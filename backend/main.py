from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import Base, engine, SessionLocal

from routers import authRouter, uploadRouter, queryRouter, chatRouter

# Create all tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Semantic Document Query API")


@app.on_event("startup")
def warmup_db():
    """Open and immediately close a DB connection to warm up the pool on startup."""
    db = SessionLocal()
    try:
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
    finally:
        db.close()

# CORS — allow all localhost variants for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(authRouter.router)
app.include_router(chatRouter.router)
app.include_router(uploadRouter.router)
app.include_router(queryRouter.router)


@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/")
def root():
    return {"message": "Semantic DocQuery API is running"}