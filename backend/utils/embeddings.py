from sentence_transformers import SentenceTransformer
import numpy as np

# Lazy-loaded — avoids blocking uvicorn startup
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def get_embedding(text: str) -> list[float]:
    """
    Generate embedding for a given text.

    Returns:
        List[float]: Normalized embedding vector
    """
    if not text or not text.strip():
        return []

    embedding = _get_model().encode(text)

    # Normalize vector (important for cosine similarity)
    norm = np.linalg.norm(embedding)
    if norm == 0:
        return embedding.tolist()

    normalized_embedding = embedding / norm
    return normalized_embedding.tolist()