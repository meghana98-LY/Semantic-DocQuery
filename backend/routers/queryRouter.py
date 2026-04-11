import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from database import get_db
from models import ChatSession, ChatMessage, Document, User
from schemas import QueryRequest, QueryResponse, SourceItem
from auth import get_current_user
from utils.embeddings import get_embedding
from utils.llm import build_rag_response, build_summary_response, extract_relevant_summary, strip_encoding_noise
from utils.masking import mask_sensitive_data

router = APIRouter(prefix="/query", tags=["Query"])


# ─── Sensitive-query detector ─────────────────────────────────────────────────

_SENSITIVE_RE = re.compile(
    r"\b(password|passwd|pwd|passcode|passphrase|"
    r"pin|upi\s*pin|atm\s*pin|mpin|m-pin|"
    r"otp|cvv|"
    r"email\s*address|e-?mail|"
    r"phone\s*number|mobile\s*number|contact\s*number|"
    r"account\s*(?:no|number|num)|bank\s*account|"
    r"card\s*(?:no|number)|credit\s*card|debit\s*card|"
    r"pan\s*(?:card|no|number)?|aadhaar|aadhar|"
    r"ifsc|upi\s*id|vpa|"
    r"date\s*of\s*birth|dob|"
    r"ssn|social\s*security)\b",
    re.IGNORECASE,
)

_SENSITIVE_ANSWER = (
    "This information is classified as sensitive or confidential and cannot be shared. "
    "Passwords, PINs, email addresses, account numbers, card details, and similar personal "
    "data are protected and will not be disclosed."
)


def _is_sensitive_query(question: str) -> bool:
    """Return True when the query is explicitly asking for sensitive/PII data."""
    return bool(_SENSITIVE_RE.search(question))


# ─── Meta-query detector ──────────────────────────────────────────────────────

# Document-type nouns — queries that are just "give <noun>" or "show <noun>"
# should always retrieve top chunks regardless of similarity score.
_DOC_NOUN_RE = re.compile(
    r"\b(bill|bills|invoice|invoices|statement|statements|"
    r"transaction|transactions|ledger|ledgers|receipt|receipts|"
    r"report|reports|record|records|entry|entries|payment|payments|"
    r"balance|balances|account|accounts|cheque|cheques|voucher|vouchers|"
    r"contract|contracts|agreement|agreements|certificate|certificates|"
    r"document|documents|data|contents?|details?|information|info)\b",
    re.IGNORECASE,
)

# Also matches any query that references a specific document by number/name
_DOC_REF_RE = re.compile(
    r"\bdoc(?:ument)?\s*\d+|\bdoc(?:ument)?\s*[a-z]\b",
    re.IGNORECASE,
)

_META_RE = re.compile(
    r"\b(summar(y|ize|ise|ies)|overview|describe|explain|"
    r"contents?\s*of|"
    r"what\s+(is|are|does)\s+(this|it)\b|what\s+is\s+(in|on)\b|"
    r"tell\s+me|show\s+me|list\s+(all\s+)?|"
    r"give\s+(me\s+)?(the\s+)?(content|summary|overview|info|detail|list|all)|"
    r"what\s+is\s+(about)|about\s+(the\s+)?doc(ument)?\d*|"
    r"page\s+\d+|pages?\s+\d+)\b",
    re.IGNORECASE,
)

# Queries containing specific dates or monetary amounts are always factual
_SPECIFIC_QUERY_RE = re.compile(
    r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b"
    r"|\b\d{4}[-/]\d{2}[-/]\d{2}\b"
    r"|\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b"
    r"|₹\s*[\d,]+"
    r"|\bRs\.?\s*[\d,]+"
    r"|\b\d[\d,]+\.\d{2}\b",
    re.IGNORECASE,
)


