from sentence_transformers import SentenceTransformer
import numpy as np

# Load model once (global)
model = SentenceTransformer("all-MiniLM-L6-v2")


def get_embedding(text: str) -> list[float]:
    """
    Generate embedding for a given text.

    Returns:
        List[float]: Normalized embedding vector
    """
    if not text or not text.strip():
        return []

    embedding = model.encode(text)

    # Normalize vector (important for cosine similarity)
    norm = np.linalg.norm(embedding)
    if norm == 0:
        return embedding.tolist()

    normalized_embedding = embedding / norm
    return normalized_embedding.tolist()