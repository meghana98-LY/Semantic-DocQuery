import numpy as np

# Lazy-loaded — avoids blocking uvicorn startup
_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L12-v2")
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


def get_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings for a list of texts in batch.

    Returns:
        List[List[float]]: List of normalized embedding vectors
    """
    if not texts:
        return []

    # Filter out empty texts
    valid_texts = []
    indices = []
    for i, text in enumerate(texts):
        if text and text.strip():
            valid_texts.append(text)
            indices.append(i)

    if not valid_texts:
        return [[] for _ in texts]

    embeddings = _get_model().encode(valid_texts)

    # Normalize vectors
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1  # Avoid division by zero
    normalized_embeddings = embeddings / norms

    # Reconstruct the full list with empty embeddings for invalid texts
    result = [[] for _ in texts]
    for idx, emb in zip(indices, normalized_embeddings):
        result[idx] = emb.tolist()

    return result