def _is_meta_query(question: str) -> bool:
    """
    Returns True for document-level meta queries (summary, page contents, overview,
    or bare document-type noun queries like 'give bill', 'show transactions').
    These bypass the similarity threshold and always return top chunks.

    Queries that contain specific dates, amounts, or IDs are always factual
    and are never treated as meta, regardless of other patterns.
    """
    # Factual queries with dates/amounts are never meta
    if _SPECIFIC_QUERY_RE.search(question):
        return False
    if _META_RE.search(question):
        return True
    # Any query referencing a specific document by number is always a meta query
    if _DOC_REF_RE.search(question):
        return True
    # Short queries (≤5 words) whose non-stop content is a document-type noun
    words = re.findall(r"\b\w+\b", question)
    if len(words) <= 5 and _DOC_NOUN_RE.search(question):
        return True
    return False


# ─── Inline page-reference extractor ─────────────────────────────────────────

def _extract_inline_page_range(question: str) -> Optional[List[int]]:
    """
    Detect page references embedded in the question text (not the page_range field).
    Examples:
      "give contents of page 3"   → [3]
      "summarize pages 2 to 5"    → [2, 3, 4, 5]
      "what is on pages 1-4"      → [1, 2, 3, 4]
    Returns None if no page reference is found.
    """
    # Range: "page(s) N-M" or "page(s) N to M"
    m = re.search(r"\bpages?\s+(\d+)\s*(?:-|to)\s*(\d+)\b", question, re.IGNORECASE)
    if m:
        start, end = int(m.group(1)), int(m.group(2))
        if 1 <= start <= end and (end - start) < 100:
            return list(range(start, end + 1))

    # Single: "page N"
    m = re.search(r"\bpages?\s+(\d+)\b", question, re.IGNORECASE)
    if m:
        page = int(m.group(1))
        if page >= 1:
            return [page]

    return None


# ─── Off-topic response helper ────────────────────────────────────────────────

def _build_off_topic_response(
    db: Session,
    session_id,
    page_range: Optional[str] = None,
) -> str:
    """
    Returns a message listing the uploaded documents and prompts the user
    to ask a question relevant to their content.
    """
    docs = (
        db.query(Document)
        .filter(
            Document.session_id == session_id,
            Document.status == "completed",
        )
        .order_by(Document.created_at)
        .all()
    )

    if docs:
        doc_list = "\n".join(f"  • {d.filename}" for d in docs)
        response = (
            "Your query does not seem to be related to the uploaded documents.\n\n"
            f"The following document(s) are available in this session:\n{doc_list}\n\n"
            "Please ask a question related to the content of these documents."
        )
    else:
        response = (
            "No documents have been processed in this session yet. "
            "Please upload a document first and then ask a question about its content."
        )

    if page_range:
        response += f'\n\n(No relevant content was found on page(s) "{page_range}" either.)'

    return response


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


# ─── BM25 keyword-search fallback ───────────────────────────────────────────

