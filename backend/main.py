from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import Base, engine

from routers import authRouter, uploadRouter, queryRouter, chatRouter

# Create all tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Semantic Document Query API")

# CORS — update allow_origins with your production frontend URL when deploying
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(authRouter.router)
app.include_router(chatRouter.router)
app.include_router(uploadRouter.router)
app.include_router(queryRouter.router)


@app.get("/")
def root():
    return {"message": "Semantic DocQuery API is running"}