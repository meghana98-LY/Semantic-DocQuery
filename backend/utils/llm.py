from __future__ import annotations

import os
import re
from typing import Any

_FALLBACK = "I could not find a reliable answer in the uploaded document."

# Matches bank-statement column header rows, e.g.
#   "Txn Date Value Date Cheque No. Description Branch Code Debit Credit Balance"
_BANK_HEADER_RE = re.compile(
    r'\b(Txn\s*Date|Value\s*Date|Cheque\s*No)\b.*\b(Credit|Debit|Balance)\b',
    re.IGNORECASE,
)


# ─── Encoding-noise patterns ────────────────────────────────────────────────

# CJK + Hangul block — same ranges as pdf_parser
_CJK_NOISE_RE = re.compile(
    r"[\u1100-\u11FF"   # Hangul Jamo
    r"\u2E80-\u2EFF"   # CJK Radicals Supplement
    r"\u2F00-\u2FDF"   # Kangxi Radicals
    r"\u3000-\u303F"   # CJK Symbols and Punctuation
    r"\u3040-\u30FF"   # Hiragana + Katakana
    r"\u3100-\u318F"   # Bopomofo + Hangul Compatibility Jamo
    r"\u3200-\u32FF"   # Enclosed CJK
    r"\u3400-\u4DBF"   # CJK Extension A
    r"\u4E00-\u9FFF"   # CJK Unified Ideographs
    r"\uA960-\uA97F"   # Hangul Jamo Extended-A
    r"\uAC00-\uD7FF"   # Hangul Syllables + Jamo Extended-B
    r"\uF900-\uFAFF"   # CJK Compatibility Ideographs
    r"\uFE30-\uFE4F"   # CJK Compatibility Forms
    r"\U00020000-\U0002A6DF]+"  # CJK Extension B
)

# Greek letters used as ligature substitutes (Θ→ti, Σ→tt, Ω→ff, etc.)
# Using Unicode escapes \u0391-\u03C9 (uppercase + lowercase) for reliable matching
# regardless of source-file encoding.
_GREEK_UPPER_NOISE_RE = re.compile(r"[\u0391-\u03C9]+")

# Unicode ligature characters that PyMuPDF sometimes outputs correctly encoded
# but PDF viewers substitute them as garbled — normalise them back
_LIGATURE_MAP = str.maketrans({
    "\uFB00": "ff",  # ﬀ
    "\uFB01": "fi",  # ﬁ
    "\uFB02": "fl",  # ﬂ
    "\uFB03": "ffi", # ﬃ
    "\uFB04": "ffl", # ﬄ
    "\uFB05": "st",  # ﬅ
    "\uFB06": "st",  # ﬆ
})

# Latin Extended-A/B and IPA Extension chars embedded INSIDE ASCII words.
# These appear when broken PDF fonts substitute ligatures (ti, tt, ft, fl, fi)
# with obscure Latin Extended codepoints like Ɵ (ti), Ʃ (tt), Ō (ft), ƞ (tf).
# Pattern: ASCII letter(s) + Latin-Ext char(s) + ASCII letter(s)
_EMBEDDED_LATIN_EXT_RE = re.compile(r"(?<=[a-zA-Z])[\u0100-\u02FF]+(?=[a-zA-Z])")
# Standalone Latin Extended noise (surrounded by whitespace)
_STANDALONE_LATIN_EXT_RE = re.compile(r"(?:^|(?<=\s))[\u0100-\u02FF]+(?=\s|$)")


def _strip_encoding_noise(text: str) -> str:
    """
    Remove or normalise encoding artifacts that survive OCR / PDF extraction:
    - CJK/Hangul blocks used as font-encoding placeholders
    - Greek range substitutes (Θ for 'ti', Σ for 'tt', etc.)
    - Latin Extended-A/B/IPA chars used as ligature substitutes inside words
    - Unicode ligature characters → ASCII equivalents
    """
    text = text.translate(_LIGATURE_MAP)
    text = _CJK_NOISE_RE.sub(" ", text)
    text = _GREEK_UPPER_NOISE_RE.sub("", text)
    # Strip Latin Extended substitutes embedded within words (e.g. CommunicaƟon → Communication)
    text = _EMBEDDED_LATIN_EXT_RE.sub("", text)
    # Strip standalone Latin Extended noise tokens
    text = _STANDALONE_LATIN_EXT_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


