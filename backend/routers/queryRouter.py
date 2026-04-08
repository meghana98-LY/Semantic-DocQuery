import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from database import get_db
from models import ChatSession, ChatMessage, User
from schemas import QueryRequest, QueryResponse, SourceItem
from auth import get_current_user
from utils.embeddings import get_embedding
from utils.llm import build_rag_response, extract_relevant_summary

router = APIRouter(prefix="/query", tags=["Query"])


# ─── Page-range parser ────────────────────────────────────────────────────────

def parse_page_range(raw: str) -> List[int]:
    """
    Convert a page-range string into a sorted, deduplicated list of page numbers.

    Accepted formats:
      "3"          → [3]
      "2-5"        → [2, 3, 4, 5]
      "1, 3, 5"    → [1, 3, 5]
      "pages 2-5"  → [2, 3, 4, 5]
      "page 3"     → [3]
    """
    # Strip unsupported text prefix
    cleaned = re.sub(r"\bpages?\b", "", raw, flags=re.IGNORECASE).strip()

    # Range format: "2-5"
    m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", cleaned)
    if m:
        start, end = int(m.group(1)), int(m.group(2))
        if start < 1 or end < 1:
            raise ValueError("Page numbers must be 1 or greater.")
        if start > end:
            raise ValueError(f"Start page ({start}) must not exceed end page ({end}).")
        if (end - start) >= 1000:
            raise ValueError("Page range spans 1000+ pages — please narrow it down.")
        return list(range(start, end + 1))

    # Comma-separated / single number: "1", "1,3,5"
    parts = [p.strip() for p in cleaned.split(",") if p.strip()]
    if parts:
        try:
            pages = [int(p) for p in parts]
        except ValueError:
            raise ValueError(
                f"Invalid page range \"{raw}\". Use formats like \"3\", \"2-5\", or \"1,3,5\"."
            )
        for p in pages:
            if p < 1:
                raise ValueError("Page numbers must be 1 or greater.")
        return sorted(set(pages))

    raise ValueError(
        f"Unrecognised page range \"{raw}\". Use formats like \"3\", \"2-5\", or \"1,3,5\"."
    )


# ─── Query endpoint ───────────────────────────────────────────────────────────

@router.post("", response_model=QueryResponse)
def ask_question(
    data: QueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not data.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    # --- Parse optional page range ---
    allowed_pages: Optional[List[int]] = None
    if data.page_range and data.page_range.strip():
        try:
            allowed_pages = parse_page_range(data.page_range)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    # --- Verify session ownership ---
    session = db.query(ChatSession).filter(
        ChatSession.id == data.session_id,
        ChatSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    # --- Generate query embedding ---
    question_embedding = get_embedding(data.question)
    if not question_embedding:
        raise HTTPException(
            status_code=500,
            detail="Could not generate embedding for the question.",
        )

    embedding_str = "[" + ",".join(str(v) for v in question_embedding) + "]"
    top_k = max(1, min(data.top_k or 5, 20))

    # --- Build optional page-filter clause ---
    page_filter_clause = ""
    params: dict = {
        "embedding":  embedding_str,
        "session_id": str(data.session_id),
        "user_id":    str(current_user.id),
        "top_k":      top_k,
    }
    if allowed_pages:
        page_filter_clause = "AND dc.page_number = ANY(:pages)"
        params["pages"] = allowed_pages

    # --- Semantic search using cosine distance (<=>)  ---
    # Embeddings are L2-normalised, so cosine_distance = 1 - cosine_similarity.
    # Similarity score = 1.0 - cosine_distance, clamped to [0, 1].
    sql = text(f"""
        SELECT
            dc.chunk_text,
            dc.page_number,
            d.filename,
            (dc.embedding <=> CAST(:embedding AS vector)) AS cosine_distance
        FROM document_chunks dc
        JOIN documents d ON dc.document_id = d.id
        WHERE d.session_id = CAST(:session_id AS uuid)
          AND d.user_id    = CAST(:user_id AS uuid)
          AND d.status     = 'completed'
          AND dc.embedding IS NOT NULL
          {page_filter_clause}
        ORDER BY dc.embedding <=> CAST(:embedding AS vector)
        LIMIT :top_k
    """)

    rows = db.execute(sql, params).fetchall()

    # Persist the user message before generating the answer
    db.add(ChatMessage(session_id=data.session_id, role="user", content=data.question))

    if not rows:
        if allowed_pages:
            answer = (
                f"Answer:\n"
                f"I could not find a reliable answer in the uploaded document.\n\n"
                f"Supporting Chunks:\n"
                f"No relevant chunks were found on page(s) \"{data.page_range}\"."
            )
        else:
            answer = (
                "Answer:\n"
                "I could not find a reliable answer in the uploaded document.\n\n"
                "Supporting Chunks:\n"
                "No relevant chunks were retrieved from the uploaded documents."
            )
        db.add(ChatMessage(session_id=data.session_id, role="assistant", content=answer, sources=[]))
        db.commit()
        return QueryResponse(answer=answer, sources=[])

    # Build sources list (used both for the response and for the LLM prompt)
    sources = []
    for row in rows:
        cosine_distance = float(row[3])
        sim_score = round(max(0.0, min(1.0, 1.0 - cosine_distance)), 4)
        snippet = row[0][:500]
        sources.append(
            {
                "document_name": row[2],
                "page_number": row[1],
                "snippet": snippet,
                "similarity_score": sim_score,
                "similarity_percent": f"{round(sim_score * 100)}%",
                "summary": extract_relevant_summary(snippet, data.question),
            }
        )

    # Generate the full structured RAG response (answer text only)
    answer = build_rag_response(data.question, sources)

    db.add(ChatMessage(session_id=data.session_id, role="assistant", content=answer, sources=sources))
    db.commit()

    return QueryResponse(
        answer=answer,
        sources=[SourceItem(**s) for s in sources],
    )