def _run_bm25_search(
    db: Session,
    question: str,
    session_id,
    user_id,
    page_filter_clause: str = "",
    extra_params: Optional[dict] = None,
    top_k: int = 4,
) -> list[dict]:
    """
    PostgreSQL full-text search (ts_rank_cd) used as a BM25 keyword fallback
    when cosine similarity returns no chunks above the relevance threshold.

    Returns sources in the same dict format as the main vector search so that
    build_rag_response / build_summary_response can consume them directly.
    """
    params: dict = {
        "session_id": str(session_id),
        "user_id":    str(user_id),
        "query_text": question,
        "top_k":      top_k,
    }
    if extra_params:
        params.update(extra_params)

    bm25_sql = text(f"""
        SELECT
            dc.chunk_text,
            dc.page_number,
            d.filename,
            ts_rank_cd(
                to_tsvector('english', dc.chunk_text),
                plainto_tsquery('english', :query_text)
            ) AS bm25_rank
        FROM document_chunks dc
        JOIN documents d ON dc.document_id = d.id
        WHERE d.session_id = CAST(:session_id AS uuid)
          AND d.user_id    = CAST(:user_id AS uuid)
          AND d.status     = 'completed'
          AND to_tsvector('english', dc.chunk_text)
              @@ plainto_tsquery('english', :query_text)
          {page_filter_clause}
        ORDER BY bm25_rank DESC
        LIMIT :top_k
    """)

    rows = db.execute(bm25_sql, params).fetchall()
    sources: list[dict] = []
    for row in rows:
        bm25_rank  = float(row[3])
        # ts_rank_cd is already in [0, 1]; normalise to the same field name
        sim_score  = round(min(1.0, bm25_rank), 4)
        raw_snip = strip_encoding_noise(row[0][:1500])
        last_b = max(raw_snip.rfind('. '), raw_snip.rfind('! '), raw_snip.rfind('? '))
        if last_b > 200:
            raw_snip = raw_snip[:last_b + 1]
        snippet    = raw_snip
        sources.append({
            "document_name":    row[2],
            "page_number":      row[1],
            "snippet":          snippet,
            "similarity_score": sim_score,
            "similarity_percent": f"{round(sim_score * 100)}%",
            "summary":          extract_relevant_summary(snippet, question),
            "retrieval_method": "bm25",   # informational tag
        })
    return sources


# ─── Document name extractor ──────────────────────────────────────────────────

def _extract_doc_filter(question: str, db: Session, session_id, user_id) -> Optional[List[str]]:
    """
    If the question mentions a document by name (e.g. 'document1', 'doc2',
    'Document1.pdf'), return the matching filenames from the DB so results
    can be filtered to that document only.
    Returns None if no document reference is detected.
    """
    # Look for patterns like: document1, doc1, document 1, doc 2, document1.pdf
    m = re.search(
        r'\b(doc(?:ument)?\s*(\d+)(?:\.pdf)?)\b',
        question, re.IGNORECASE,
    )
    if not m:
        return None

    doc_num = m.group(2)  # e.g. "1", "2", "3"

    # Fetch all completed filenames for this session
    docs = db.query(Document.filename).filter(
        Document.session_id == session_id,
        Document.user_id == user_id,
        Document.status == "completed",
    ).all()

    matched = [
        d.filename for d in docs
        if doc_num in re.findall(r'\d+', d.filename)
    ]
    return matched if matched else None


# ─── Query endpoint ───────────────────────────────────────────────────────────

