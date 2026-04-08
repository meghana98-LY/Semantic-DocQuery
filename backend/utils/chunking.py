def chunk_text(text: str, chunk_size: int = 500, overlap: int = 100):
    """
    Split text into overlapping chunks for semantic search.

    Args:
        text (str): Full page text
        chunk_size (int): Number of characters per chunk
        overlap (int): Number of overlapping characters

    Returns:
        List[str]: List of cleaned text chunks
    """
    if not text or not text.strip():
        return []

    text = " ".join(text.split())  # normalize whitespace
    chunks = []
    start = 0
    text_length = len(text)

    while start < text_length:
        end = min(start + chunk_size, text_length)
        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end == text_length:
            break

        start += chunk_size - overlap

    return chunks