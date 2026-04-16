# Semantic-DocQuery

A full-stack document intelligence platform where users upload PDFs and ask natural language questions. Answers are composed extractively from the most relevant chunks — retrieved via vector search (pgvector + MiniLM embeddings) with BM25 fallback — and returned with source references, raw chunks with summary, similarity scores, and automatic PII masking.

---

## Document Ingestion architecture

  <img src="frontend/public/ingestion-pipeline.svg" width="900"/>

---

## Query Architecture

  <img src="frontend/public/query-pipeline.svg" width="900"/>

---
## System Architecture

```
Browser (React + Vite)
        │
        ▼
FastAPI Backend (REST APIs)
        │
        ├──  PDF Ingestion Pipeline
        │       ├── PyMuPDF (PDF Parsing)
        │       ├── OCR (Tesseract for scanned PDFs)
        │       ├── Noise Cleaner (remove headers, footers, artifacts)
        │       ├── Chunker (split into semantic chunks)
        │       ├── Embedder (MiniLM via sentence-transformers)
        │       └── pgvector (store embeddings in PostgreSQL)
        │
        ├──  Query Pipeline
        │       ├── Query Embedding
        │       ├── Cosine Similarity Search (pgvector)
        │       ├── Threshold Filtering
        │       ├── Extractive Summariser
        │       └── Response Builder (Answer + Source Cards)
        │
        ▼
PostgreSQL + pgvector
```

## Tech Stack & Libraries

| Library | Version | Purpose |
|--------|--------|--------|
| FastAPI | 0.111.0 | API framework |
| Uvicorn | 0.30.1 | ASGI server |
| SQLAlchemy | 2.0.30 | ORM for database interactions |
| psycopg[binary] | 3.1.19 | PostgreSQL driver |
| pgvector | 0.2.5 | Vector similarity search |
| sentence-transformers | 2.7.0 | Embedding model (all-MiniLM-L6-v2) |
| torch | 2.5.1 | Backend for embedding models |
| transformers | 4.41.2 | Model architecture support |
| PyMuPDF | 1.24.4 | PDF parsing and text extraction |
| pytesseract | 0.3.10 | OCR for scanned documents |
| pdf2image | 1.17.0 | Convert PDF pages to images for OCR |
| Pillow | 10.3.0 | Image preprocessing for OCR |
| python-dotenv | 1.0.1 | Environment variable management |
| python-jose | 3.3.0 | JWT authentication |
| passlib[bcrypt] | 1.7.4 | Password hashing |
| python-multipart | 0.0.9 | File upload handling |
| email-validator | 2.1.1 | Email validation |
| pydantic | 2.12.5 | Data validation and serialization |
| numpy | 1.26.4 | Numerical computations |
| scikit-learn | 1.4.2 | Similarity and utility functions |
---


##  Workflow

### Ingestion Pipeline (Upload)

1. User uploads a PDF document  
2. Security validation (MIME type, magic bytes `%PDF`, file size check)  
3. Text extraction using PyMuPDF with OCR fallback for scanned/garbled pages  
4. PII masking (emails, Aadhaar, PAN, phone numbers, IFSC, etc.) before storage  
5. Content split into overlapping chunks  
6. Embeddings generated using `all-MiniLM-L6-v2`  
7. Stored in vector database (`pgvector`)  

---

### Query Pipeline

1. User submits a query  
2. Sensitive query check (blocks requests for passwords, PINs, or PII)  
3. Spell correction using Groq LLM  
4. Query converted into embedding  
5. Cosine similarity search retrieves top relevant chunks  
6. BM25 keyword fallback if vector search returns no results  
7. LLM generates answer using retrieved context  

---
# Implementation Details

## Backend Stack

| Library               | Version | Purpose                  |
| --------------------- | ------- | ------------------------ |
| FastAPI               | Latest  | API framework            |
| Uvicorn               | Latest  | ASGI server              |
| SQLAlchemy            | Latest  | ORM                      |
| pgvector              | Latest  | Vector similarity search |
| sentence-transformers | Latest  | Embedding model          |
| PyMuPDF               | Latest  | PDF parsing              |
| pytesseract           | Latest  | OCR                      |
| python-dotenv         | Latest  | Env management           |
| pydantic              | Latest  | Data validation          |

---
## Frontend Stack

| Library | Version | Purpose |
|--------|--------|--------|
| React | 19.2.4 | UI library for building components |
| React Router | 7.14.0 | Client-side routing |
| Vite | 8.0.4 | Fast build tool and development server |

---

## Infrastructure Choices

| Component | Choice | Reason |
|----------|--------|--------|
| Database | PostgreSQL + pgvector | Efficient vector similarity search |
| Embedding Model | all-MiniLM-L12-v2 | Fast, lightweight, 384-dimensional embeddings |
| Summarisation | Extractive (local) | No external API dependency; preserves factual accuracy |

---

# Project Structure