@router.post("", response_model=QueryResponse)
def ask_question(
    data: QueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not data.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    # --- Block queries explicitly asking for sensitive / PII data ---
    if _is_sensitive_query(data.question):
        session_check = db.query(ChatSession).filter(
            ChatSession.id == data.session_id,
            ChatSession.user_id == current_user.id,
        ).first()
        if not session_check:
            raise HTTPException(status_code=404, detail="Session not found.")
        db.add(ChatMessage(session_id=data.session_id, role="user", content=data.question))
        db.add(ChatMessage(session_id=data.session_id, role="assistant", content=_SENSITIVE_ANSWER, sources=[]))
        db.commit()
        return QueryResponse(answer=_SENSITIVE_ANSWER, sources=[])

    # --- Reject trivial / greeting queries (no words with 3+ chars) ---
    meaningful_words = [w for w in re.findall(r"\b\w+\b", data.question) if len(w) >= 3]
    if not meaningful_words:
        # Verify session exists first so we can persist the exchange
        session_check = db.query(ChatSession).filter(
            ChatSession.id == data.session_id,
            ChatSession.user_id == current_user.id,
        ).first()
        if not session_check:
            raise HTTPException(status_code=404, detail="Session not found.")
        db.add(ChatMessage(session_id=data.session_id, role="user", content=data.question))
        answer = _build_off_topic_response(db, data.session_id)
        db.add(ChatMessage(session_id=data.session_id, role="assistant", content=answer, sources=[]))
        db.commit()
        return QueryResponse(answer=answer, sources=[])

    # --- Parse optional page range (explicit field first, then inline in question) ---
    allowed_pages: Optional[List[int]] = None
    if data.page_range and data.page_range.strip():
        try:
            allowed_pages = parse_page_range(data.page_range)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    else:
        # Auto-detect page references inside the question text
        allowed_pages = _extract_inline_page_range(data.question)

    # Detect meta/navigation queries — these bypass the similarity threshold
    is_meta = _is_meta_query(data.question)

    # --- Verify session ownership ---
    session = db.query(ChatSession).filter(
        ChatSession.id == data.session_id,
        ChatSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    corrected_question = data.question

    # --- Generate query embedding ---
    question_embedding = get_embedding(corrected_question)
    if not question_embedding:
        raise HTTPException(
            status_code=500,
            detail="Could not generate embedding for the question.",
        )

    embedding_str = "[" + ",".join(str(v) for v in question_embedding) + "]"
    # Fetch more than needed so filtering still leaves 4 good chunks.
    # Meta queries get extra width; normal queries fetch 8 to keep the best 4.
    top_k = max(1, min(data.top_k or 4, 20))
    if is_meta:
        top_k = min(top_k * 3, 20)
    else:
        top_k = min(top_k * 2, 20)   # fetch 8, display 4

    # --- Build optional page-filter and doc-filter clauses ---
    page_filter_clause = ""
    doc_filter_clause = ""
    params: dict = {
        "embedding":  embedding_str,
        "session_id": str(data.session_id),
        "user_id":    str(current_user.id),
        "top_k":      top_k,
    }
    if allowed_pages:
        page_filter_clause = "AND dc.page_number = ANY(:pages)"
        params["pages"] = allowed_pages

    # Filter by document name if mentioned in the question
    matched_docs = _extract_doc_filter(data.question, db, data.session_id, current_user.id)
    if matched_docs:
        doc_filter_clause = "AND d.filename = ANY(:doc_names)"
        params["doc_names"] = matched_docs

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
          {doc_filter_clause}
        ORDER BY dc.embedding <=> CAST(:embedding AS vector)
        LIMIT :top_k
    """)

    rows = db.execute(sql, params).fetchall()

    # Persist the user message before generating the answer
    db.add(ChatMessage(session_id=data.session_id, role="user", content=data.question))

    if not rows:
        # Check whether any completed documents exist in this session
        session_has_docs = db.query(Document).filter(
            Document.session_id == data.session_id,
            Document.status == "completed",
        ).first() is not None

        if session_has_docs:
            # ── BM25 fallback: vector index missed; try keyword search ────────
            bm25_sources = _run_bm25_search(
                db, corrected_question, data.session_id, current_user.id,
                page_filter_clause + " " + doc_filter_clause,
                {**(({"pages": allowed_pages}) if allowed_pages else {}), **(({"doc_names": matched_docs}) if matched_docs else {})},
            )
            if bm25_sources:
                for s in bm25_sources:
                    s["snippet"] = mask_sensitive_data(s["snippet"])
                    s["summary"] = mask_sensitive_data(s.get("summary", ""))
                answer = mask_sensitive_data(build_rag_response(corrected_question, bm25_sources))
                db.add(ChatMessage(
                    session_id=data.session_id, role="assistant",
                    content=answer, sources=bm25_sources,
                ))
                db.commit()
                return QueryResponse(
                    answer=answer,
                    sources=[SourceItem(**{k: v for k, v in s.items() if k != "retrieval_method"}) for s in bm25_sources],
                )
            # BM25 also found nothing
            answer = _build_off_topic_response(db, data.session_id, data.page_range if allowed_pages else None)
        else:
            answer = _build_off_topic_response(db, data.session_id, data.page_range if allowed_pages else None)
        db.add(ChatMessage(session_id=data.session_id, role="assistant", content=answer, sources=[]))
        db.commit()
        return QueryResponse(answer=answer, sources=[])

    # Build sources list (used both for the response and for the LLM prompt)
    sources = []
    for row in rows:
        cosine_distance = float(row[3])
        sim_score = round(max(0.0, min(1.0, 1.0 - cosine_distance)), 4)
        raw_text = strip_encoding_noise(row[0][:1500])
        # Cut at the last sentence boundary so snippets never end mid-sentence
        last_boundary = max(raw_text.rfind('. '), raw_text.rfind('! '), raw_text.rfind('? '))
        if last_boundary > 200:
            raw_text = raw_text[:last_boundary + 1]
        snippet = mask_sensitive_data(raw_text)
        sources.append(
            {
                "document_name": row[2],
                "page_number": row[1],
                "snippet": snippet,
                "similarity_score": sim_score,
                "similarity_percent": f"{round(sim_score * 100)}%",
                "summary": mask_sensitive_data(extract_relevant_summary(snippet, corrected_question)),
            }
        )

    # Always keep the top 4 retrieved chunks sorted by similarity score —
    # no minimum threshold so every query always surfaces 4 results.
    # For meta queries with a specific proper noun absent from all chunks,
    # treat as off-topic (entity genuinely not in the document).
    if is_meta:
        _meta_stop = {"give", "show", "tell", "list", "get", "find", "the",
                      "me", "a", "an", "about", "summary", "overview", "of"}
        query_words = corrected_question.split()
        specific_entity = next(
            (w for w in query_words
             if w[0].isupper() and w.lower() not in _meta_stop and len(w) > 2),
            None
        )
        if specific_entity:
            all_chunk_text = " ".join(s["snippet"] for s in sources)
            entity_in_chunks = specific_entity.lower() in all_chunk_text.lower()
            max_score = max((s["similarity_score"] for s in sources), default=0)
            if not entity_in_chunks and max_score < 0.45:
                sources = []

    # Sort by similarity descending and keep the top 4 most relevant chunks
    sources = sorted(sources, key=lambda s: s["similarity_score"], reverse=True)[:4]

    # If nothing passes the similarity threshold, try BM25 keyword fallback
    if not sources:
        bm25_sources = _run_bm25_search(
            db, data.question, data.session_id, current_user.id,
            page_filter_clause + " " + doc_filter_clause,
            {**({"pages": allowed_pages} if allowed_pages else {}), **({"doc_names": matched_docs} if matched_docs else {})},
        )
        if bm25_sources:
            for s in bm25_sources:
                s["snippet"] = mask_sensitive_data(s["snippet"])
                s["summary"] = mask_sensitive_data(s.get("summary", ""))
            answer = mask_sensitive_data(build_rag_response(corrected_question, bm25_sources))
            db.add(ChatMessage(
                session_id=data.session_id, role="assistant",
                content=answer, sources=bm25_sources,
            ))
            db.commit()
            return QueryResponse(
                answer=answer,
                sources=[SourceItem(**{k: v for k, v in s.items() if k != "retrieval_method"}) for s in bm25_sources],
            )
        # BM25 also found nothing
        answer = _build_off_topic_response(db, data.session_id, data.page_range if allowed_pages else None)
        db.add(ChatMessage(session_id=data.session_id, role="assistant", content=answer, sources=[]))
        db.commit()
        return QueryResponse(answer=answer, sources=[])

    # Generate the full structured RAG response (answer text only)
    if is_meta:
        answer = mask_sensitive_data(build_summary_response(sources, corrected_question))
    else:
        answer = mask_sensitive_data(build_rag_response(corrected_question, sources))

    db.add(ChatMessage(session_id=data.session_id, role="assistant", content=answer, sources=sources))
    db.commit()

    return QueryResponse(
        answer=answer,
        sources=[SourceItem(**s) for s in sources],
    )