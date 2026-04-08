import uuid
from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional, List


# ─── Auth ─────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    email: Optional[str] = None


# ─── Chat Session Schemas ─────────────────────────────────────────────────────

class ChatSessionCreate(BaseModel):
    title: Optional[str] = "New Chat"


class ChatSessionResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ChatMessageResponse(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    sources: Optional[List[dict]] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Document Schemas ─────────────────────────────────────────────────────────

class DocumentResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    session_id: Optional[uuid.UUID] = None
    filename: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class UploadResponseItem(BaseModel):
    document_id: uuid.UUID
    filename: str
    status: str


class UploadResponse(BaseModel):
    message: str
    documents: List[UploadResponseItem]


# ─── Query Schemas ────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    question: str
    session_id: uuid.UUID
    top_k: Optional[int] = 5
    page_range: Optional[str] = None  # e.g. "3", "2-5", "1,3,5"


class SourceItem(BaseModel):
    document_name: str
    page_number: int
    snippet: str
    similarity_score: float
    similarity_percent: str
    summary: Optional[str] = None  # chunk-level summary relevant to the query


class QueryResponse(BaseModel):
    answer: str
    sources: List[SourceItem]


# ─── Chunk Schema (Optional / Debugging) ─────────────────────────────────────

class DocumentChunkResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    page_number: int
    chunk_text: str
    created_at: datetime

    class Config:
        from_attributes = True