# Public alias for use in other modules
strip_encoding_noise = _strip_encoding_noise


# ─── Runtime chunk cleaner ────────────────────────────────────────────────────

def _clean_chunk_text(text: str) -> str:
    """
    Remove OCR noise tokens from an already-stored chunk (single-line).
    Drops tokens where fewer than 60 % of chars are alphanumeric.
    Also strips CJK and Greek encoding noise before token filtering.
    """
    text = _strip_encoding_noise(text)
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
      - Too short (< 20 chars)
      - > 35 % digit characters (table cells, figure captions)
      - ≥ 5 standalone numbers (table rows like "11 6 9 11 …")
      - Contains no word with a vowel (pure abbreviation / nonsense lines)
      - Too many OCR noise characters
    """
    sent = sent.strip()
    if len(sent) < 20:
        return False
    if sum(c.isdigit() for c in sent) / len(sent) > 0.35:
        return False
    if len(re.findall(r"\b\d+\b", sent)) >= 5:
        return False
    # Must have at least one word with a vowel (not pure symbols/abbreviations)
    words = re.findall(r"\b[a-zA-Z]{2,}\b", sent)
    if not words:
        return False
    # Reject OCR garbage: too many noise characters (!, ~, |, }, \, ' used as symbols, etc.)
    noise_chars = sum(1 for c in sent if c in r"!~|}{\"@#^*_=+<>`'")
    if noise_chars / len(sent) > 0.08:
        return False
    # Reject bank-statement column header rows
    if _BANK_HEADER_RE.search(sent):
        return False
    # Reject mid-sentence fragments (start with lowercase — continuation of a cut chunk)
    if sent[0].islower():
        return False
    return True


# ─── Sentence scorer ─────────────────────────────────────────────────────────

# Stop-words excluded from query overlap so generic words don't dilute the score
_STOP = {
    "give", "get", "show", "tell", "what", "which", "where", "when", "who",
    "how", "the", "this", "that", "these", "those", "about", "from", "with",
    "for", "and", "are", "was", "were", "can", "does", "did", "has", "have",
    "its", "their", "there", "also", "some", "any", "all", "more", "into",
    "summary", "summarize", "summarise", "overview", "content", "contents",
    "document", "page", "pages", "doc", "file", "section", "explain",
    "describe", "detail", "details", "information", "info", "answer",
}


def _score_sentence(sentence: str, q_words: set[str]) -> float:
    """
    Fraction of meaningful query words (≥3 chars, not stop-words) present in
    the sentence. If all query words are stop-words (meta queries like 'give
    summary'), returns a small positive base score so every clean sentence is
    ranked and the best ones are still returned.
    """
    meaningful = q_words - _STOP
    if not meaningful:
        return 0.1  # base score — let similarity_score weighting choose the best chunk
    words = set(w.lower() for w in re.findall(r"\b\w+\b", sentence))
    return len(meaningful & words) / len(meaningful)


# ─── Tabular / structured-data chunk descriptor ─────────────────────────────

def _describe_chunk(text: str) -> str:
    """
    For chunks that are primarily tabular or financial data (bank statements,
    invoices, ledgers, tables) — i.e. no extractable prose sentences —
    produce a plain-English description of what the chunk contains.
    """
    is_bank = bool(re.search(
        r'\b(NEFT|RTGS|IMPS|UPI|Txn|Cheque|Balance|Debit|Credit|IFSC|MB/|IB NEFT)\b',
        text, re.IGNORECASE
    ))
    is_invoice = bool(re.search(
        r'\b(Invoice|Inv\b|Bill|Amount Due|Total|GST|CGST|SGST|Tax)\b',
        text, re.IGNORECASE
    ))
    is_table = bool(re.search(
        r'\b(S\.?No\.?|Sr\.?No\.?|Sl\.?No\.?|Item|Description|Qty|Quantity|Rate|Unit)\b',
        text, re.IGNORECASE
    ))

    parts: list[str] = []

    if is_bank:
        parts.append("This section contains bank transaction records")
        # Date range
        dates = re.findall(
            r'\b\d{1,2}[- ][A-Za-z]{3}[- ]\d{4}\b|\b\d{2}-\d{2}-\d{4}\b', text
        )
        unique_dates = list(dict.fromkeys(dates))
        if len(unique_dates) == 1:
            parts.append(f"dated {unique_dates[0]}")
        elif len(unique_dates) >= 2:
            parts.append(f"from {unique_dates[0]} to {unique_dates[-1]}")
        # Transaction direction
        has_dr = bool(re.search(r'\bDr\b|\bDebit\b', text, re.IGNORECASE))
        has_cr = bool(re.search(r'\bCr\b|\bCredit\b', text, re.IGNORECASE))
        txn_types = re.findall(r'\b(NEFT|RTGS|IMPS|UPI|Cheque)\b', text, re.IGNORECASE)
        n_txn = len(re.findall(
            r'\b(NEFT|RTGS|IMPS|UPI|IB NEFT|MB/)\b', text, re.IGNORECASE
        ))
        if n_txn:
            parts.append(f"with approximately {n_txn} transaction(s)")
        if has_dr and has_cr:
            parts.append("including both debit (Dr) and credit (Cr) entries")
        elif has_dr:
            parts.append("showing debit (money out) entries")
        elif has_cr:
            parts.append("showing credit (money in) entries")
        unique_types = list(dict.fromkeys(t.upper() for t in txn_types))
        if unique_types:
            parts.append(f"via {', '.join(unique_types[:3])}")

    elif is_invoice:
        parts.append("This section contains invoice or billing information")
        gst = re.findall(r'\b(GST|CGST|SGST|IGST)\b', text, re.IGNORECASE)
        if gst:
            parts.append(f"including {', '.join(dict.fromkeys(g.upper() for g in gst))} details")
        amounts = re.findall(r'[\d,]+\.\d{2}', text)
        if amounts:
            parts.append(f"with {len(amounts)} monetary value(s) listed")

    elif is_table:
        parts.append("This section contains a structured data table")
        amounts = re.findall(r'[\d,]+\.\d{2}', text)
        if amounts:
            parts.append(f"with {len(amounts)} numeric entries")

    else:
        # Generic numeric/tabular content
        amounts = re.findall(r'[\d,]+\.\d{2}', text)
        numbers = re.findall(r'\b\d+\b', text)
        if amounts:
            parts.append(f"This section contains structured numerical data with {len(amounts)} value(s)")
        elif numbers:
            parts.append("This section contains structured data with numeric entries")
        else:
            return ""  # nothing useful to say

    return ". ".join(parts) + "."


# ─── Per-chunk relevant summary (shown on source cards) ──────────────────────

def extract_relevant_summary(chunk_text: str, question: str, max_sentences: int = 4) -> str:
    """
    Produce a human-readable summary for a single chunk card.

    For bank / invoice / tabular chunks:
      - Builds a _describe_chunk() plain-English description covering date range,
        transaction count, debit/credit direction, named entities found.
      - Appended with a list of entity names present (e.g. "GOOGLE INDIA DIGITAL SERVICES").

    For prose chunks:
      - Top-scored clean sentences in original order.
    """
    # Strip encoding noise (CJK, Hangul, Greek substitutes, ligatures) before
    # any branch so garbled characters never appear in the card summary.
    chunk_text = _strip_encoding_noise(chunk_text)

    is_bank = bool(re.search(
        r'\b(NEFT|RTGS|IMPS|UPI|Txn\s+Date|Cheque|IB NEFT)\b',
        chunk_text, re.IGNORECASE,
    ))
    is_invoice = bool(re.search(
        r'\b(Invoice|Amount Due|Grand Total|GST|CGST|SGST)\b',
        chunk_text, re.IGNORECASE,
    ))

    if is_bank or is_invoice:
        desc = _describe_chunk(chunk_text)

        # Extract notable entity names (ALL-CAPS multi-word) present in the chunk
        entities = list(dict.fromkeys(
            m.group(0).strip()
            for m in re.finditer(r'\b[A-Z]{2,}(?:\s+[A-Z]{2,})+\b', chunk_text)
        ))
        # Filter out generic bank keywords
        skip = {'NEFT', 'RTGS', 'IMPS', 'IFSC', 'IB NEFT', 'UPI', 'NEFT CR', 'NEFT DR'}
        entities = [e for e in entities if e.upper() not in skip][:4]

        # Date range for the chunk
        dates_in_chunk = list(dict.fromkeys(
            _norm_date(d) for d in _DATE_FIND_RE.findall(chunk_text)
        ))
        date_str = ""
        if len(dates_in_chunk) >= 2:
            date_str = f" covering {dates_in_chunk[0]} to {dates_in_chunk[-1]}"
        elif len(dates_in_chunk) == 1:
            date_str = f" on {dates_in_chunk[0]}"

        parts: list[str] = []
        if desc:
            parts.append(desc.rstrip('.') + date_str + ".")
        if entities:
            parts.append("Entities: " + ", ".join(entities) + ".")

        if parts:
            return " ".join(parts)
        return desc or ""

    # ── Prose chunk ───────────────────────────────────────────────────────────
    q_words = set(w.lower() for w in re.findall(r"\b\w+\b", question) if len(w) >= 3)
    cleaned = _clean_chunk_text(chunk_text)
    clean = [s for s in _split_sentences(cleaned) if _is_clean_sentence(s)]

    if not clean:
        return _describe_chunk(chunk_text)

    ranked = sorted(clean, key=lambda s: _score_sentence(s, q_words), reverse=True)
    top = set(ranked[:max_sentences])
    in_order = [s for s in clean if s in top]
    return " ".join(in_order).strip()


# ─── Intent detection ────────────────────────────────────────────────────────

_INTENT_QUESTION  = re.compile(r"^\s*(what|who|which|where|when|why|how)\b", re.IGNORECASE)
_INTENT_LIST      = re.compile(r"^\s*(list|enumerate|find all|show all|get all|name all)\b", re.IGNORECASE)
_INTENT_RETRIEVE  = re.compile(r"^\s*(give|show|get|fetch|retrieve|display|extract|find|pull)\b", re.IGNORECASE)
_INTENT_SUMMARY   = re.compile(r"^\s*(summar|overview|describe|explain|outline)\b", re.IGNORECASE)

_CONNECTORS = [
    "", "Additionally,", "Furthermore,", "In particular,", "Also,", "Moreover,", "Notably,"
]


def _detect_intent(question: str) -> str:
    if _INTENT_QUESTION.match(question):
        return "question"
    if _INTENT_LIST.match(question):
        return "list"
    if _INTENT_RETRIEVE.match(question):
        return "retrieve"
    if _INTENT_SUMMARY.match(question):
        return "summary"
    return "general"


def _topic_phrase(question: str) -> str:
    """Extract meaningful keywords from the question as a readable topic."""
    words = [w for w in re.findall(r"\b[a-zA-Z]{3,}\b", question)
             if w.lower() not in _STOP]
    return " ".join(words[:4]) if words else ""


def _make_intro(intent: str, topic: str, doc_name: str) -> str:
    doc_label = f" in '{doc_name}'" if doc_name else ""
    t = f' about "{topic}"' if topic else ""
    if intent == "question":
        return f"Based on the document{doc_label}, here is what I found{t}:"
    if intent == "list":
        return f"The document{doc_label} contains the following information{t}:"
    if intent == "retrieve":
        return f"Here is the relevant content{t} from the document{doc_label}:"
    return f"Based on the document{doc_label}, here is the most relevant information{t}:"


# ─── Cross-chunk extractive → generative composer ────────────────────────────

def _build_extractive_summary(question: str, sources: list[dict[str, Any]]) -> str:
    """
    Selects the highest-relevance sentences across all retrieved chunks
    (scored by query-word overlap × cosine similarity) and composes them
    into a fluent, connected response with page citations.

    Fallback hierarchy:
      1. Top-scored clean sentences  →  composed generative paragraph
      2. First clean sentences from best chunk  →  direct passage
      3. Tabular/structured data description
      4. _FALLBACK
    """
    q_words = set(w.lower() for w in re.findall(r"\b\w+\b", question) if len(w) >= 3)
    intent = _detect_intent(question)
    topic  = _topic_phrase(question)

    # Build scored candidates with page & doc metadata
    # (score, sentence, page_number, doc_name)
    candidates: list[tuple[float, str, int, str]] = []
    seen: set[str] = set()

    for src in sources:
        cleaned = _clean_chunk_text(src["snippet"])
        for sent in _split_sentences(cleaned):
            if not _is_clean_sentence(sent):
                continue
            norm = re.sub(r"\s+", " ", sent).lower()
            if norm in seen:
                continue
            seen.add(norm)
            sc = _score_sentence(sent, q_words)
            # Weight score by chunk similarity so top-ranked chunks are preferred
            weighted = sc * (0.4 + src["similarity_score"] * 0.6)
            candidates.append((weighted, sent, src["page_number"], src["document_name"]))

    # ── Fallback: no scored clean sentences ──────────────────────────────────
    if not candidates or max(c[0] for c in candidates) == 0.0:
        for src in sources:
            cleaned = _clean_chunk_text(src["snippet"])
            first_two = [s for s in _split_sentences(cleaned) if _is_clean_sentence(s)][:2]
            if first_two:
                body = " ".join(first_two)
                return body
        # Try structured/tabular description
        descriptions: list[str] = []
        seen_desc: set[str] = set()
        for src in sorted(sources, key=lambda s: s["page_number"]):
            desc = _describe_chunk(src["snippet"])
            if desc and desc not in seen_desc:
                seen_desc.add(desc)
                descriptions.append(f"  • Page {src['page_number']}: {desc}")
        if descriptions:
            return "The document appears to contain structured or tabular data:\n\n" + "\n".join(descriptions)
        return _FALLBACK

    # Sort by score descending, take top 6
    candidates.sort(key=lambda x: x[0], reverse=True)
    top_candidates = candidates[:6]

    # Restore natural reading order (by page, then by position in chunk text)
    top_set: dict[str, tuple[int, str]] = {s: (p, d) for _, s, p, d in top_candidates}

    ordered: list[tuple[int, str, str]] = []  # (page, sentence, doc_name)
    for src in sources:
        cleaned = _clean_chunk_text(src["snippet"])
        for sent in _split_sentences(cleaned):
            if sent in top_set and not any(s == sent for _, s, _ in ordered):
                ordered.append((src["page_number"], sent, src["document_name"]))

    if not ordered:
        return _FALLBACK

    # Determine primary doc name for intro
    primary_doc = ordered[0][2] if ordered else (sources[0]["document_name"] if sources else "")
    intro = _make_intro(intent, topic, primary_doc)

    # Compose generative paragraph with connectors (no inline page citations)
    lines: list[str] = [intro, ""]
    for i, (page, sent, _) in enumerate(ordered):
        connector = _CONNECTORS[min(i, len(_CONNECTORS) - 1)]
        if connector:
            lines.append(f"{connector} {sent}")
        else:
            lines.append(sent)

    return "\n".join(lines).strip()


# ─── Factual value extractor (bank / invoice / tabular) ─────────────────────

_DATE_FIND_RE = re.compile(
    r'\b(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}'
    r'|\d{4}[-/]\d{2}[-/]\d{2}'
    r'|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})\b',
    re.IGNORECASE,
)
# Partial date — day + month name, no year required (e.g. "13 April", "13 Apr")
_PARTIAL_DATE_RE = re.compile(
    r'\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|'
    r'October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b',
    re.IGNORECASE,
)
_MONTH_MAP: dict[str, int] = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
    'january': 1, 'february': 2, 'march': 3, 'april': 4,
    'june': 6, 'july': 7, 'august': 8, 'september': 9,
    'october': 10, 'november': 11, 'december': 12,
}
_AMOUNT_FIND_RE = re.compile(r'[\d,]+\.\d{2}')


def _norm_date(d: str) -> str:
    """Normalise any detected date string to DD-MM-YYYY for comparison."""
    m = re.match(r'(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})$', d.strip())
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        if len(yyyy) == 2:
            yyyy = '20' + yyyy
        return f"{int(dd):02d}-{int(mm):02d}-{yyyy}"
    m = re.match(r'(\d{4})[-/](\d{2})[-/](\d{2})$', d.strip())
    if m:
        yyyy, mm, dd = m.group(1), m.group(2), m.group(3)
        return f"{dd}-{mm}-{yyyy}"
    return d


def _row_date_day_month(row: str) -> list[tuple[int, int]]:
    """
    Return all (day, month_num) pairs found in a row regardless of year.
    Works for normalised dates like "13-04-2023" and "13 Apr 2023".
    """
    results: list[tuple[int, int]] = []
    for d in _DATE_FIND_RE.findall(row):
        nd = _norm_date(d)           # "DD-MM-YYYY"
        parts = nd.split('-')
        if len(parts) == 3:
            try:
                results.append((int(parts[0]), int(parts[1])))
            except ValueError:
                pass
    return results


def _extract_entity(question: str) -> str:
    """
    Extract a company / entity name from the question.
    Looks for ALL-CAPS multi-word sequences first (GOOGLE INDIA DIGITAL SERVICES),
    then falls back to a noun phrase after 'from' or 'by'.
    """
    # ALL-CAPS multi-word (2+ consecutive all-caps tokens)
    m = re.search(r'\b([A-Z]{2,}(?:\s+[A-Z]{2,})+)\b', question)
    if m:
        return m.group(1).strip()
    # After "from / by / for" keyword — title-case or mixed
    m = re.search(
        r'\b(?:from|by|for)\s+([A-Z][A-Za-z0-9]+(?: [A-Z][A-Za-z0-9]+)+)\b',
        question,
    )
    if m:
        return m.group(1).strip()
    return ""


def _try_extract_factual_answer(question: str, sources: list[dict[str, Any]]) -> str:
    """
    For bank-statement, invoice, and tabular documents, tries to extract a
    specific fact (balance on a date, total amount, transaction count, credit
    from a named entity, etc.) and compose a natural-language sentence.

    Returns a composed answer string if successful, or "" to fall through to
    the normal extractive summariser.
    """
    q_lower = question.lower()
    wants_balance   = bool(re.search(r'\bbalance\b', q_lower))
    wants_debit     = bool(re.search(r'\b(debit|dr\.?|withdrawal|spent)\b', q_lower))
    wants_credit    = bool(re.search(r'\b(credit|cr\.?|deposit|received|inward|credited)\b', q_lower))
    wants_total     = bool(re.search(r'\b(total|grand total|net amount|sum)\b', q_lower))
    wants_txn_count = bool(re.search(r'\b(how many|count|number of)\b', q_lower))

    # ── Date matching ─────────────────────────────────────────────────────────
    # Full dates (DD-MM-YYYY etc.)
    q_dates_full = [_norm_date(d) for d in _DATE_FIND_RE.findall(question)]

    # Partial date (day + month name, no year) — e.g. "13 April"
    partial_day: int | None = None
    partial_month: int | None = None
    partial_label: str = ""
    pm = _PARTIAL_DATE_RE.search(question)
    if pm and not q_dates_full:
        partial_day = int(pm.group(1))
        partial_month = _MONTH_MAP.get(pm.group(2).lower()[:3])
        if partial_month is None:
            partial_month = _MONTH_MAP.get(pm.group(2).lower())
        partial_label = pm.group(0).strip()  # e.g. "13 April"

    # ── Entity name ───────────────────────────────────────────────────────────
    entity = _extract_entity(question)
    entity_keywords = [w.lower() for w in entity.split() if len(w) >= 3] if entity else []

    def _row_matches_entity(row: str) -> bool:
        if not entity_keywords:
            return True   # no entity filter
        row_l = row.lower()
        return all(kw in row_l for kw in entity_keywords[:3])

    # ── Scan each chunk ───────────────────────────────────────────────────────
    not_found_msgs: list[str] = []

    for src in sources:
        text = src["snippet"]
        doc  = src["document_name"]
        page = src["page_number"]

        is_bank = bool(re.search(
            r'\b(NEFT|RTGS|IMPS|UPI|Txn|Cheque|Balance|Debit|Credit|IFSC|MB/|IB NEFT)\b',
            text, re.IGNORECASE,
        ))
        is_invoice = bool(re.search(
            r'\b(Invoice|Inv\b|Amount Due|Grand Total|GST|CGST|SGST)\b',
            text, re.IGNORECASE,
        ))

        # ── Bank statement ────────────────────────────────────────────────────
        if is_bank:
            rows = [r.strip() for r in re.split(r'\n+', text) if r.strip()]

            # Available dates in this chunk (for "not found" messages)
            chunk_dm: list[tuple[int, int]] = []
            for r in rows:
                chunk_dm.extend(_row_date_day_month(r))
            chunk_dm = list(dict.fromkeys(chunk_dm))

            chunk_date_labels = []
            for d_full in _DATE_FIND_RE.findall('\n'.join(rows)):
                nd = _norm_date(d_full)
                if nd not in chunk_date_labels:
                    chunk_date_labels.append(nd)

            # ── Full-date match ───────────────────────────────────────────────
            if q_dates_full:
                target = q_dates_full[0]
                t_parts = target.split('-')
                t_day, t_month = int(t_parts[0]), int(t_parts[1])

                matched = [
                    r for r in rows
                    if (t_day, t_month) in _row_date_day_month(r)
                    and _row_matches_entity(r)
                ]

                if matched:
                    return _compose_bank_answer(
                        matched, target, doc, page,
                        wants_credit, wants_debit, wants_balance, entity,
                    )
                elif chunk_dm:
                    rng_labels = _chunk_date_range(chunk_date_labels)
                    not_found_msgs.append(
                        f"Page {page} covers {rng_labels}"
                    )

            # ── Partial-date match (day + month, any year) ────────────────────
            elif partial_day is not None and partial_month is not None:
                matched = [
                    r for r in rows
                    if (partial_day, partial_month) in _row_date_day_month(r)
                    and _row_matches_entity(r)
                ]

                if matched:
                    return _compose_bank_answer(
                        matched, partial_label, doc, page,
                        wants_credit, wants_debit, wants_balance, entity,
                    )
                elif chunk_dm:
                    rng_labels = _chunk_date_range(chunk_date_labels)
                    not_found_msgs.append(
                        f"Page {page} covers {rng_labels}"
                    )

            # ── Generic stats (no date in question) ───────────────────────────
            else:
                if wants_balance:
                    all_amounts = _AMOUNT_FIND_RE.findall(text)
                    if all_amounts and chunk_date_labels:
                        rng = _chunk_date_range(chunk_date_labels)
                        return (
                            f"According to '{doc}' (page {page}), the records covering "
                            f"{rng} show {len(all_amounts)} monetary entries. "
                            f"The last recorded balance is \u20b9{all_amounts[-1]}."
                        )
                if wants_txn_count:
                    n = len(re.findall(r'\b(NEFT|RTGS|IMPS|UPI|Cheque)\b', text, re.IGNORECASE))
                    if n:
                        return (
                            f"According to '{doc}' (page {page}), approximately {n} "
                            f"transaction(s) are listed in the retrieved section."
                        )

        # ── Invoice ───────────────────────────────────────────────────────────
        if is_invoice and wants_total:
            m = re.search(r'\b(Grand\s+)?Total\b[^\d\n]*([\d,]+\.\d{2})', text, re.IGNORECASE)
            if m:
                return (
                    f"According to '{doc}' (page {page}), "
                    f"the total amount is \u20b9{m.group(2)}."
                )

    # ── Nothing found — report date range if data is present ─────────────────
    date_ref = (partial_label or (q_dates_full[0] if q_dates_full else ""))
    entity_label = f" from {entity}" if entity else ""

    if not_found_msgs and date_ref:
        pages_info = "; ".join(not_found_msgs)
        return (
            f"No transaction{entity_label} was found on {date_ref} "
            f"in the retrieved sections of the document. "
            f"({pages_info})"
        )

    return ""   # fall through to generative extractive summary


# ── Bank answer composer ──────────────────────────────────────────────────────

def _chunk_date_range(date_labels: list[str]) -> str:
    if not date_labels:
        return "unknown dates"
    if len(date_labels) == 1:
        return date_labels[0]
    return f"{date_labels[0]} to {date_labels[-1]}"


def _compose_bank_answer(
    matched_rows: list[str],
    date_label: str,
    doc: str,
    page: int,
    wants_credit: bool,
    wants_debit: bool,
    wants_balance: bool,
    entity: str,
) -> str:
    entity_label = f" from {entity}" if entity else ""
    lines: list[str] = []

    for row in matched_rows[:5]:   # cap at 5 matching rows
        amounts = _AMOUNT_FIND_RE.findall(row)
        if not amounts:
            continue
        # Typical bank row: ... Debit Credit Balance (3 last amounts)
        if len(amounts) >= 3:
            debit_amt   = amounts[-3]
            credit_amt  = amounts[-2]
            balance_amt = amounts[-1]
            # Determine direction: Cr in description → credit, Dr → debit
            is_credit_row = bool(re.search(r'\bCr\b|NEFT\s+Cr', row, re.IGNORECASE))
            is_debit_row  = bool(re.search(r'\bDr\b|IB NEFT Dr', row, re.IGNORECASE))

            if wants_credit and is_credit_row:
                lines.append(
                    f"A credit{entity_label} of \u20b9{credit_amt} was received on {date_label} "
                    f"(balance after: \u20b9{balance_amt})."
                )
            elif wants_debit and is_debit_row:
                lines.append(
                    f"A debit{entity_label} of \u20b9{debit_amt} was made on {date_label} "
                    f"(balance after: \u20b9{balance_amt})."
                )
            elif wants_balance:
                lines.append(
                    f"Balance on {date_label}{entity_label}: \u20b9{balance_amt}."
                )
            else:
                # Return all three columns
                direction = ""
                if is_credit_row:
                    direction = f"Credit: \u20b9{credit_amt}. "
                elif is_debit_row:
                    direction = f"Debit: \u20b9{debit_amt}. "
                lines.append(
                    f"On {date_label}{entity_label}: {direction}"
                    f"Balance: \u20b9{balance_amt}."
                )
        elif len(amounts) == 1:
            lines.append(
                f"On {date_label}{entity_label}: amount \u20b9{amounts[0]}."
            )

    if lines:
        prefix = f"According to '{doc}' (page {page}):\n"
        return prefix + "\n".join(f"  • {l}" for l in lines)

    # Rows matched but no amounts parseable
    desc = " ".join(matched_rows[0].split()[:15])
    return (
        f"According to '{doc}' (page {page}), the record on {date_label}{entity_label} "
        f'reads: "{desc}".'
    )


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
    Primary entry point called by queryRouter for normal (non-meta) queries.

    Attempts in order:
      1. Direct factual extraction — for bank/invoice queries with dates or
         amounts, returns a precise composed sentence (e.g. "the balance on
         12-04-2023 was ₹2,18,480.00").
      2. Generative extractive summary — scores sentences against the query,
         composes a fluent paragraph with connectors and page citations.
      3. _FALLBACK message.
    """
    if not sources:
        return _FALLBACK

    # 1 ─ Try to extract a specific fact from tabular/financial chunks
    factual = _try_extract_factual_answer(question, sources)
    if factual:
        return factual

    # 2 ─ Generative extractive summary
    return _build_extractive_summary(question, sources)


def build_summary_response(sources: list[dict[str, Any]], question: str = "") -> str:
    """
    Called for document-level meta queries (summarize, overview, page contents).
    Extracts and composes a response locally from the retrieved chunks.
    """
    if not sources:
        return _FALLBACK

    doc_names = sorted({s["document_name"] for s in sources})
    doc_label = "', '".join(doc_names)

    # Determine if the query has a specific focus beyond just "summarize"
    _generic_meta = re.compile(
        r"^\s*(summar(y|ize|ise)|overview|describe|explain|\s*contents?|what\s+is\s+(this|it))",
        re.IGNORECASE,
    )
    has_specific_query = bool(question.strip()) and not _generic_meta.match(question.strip())

    # ── Local extraction ──────────────────────────────────────────────────────
    seen_norm: set[str] = set()
    prose_points: list[tuple[int, str]] = []
    tabular_points: list[tuple[int, str]] = []

    for src in sorted(sources, key=lambda s: (s["document_name"], s["page_number"])):
        cleaned = _clean_chunk_text(src["snippet"])
        chunk_sents = [s for s in _split_sentences(cleaned) if _is_clean_sentence(s)]
        if not chunk_sents:
            desc = _describe_chunk(src["snippet"])
            if desc:
                key = f"{src['page_number']}:{desc}"
                if key not in seen_norm:
                    seen_norm.add(key)
                    tabular_points.append((src["page_number"], desc))
            continue
        for sent in chunk_sents:
            norm = re.sub(r"\s+", " ", sent).lower()
            if norm in seen_norm:
                continue
            seen_norm.add(norm)
            prose_points.append((src["page_number"], sent))

    # For specific queries, score sentences by relevance; for generic overview, preserve order
    if has_specific_query and prose_points:
        q_words = set(w.lower() for w in re.findall(r"\b\w+\b", question) if len(w) >= 3)
        scored = sorted(prose_points, key=lambda ps: _score_sentence(ps[1], q_words), reverse=True)
        prose_points = scored[:8]
        # Restore page order for readability
        prose_points = sorted(prose_points, key=lambda ps: ps[0])

    lines: list[str] = []

    if prose_points:
        all_sents: list[str] = []
        page_map: dict[int, list[str]] = {}
        for page, sent in prose_points[:12]:
            page_map.setdefault(page, []).append(sent)
        for page in sorted(page_map.keys()):
            all_sents.extend(page_map[page][:2])
        lines.append(" ".join(all_sents))
        if tabular_points:
            lines.append("")
            lines.append("The document also contains structured or tabular data.")
    elif tabular_points:
        descs = " ".join(desc for _, desc in tabular_points)
        lines.append(descs)
    else:
        return _FALLBACK

    return "\n".join(lines).strip()


