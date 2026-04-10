# Semantic-DocQuery

A full-stack web application that lets users upload PDF documents, ask natural language questions, and retrieve precise, readable answers using semantic search — without any external LLM API.

---

## Table of Contents

1. [High-Level Design](#high-level-design)
2. [Implementation Details](#implementation-details)
3. [Steps to Build and Test](#steps-to-build-and-test)

---

## High-Level Design

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Browser (React + Vite)                     │
│   Login / Register → Dashboard → Session Chat → Upload & Query      │
└────────────────────────────┬────────────────────────────────────────┘
                             │ HTTP/REST (JWT auth)
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      FastAPI Backend                                │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────────┐ │
│  │  Auth Router │  │ Chat Router  │  │      Upload Router        │ │
│  │  /auth/*     │  │ /chat/*      │  │      /upload              │ │
│  └──────────────┘  └──────────────┘  └───────────┬───────────────┘ │
│                                                   │ BackgroundTask  │
│  ┌────────────────────────────────────────────────▼───────────────┐ │
│  │                    PDF Ingestion Pipeline                      │ │
│  │                                                                │ │
│  │  PDF File ──► PyMuPDF (text extraction)                       │ │
│  │                   │                                           │ │
│  │                   ▼  (if page text < 30 chars)                │ │
│  │             Tesseract OCR  ──► OCR Noise Cleaner              │ │
│  │                   │              (token-level filter)         │ │
│  │                   ▼                                           │ │
│  │            Text Chunker (800 chars, 150 overlap)              │ │
│  │                   │                                           │ │
│  │                   ▼                                           │ │
│  │     SentenceTransformer Encoder (all-MiniLM-L6-v2)           │ │
│  │                   │                                           │ │
│  │                   ▼                                           │ │
│  │         PostgreSQL + pgvector  (stores chunks + embeddings)   │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                     Query Router  /query                    │   │
│  │                                                             │   │
│  │  User Question ──► Trivial query guard (< 3-char words)    │   │
│  │                         │                                   │   │
│  │                         ▼                                   │   │
│  │              Embed question (MiniLM)                        │   │
│  │                         │                                   │   │
│  │                         ▼                                   │   │
│  │     pgvector cosine search  (top-K chunks, optional         │   │
│  │                              page-range filter)             │   │
│  │                         │                                   │   │
│  │                         ▼                                   │   │
│  │     Similarity threshold filter  (score ≥ 0.30)            │   │
│  │                         │                                   │   │
│  │              ┌──────────┴──────────┐                        │   │
│  │              │                     │                        │   │
│  │    Off-topic / no docs         Relevant chunks              │   │
│  │    → document overview         → Extractive summariser      │   │
│  │      + re-query prompt           (sentence scoring,         │   │
│  │                                   OCR noise removal,        │   │
│  │                                   ranked top-6 sentences)   │   │
│  │                                        │                    │   │
│  │                                        ▼                    │   │
│  │                              Structured answer +            │   │
│  │                              Source cards (chunk,           │   │
│  │                              page, similarity %)            │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│              PostgreSQL  (hosted / local)                           │
│   Tables: users · chat_sessions · chat_messages ·                  │
│           documents · document_chunks (pgvector)                   │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Data Flow

| Stage | Input | Output |
|---|---|---|
| **PDF Ingestion** | Uploaded PDF file | Per-page text (native or OCR) |
| **Text Cleaning** | Raw OCR text | Noise-filtered plain text |
| **Chunking** | Page text | 800-char overlapping chunks |
| **Embedding** | Text chunk | 384-dim L2-normalised vector |
| **Storage** | Chunk + vector | `document_chunks` row in PostgreSQL |
| **Semantic Search** | Question embedding | Top-K chunks by cosine similarity |
| **Summarisation** | Retrieved chunks | Scored, de-duplicated prose sentences |
| **Response** | Sentences + metadata | Answer paragraph + source cards |

---

## Implementation Details

### Tools & Libraries

#### Backend

| Library | Version | Purpose | Rationale |
|---|---|---|---|
| **FastAPI** | 0.111 | REST API framework | Async-first, automatic OpenAPI docs, Pydantic validation out of the box |
| **Uvicorn** | 0.30 | ASGI server | Lightweight, production-grade runner for FastAPI |
| **SQLAlchemy** | 2.0 | ORM | Mature, database-agnostic; v2 style async-compatible |
| **psycopg[binary]** | 3.1 | PostgreSQL driver | Modern async-capable driver; required by SQLAlchemy 2 |
| **pgvector** | 0.2 | Vector similarity in Postgres | Enables cosine search (`<=>`) directly in SQL; no separate vector DB needed |
| **python-jose** | 3.3 | JWT creation / validation | Lightweight, no external service required for auth |
| **passlib[bcrypt]** | 1.7 | Password hashing | Industry-standard bcrypt; pluggable backend |
| **python-multipart** | 0.0.9 | File upload parsing | Required by FastAPI for `UploadFile` |
| **sentence-transformers** | 2.7 | Sentence embeddings | `all-MiniLM-L6-v2` produces high-quality 384-dim embeddings fast, runs locally without API cost |
| **PyMuPDF (fitz)** | 1.24 | Native PDF text extraction | Fast, accurate extraction from text-based PDFs |
| **pytesseract** | 0.3 | OCR fallback | Handles scanned / image-only PDF pages |
| **pdf2image** | 1.17 | PDF → image conversion | Required to feed pages to Tesseract |
| **Pillow** | 10.3 | Image processing | Dependency of pdf2image and pytesseract |
| **numpy** | 1.26 | Vector normalisation | L2-normalise embeddings before storage for correct cosine distance |
| **python-dotenv** | 1.0 | Environment config | Keeps secrets (DB URL, JWT secret) out of source code |

#### Frontend

| Library | Version | Purpose | Rationale |
|---|---|---|---|
| **React** | 19 | UI framework | Component model suits chat + document panel layout |
| **React Router DOM** | 7 | Client-side routing | SPA navigation with protected routes |
| **Vite** | 8 | Build tool | Instant HMR, minimal config, fast production builds |

#### Infrastructure

| Component | Choice | Rationale |
|---|---|---|
| **Database** | PostgreSQL | Native pgvector extension; ACID compliance for user/session data |
| **Vector index** | pgvector (`<=>` cosine) | Eliminates a separate vector store; cosine distance on L2-normalised vectors equals cosine similarity |
| **Embedding model** | `all-MiniLM-L6-v2` | 22 M parameters, 384 dims — fast on CPU, strong semantic quality, runs fully offline |
| **Summarisation** | Extractive (sentence scoring) | Zero hallucination risk; answers are always grounded in document text |

---

## Steps to Build and Test

### Prerequisites

- Python 3.10+
- Node.js 18+
- PostgreSQL 14+ with the **pgvector** extension installed
- Tesseract OCR installed on the system ([Windows installer](https://github.com/UB-Mannheim/tesseract/wiki) / `apt install tesseract-ocr` on Linux)
- Poppler installed for pdf2image ([Windows binaries](https://github.com/oschwartz10612/poppler-windows/releases) / `apt install poppler-utils` on Linux)

---

### 1. Clone the Repository

```bash
git clone https://github.com/<your-username>/Semantic-DocQuery.git
cd Semantic-DocQuery
```

---

### 2. Configure Environment Variables

Create `backend/.env`:

```env
DATABASE_URL=postgresql+psycopg://<user>:<password>@<host>:<port>/<dbname>
SECRET_KEY=your_jwt_secret_key_here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60

# Optional — only needed on Windows or non-default installs
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
POPPLER_PATH=C:\poppler\Library\bin
```

---

### 3. Enable pgvector in PostgreSQL

Connect to your database and run:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

---

### 4. Set Up the Backend

```bash
cd backend

# Create and activate virtual environment
python -m venv venv

# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start the API server (tables are auto-created on first run)
uvicorn main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`.  
Interactive docs: `http://localhost:8000/docs`.

---

### 5. Set Up the Frontend

```bash
cd frontend

# Install dependencies
npm install

# Start the development server
npm run dev
```

The app will open at `http://localhost:5173`.

---

### 6. Using the Application

1. **Register** a new account at `/register`.
2. **Log in** at `/login`.
3. On the **Dashboard**, create a new chat session.
4. Inside the session, **upload one or more PDF files**.
5. Wait for the status indicator to change to **Completed** (processing runs in the background).
6. **Type a question** about the document content and press Ask.
7. The assistant returns a structured answer with source cards showing the matched page, similarity score, and a per-chunk relevant summary.

---

### 7. Build for Production

**Backend** — run behind a reverse proxy (e.g. Nginx) with Gunicorn:

```bash
pip install gunicorn
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

Update `main.py` `allow_origins` to your production frontend URL.

**Frontend**:

```bash
cd frontend
npm run build        # outputs to frontend/dist/
npm run preview      # local preview of production build
```

---

### 8. Project Structure

```
sem/
├── backend/
│   ├── main.py               # FastAPI app entry point
│   ├── auth.py               # JWT authentication helpers
│   ├── database.py           # SQLAlchemy engine & session
│   ├── models.py             # ORM models (User, Session, Document, Chunk)
│   ├── schemas.py            # Pydantic request / response schemas
│   ├── requirements.txt
│   ├── routers/
│   │   ├── authRouter.py     # /auth  — register, login
│   │   ├── chatRouter.py     # /chat  — session CRUD, message history
│   │   ├── uploadRouter.py   # /upload — PDF ingestion pipeline
│   │   └── queryRouter.py    # /query — semantic search & answer generation
│   └── utils/
│       ├── pdf_parser.py     # PyMuPDF extraction + Tesseract OCR fallback
│       ├── chunking.py       # Overlapping text chunker
│       ├── embeddings.py     # SentenceTransformer wrapper (MiniLM)
│       └── llm.py            # Extractive summariser & OCR noise filters
└── frontend/
    ├── src/
    │   ├── App.jsx
    │   ├── pages/
    │   │   ├── Login.jsx
    │   │   ├── Register.jsx
    │   │   ├── Dashboard.jsx
    │   │   └── SessionChat.jsx   # Main chat + upload + results UI
    │   ├── components/
    │   │   ├── Navbar.jsx
    │   │   └── ProtectedRoute.jsx
    │   └── api/
    │       └── client.js         # Axios/fetch wrappers for all endpoints
    └── public/
```

---

## License

MIT
