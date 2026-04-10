from __future__ import annotations

import re
from typing import Any

_FALLBACK = "I could not find a reliable answer in the uploaded document."


# ─── Runtime chunk cleaner ────────────────────────────────────────────────────

def _clean_chunk_text(text: str) -> str:
    """
    Remove OCR noise tokens from an already-stored chunk (single-line).
    Drops tokens where fewer than 60 % of chars are alphanumeric.
    Matches the same logic used in pdf_parser._clean_ocr_text so that
    chunks stored before the ingestion fix also get cleaned at query time.
    """
    clean_tokens = []
    for tok in text.split():
        alnum = sum(c.isalnum() for c in tok)
        if alnum == 0:
            continue
        if len(tok) <= 2:
            clean_tokens.append(tok)
            continue
        if alnum / len(tok) >= 0.60:
            clean_tokens.append(tok)
    return re.sub(r"\s+", " ", " ".join(clean_tokens)).strip()


# ─── Sentence splitter ────────────────────────────────────────────────────────

def _split_sentences(text: str) -> list[str]:
    """Split text on sentence-ending punctuation."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


# ─── Quality filter ───────────────────────────────────────────────────────────

def _is_clean_sentence(sent: str) -> bool:
    """
    Return True only for readable prose sentences. Rejects:
      - Too short (< 40 chars)
      - Starts lower-case (OCR fragment / mid-sentence break)
      - > 35 % digit characters (table cells, figure captions)
      - ≥ 4 standalone numbers (table rows like "11 6 9 11 …")
      - Ends with a colon (section headers like "ils are as below:")
      - Contains no vowel words (pure abbreviation / nonsense lines)
    """
    sent = sent.strip()
    if len(sent) < 30:
        return False
    if not re.match(r"^[A-Z\u00C0-\u024F]", sent):
        return False
    if sum(c.isdigit() for c in sent) / len(sent) > 0.35:
        return False
    if len(re.findall(r"\b\d+\b", sent)) >= 4:
        return False
    if sent.rstrip().endswith(":"):
        return False
    # Must have at least one word with a vowel (not pure symbols/abbreviations)
    words = re.findall(r"\b[a-zA-Z]{3,}\b", sent)
    if not words:
        return False
    # Reject OCR garbage: too many noise characters (!, ~, |, }, \, ' used as symbols, etc.)
    noise_chars = sum(1 for c in sent if c in r"!~|}{\"@#^*_=+<>`'")
    if noise_chars / len(sent) > 0.08:
        return False
    return True


# ─── Sentence scorer ─────────────────────────────────────────────────────────

def _score_sentence(sentence: str, q_words: set[str]) -> float:
    """Fraction of query words (≥3 chars) that appear in the sentence."""
    if not q_words:
        return 0.0
    words = set(w.lower() for w in re.findall(r"\b\w+\b", sentence))
    return len(q_words & words) / len(q_words)


# ─── Per-chunk relevant summary (shown on source cards) ──────────────────────

def extract_relevant_summary(chunk_text: str, question: str, max_sentences: int = 3) -> str:
    """
    Pick the top-scoring clean prose sentences from a single chunk.
    Returns them in their original document order.
    Returns an empty string if no clean sentences are found (never dumps raw OCR).
    """
    q_words = set(w.lower() for w in re.findall(r"\b\w+\b", question) if len(w) >= 3)
    cleaned = _clean_chunk_text(chunk_text)
    clean = [s for s in _split_sentences(cleaned) if _is_clean_sentence(s)]

    if not clean:
        return ""  # never fall back to raw OCR text

    ranked = sorted(clean, key=lambda s: _score_sentence(s, q_words), reverse=True)
    top = set(ranked[:max_sentences])
    in_order = [s for s in clean if s in top]
    return " ".join(in_order).strip()


# ─── Cross-chunk extractive summariser ───────────────────────────────────────

def _build_extractive_summary(question: str, sources: list[dict[str, Any]]) -> str:
    """
    Reads every retrieved chunk, scores each clean sentence against the query
    using word-overlap weighted by the chunk's cosine similarity, picks the
    top 6 sentences (de-duplicated), restores natural reading order, and
    formats them into a readable paragraph prefixed with a context header.

    Fallback hierarchy:
      1. Top-scored clean sentences (main path)
      2. First two clean sentences from the best-ranked chunk (semantically
         related but uses different vocabulary than the query)
      3. _FALLBACK message (nothing clean at all)
    """
    q_words = set(w.lower() for w in re.findall(r"\b\w+\b", question) if len(w) >= 3)

    candidates: list[tuple[float, str]] = []
    seen: set[str] = set()

    for src in sources:
        cleaned_snippet = _clean_chunk_text(src["snippet"])
        for sent in _split_sentences(cleaned_snippet):
            if not _is_clean_sentence(sent):
                continue
            norm = re.sub(r"\s+", " ", sent).lower()
            if norm in seen:
                continue
            seen.add(norm)
            sc = _score_sentence(sent, q_words)
            # Weight so higher-similarity chunks contribute more
            weighted = sc * (0.4 + src["similarity_score"] * 0.6)
            candidates.append((weighted, sent))

    # ── Fallback: no clean sentences scored > 0 ──────────────────────────────
    if not candidates or candidates[0][0] == 0.0:
        for src in sources:
            cleaned_snippet = _clean_chunk_text(src["snippet"])
            first_two = [
                s for s in _split_sentences(cleaned_snippet)
                if _is_clean_sentence(s)
            ][:2]
            if first_two:
                body = " ".join(first_two)
                return (
                    f"The document contains the following content related to your query:\n\n"
                    f"{body}"
                )
        return _FALLBACK

    candidates.sort(key=lambda x: x[0], reverse=True)
    top_set = {s for _, s in candidates[:6]}

    # Restore original document order for natural reading
    ordered: list[str] = []
    for src in sources:
        cleaned_snippet = _clean_chunk_text(src["snippet"])
        for sent in _split_sentences(cleaned_snippet):
            if sent in top_set and sent not in ordered:
                ordered.append(sent)

    body = " ".join(ordered).strip()
    return f"Based on the uploaded document:\n\n{body}"


# ─── Public API ──────────────────────────────────────────────────────────────

def generate_answer(question: str, context: str) -> str:
    """Backward-compatibility wrapper."""
    if not context or not context.strip():
        return _FALLBACK
    fake = {"snippet": context, "similarity_score": 1.0,
            "document_name": "", "page_number": 0}
    return _build_extractive_summary(question, [fake])


def build_rag_response(question: str, sources: list[dict[str, Any]]) -> str:
    """
    Primary entry point called by queryRouter.
    Returns a clean, readable multi-sentence paragraph summarising the
    retrieved document content in relation to the user's question.
    No flan-t5 — purely extractive so output is always grounded and grammatical.
    """
    if not sources:
        return _FALLBACK
    return _build_extractive_summary(question, sources)


