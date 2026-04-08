import os
import uuid

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from database import get_db, SessionLocal
from models import Document, DocumentChunk, ChatSession, User
from auth import get_current_user
from utils.pdf_parser import extract_text_by_page
from utils.chunking import chunk_text
from utils.embeddings import get_embedding
from schemas import UploadResponse, UploadResponseItem

router = APIRouter(prefix="/upload", tags=["Upload"])

UPLOAD_DIR = "uploads"
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024   # 50 MB per file
MAX_FILES_PER_REQUEST = 20
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ─── PROCESS DOCUMENT (background, own DB session) ───────────────────────────

def process_document(file_path: str, document_id: uuid.UUID):
    """
    Runs after the response is sent.
    Creates its own DB session — safe to use after the request session closes.
    """
    db = SessionLocal()
    try:
        pages = extract_text_by_page(file_path)
        chunk_counter = 0

        for page in pages:
            page_number = page["page_number"]
            page_text = page["text"]

            for chunk in chunk_text(page_text):
                embedding = get_embedding(chunk)

                db_chunk = DocumentChunk(
                    document_id=document_id,
                    chunk_index=chunk_counter,
                    page_number=page_number,
                    chunk_text=chunk,
                    embedding=embedding if embedding else None
                )
                db.add(db_chunk)
                chunk_counter += 1

        document = db.query(Document).filter(Document.id == document_id).first()
        if document:
            document.status = "completed"
        db.commit()

    except Exception:
        db.rollback()
        document = db.query(Document).filter(Document.id == document_id).first()
        if document:
            document.status = "failed"
            db.commit()
    finally:
        db.close()


# ─── UPLOAD ENDPOINT ─────────────────────────────────────────────────────────

@router.post("", response_model=UploadResponse)
async def upload_documents(
    background_tasks: BackgroundTasks,
    session_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Verify the session exists and belongs to this user
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.user_id == current_user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not files:
        raise HTTPException(status_code=400, detail="No files provided.")

    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files. Maximum {MAX_FILES_PER_REQUEST} files per request."
        )

    uploaded_docs = []

    for file in files:
        # --- Extension check ---
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=400,
                detail=f"Only PDF files are accepted. \"{file.filename}\" is not allowed."
            )

        content = await file.read()

        # --- Empty file check ---
        if len(content) == 0:
            raise HTTPException(
                status_code=400,
                detail=f"File \"{file.filename}\" is empty and cannot be processed."
            )

        # --- File size check ---
        if len(content) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"File \"{file.filename}\" exceeds the 50 MB limit "
                    f"({len(content) // (1024 * 1024)} MB)."
                )
            )

        # --- PDF magic-bytes check (prevent disguised uploads) ---
        if not content.startswith(b"%PDF"):
            raise HTTPException(
                status_code=400,
                detail=f"\"{file.filename}\" does not appear to be a valid PDF file."
            )

        file_id = str(uuid.uuid4())
        safe_name = os.path.basename(file.filename)  # strip any path-traversal attempt
        file_path = os.path.join(UPLOAD_DIR, f"{file_id}_{safe_name}")

        with open(file_path, "wb") as f:
            f.write(content)

        new_document = Document(
            user_id=current_user.id,
            session_id=session_id,
            filename=file.filename,
            file_path=file_path,
            mime_type=file.content_type,
            status="processing"
        )
        db.add(new_document)
        db.commit()
        db.refresh(new_document)

        # Schedule background processing with its own DB session
        background_tasks.add_task(process_document, file_path, new_document.id)

        uploaded_docs.append(UploadResponseItem(
            document_id=new_document.id,
            filename=file.filename,
            status="processing"
        ))

    return UploadResponse(
        message=f"{len(uploaded_docs)} file(s) uploaded. Processing started.",
        documents=uploaded_docs
    )