```
doc-query/
│
├── backend/
│ ├── routers/ # API route handlers
│ │ ├── authRouter.py # Authentication endpoints
│ │ ├── chatRouter.py # Chat/session handling
│ │ ├── queryRouter.py # Query processing endpoints
│ │ └── uploadRouter.py # Document upload endpoints
│ │
│ ├── utils/ # Core processing logic
│ │ ├── chunking.py # Text chunking logic
│ │ ├── embeddings.py # Embedding generation
│ │ ├── llm.py # LLM interaction layer
│ │ ├── masking.py # Data masking utilities
│ │ └── pdf_parser.py # PDF parsing & extraction
│ │
│ ├── uploads/ # Stored uploaded documents
│ ├── auth.py # Authentication logic (JWT, hashing)
│ ├── database.py # DB connection & session management
│ ├── main.py # FastAPI app entry point
│ ├── models.py # Database models (ORM)
│ ├── schemas.py # Pydantic schemas
│ ├── requirements.txt # Backend dependencies
│ └── .env.example # Environment variables template
│
├── frontend/
│ ├── src/
│ │ ├── api/ # API integration layer
│ │ │ └── client.js
│ │ │
│ │ ├── components/ # Reusable UI components
│ │ │ ├── AssistantContent.jsx
│ │ │ ├── HighlightedText.jsx
│ │ │ ├── Navbar.jsx
│ │ │ ├── ProtectedRoute.jsx
│ │ │ ├── RedactedText.jsx
│ │ │ └── SourceCards.jsx
│ │ │
│ │ ├── pages/ # Application pages
│ │ │ ├── Dashboard.jsx
│ │ │ ├── Landing.jsx
│ │ │ ├── Login.jsx
│ │ │ ├── Register.jsx
│ │ │ └── SessionChat.jsx
│ │ │
│ │ ├── App.jsx # Root component
│ │ ├── App.css
│ │ ├── index.css
│ │ └── main.jsx # Entry point
│ │
│ ├── public/ # Static assets
│ │ ├── architecture.svg
│ │ ├── ingestion-pipeline.svg
│ │ └── query-pipeline.svg
│ │
│ ├── index.html
│ ├── vite.config.js
│ └── package.json # Frontend dependencies
│
├── sample-docs/ # Sample PDFs for testing
├── package.json # Root config (if applicable)
└── README.md
---
```

# Setup & Installation

## Prerequisites

* Python 3.12+ (developed on 3.12.5, system has 3.13.2 — not 3.10)
* Node.js 20+ (developed on v22.14.0 — not 18+)
* PostgreSQL (with pgvector extension)
* Tesseract OCR
* Poppler (for PDF processing)
---

**Database Setup**
```sql
CREATE EXTENSION IF NOT EXISTS vector;
-- Tables are auto-created by SQLAlchemy on first backend start
```

**Backend Setup**
```bash
git clone <your-repo-url>
cd sem/backend

python -m venv venv

# Linux/Mac:
source venv/bin/activate
# Windows:
venv\Scripts\activate

pip install -r requirements.txt

# Create .env manually 
# Add these to .env:
# DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/dbname
# SECRET_KEY=your-secret-key
# GROQ_API_KEY=your-groq-api-key
# TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe   # Windows
# POPPLER_PATH=C:\poppler\bin                                   # Windows

uvicorn main:app --reload
```

**Frontend Setup**
```bash
cd sem/frontend
npm install
npm run dev
```
**run both together from the root:**
```bash
cd sem
npm install       # installs concurrently + wait-on, also runs frontend npm install
npm run dev       # starts backend first, then frontend once backend is ready

```
---
# Security Notes

* No hardcoded credentials
* All secrets managed via `.env`
* Input validation using Pydantic
* Secure file handling

---

# Features

* Multi-document support
* Semantic search with similarity scoring
* Source attribution with page numbers
* OCR support for scanned PDFs
* Clean and modular architecture

---
# Limitations
## 1. Latency & Scalability Constraints
Response time depends on:
- Vector search performance  
- LLM inference latency  

Performance may degrade with larger datasets or high concurrent usage.  
No caching or optimization layer is implemented.

## 2. Security & Data Privacy
The system lacks:
- Role-based access control (RBAC)  
- Advanced encryption for stored documents  

If external APIs are used, document data may be transmitted to third-party services.

## 3. Limited User Feedback Mechanism
Users cannot:
- Provide feedback on responses  
- View confidence scores or sources  

No feedback loop exists for improving system performance.

---
## Future Enhancements

- Enhance document processing with OCR improvements and structured data extraction  
- Enable real-time and incremental indexing for dynamic document updates  
- Use domain-specific or fine-tuned embedding models for better semantic understanding  
- Strengthen security with RBAC, encryption, and secure API communication  
- Introduce evaluation metrics for retrieval accuracy and answer quality  
- Implement user feedback system for continuous improvement  
 
---

# License
MIT License
