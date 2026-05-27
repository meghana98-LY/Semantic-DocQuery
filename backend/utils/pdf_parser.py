import os
import re
from dotenv import load_dotenv

load_dotenv()

# Read OCR-related paths from .env
TESSERACT_CMD = os.getenv("TESSERACT_CMD")
POPPLER_PATH = os.getenv("POPPLER_PATH")


# ─── OCR noise cleaner ────────────────────────────────────────────────────────


# ─── OCR noise cleaner ────────────────────────────────────────────────────────

def _clean_ocr_text(text: str) -> str:
    """
    Token-level OCR noise removal applied immediately after pytesseract.
    Drops tokens where fewer than 60 % of characters are alphanumeric —
    catches garbage like `t'.16cA""`, `H'c!l-~`, `}-\\~`, `7L__` while
    keeping real words, numbers, and common abbreviations.
    """
    clean_tokens = []
    for tok in text.split():
        alnum = sum(c.isalnum() for c in tok)
        if alnum == 0:
            continue                          # pure-punctuation token
        if len(tok) <= 2:
            clean_tokens.append(tok)          # keep short tokens as-is
            continue
        if alnum / len(tok) >= 0.60:
            clean_tokens.append(tok)
    return re.sub(r"\s+", " ", " ".join(clean_tokens)).strip()


# CJK + Hangul Unicode ranges used as broken-font encoding substitutes
_CJK_RE = re.compile(
    r"[\u1100-\u11FF"        # Hangul Jamo
    r"\u2E80-\u2EFF"        # CJK Radicals Supplement
    r"\u2F00-\u2FDF"        # Kangxi Radicals
    r"\u3000-\u303F"        # CJK Symbols and Punctuation
    r"\u3040-\u309F"        # Hiragana
    r"\u30A0-\u30FF"        # Katakana
    r"\u3100-\u318F"        # Bopomofo + Hangul Compatibility Jamo
    r"\u3200-\u32FF"        # Enclosed CJK
    r"\u3400-\u4DBF"        # CJK Extension A
    r"\u4E00-\u9FFF"        # CJK Unified Ideographs
    r"\uA960-\uA97F"        # Hangul Jamo Extended-A
    r"\uAC00-\uD7FF"        # Hangul Syllables + Jamo Extended-B
    r"\uF900-\uFAFF"        # CJK Compatibility Ideographs
    r"\uFE30-\uFE4F"        # CJK Compatibility Forms
    r"\U00020000-\U0002A6DF"  # CJK Extension B
    r"]"
)

_CJK_RATIO_THRESHOLD = 0.05   # >5 % CJK chars → treat page as garbled, force OCR


def _has_garbled_cjk(text: str) -> bool:
    """
    Return True when the extracted text contains an unusually high proportion
    of CJK characters, which indicates broken font encoding rather than real
    CJK content (since the target documents are in English/Hindi).
    """
    if not text:
        return False
    cjk_count = len(_CJK_RE.findall(text))
    return cjk_count / len(text) > _CJK_RATIO_THRESHOLD


# Greek letters used as ligature/encoding substitutes in broken PDFs.
# e.g. Σ (U+03A3) for 'tt', Θ (U+0398) for 'ti', Ω (U+03A9) for 'ff', etc.
# Using Unicode range escapes for reliable matching regardless of file encoding.
_GREEK_UPPER_RE = re.compile(r"[\u0391-\u03C9]")

_GREEK_RATIO_THRESHOLD = 0.01   # >1 % of alpha chars are Greek → garbled


def _has_garbled_greek(text: str) -> bool:
    """
    Return True when Greek letters appear at a suspicious rate inside
    predominantly ASCII text — broken font mapping (Σ for tt, Θ for ti, etc.).
    """
    if not text:
        return False
    greek_count = len(_GREEK_UPPER_RE.findall(text))
    if greek_count == 0:
        return False
    alpha_count = sum(1 for c in text if c.isalpha())
    if alpha_count == 0:
        return False
    return greek_count / alpha_count > _GREEK_RATIO_THRESHOLD


# Latin Extended-A/B and IPA chars embedded inside ASCII words — ligature substitutes.
_LATIN_EXT_IN_WORD_RE = re.compile(r"[a-zA-Z][\u0100-\u02FF][a-zA-Z]")
_LATIN_EXT_RATIO_THRESHOLD = 0.01  # >1 % of alpha chars in Ext range → garbled


def _has_garbled_latin_ext(text: str) -> bool:
    """
    Return True when Latin Extended-A/B/IPA characters appear embedded within
    ASCII words — a strong signal that broken PDF font mapping is substituting
    ligature glyphs (ti, tt, ft, fl, fi) with obscure Latin Extended codepoints
    (e.g. Ɵ for 'ti', Ʃ for 'tt', Ō for 'ft').
    """
    if not _LATIN_EXT_IN_WORD_RE.search(text):
        return False
    ext_count = sum(1 for c in text if '\u0100' <= c <= '\u02FF')
    alpha_count = sum(1 for c in text if c.isalpha())
    if alpha_count == 0:
        return False
    return ext_count / alpha_count > _LATIN_EXT_RATIO_THRESHOLD


def extract_text_from_pdf(file_path: str) -> str:
    """
    Extract full text from PDF using page-wise extraction + OCR fallback.
    """
    pages = extract_text_by_page(file_path)
    return "\n".join([page["text"] for page in pages])


def extract_text_by_page(file_path: str):
    """
    Extract text page by page.
    Uses normal PDF extraction first.
    Falls back to OCR if page has little/no readable text.

    Returns:
    [
        {"page_number": 1, "text": "..."},
        {"page_number": 2, "text": "..."},
        ...
    ]
    """
    import fitz  # PyMuPDF
    import pytesseract
    from pdf2image import convert_from_path

    # Set Tesseract path if provided
    if TESSERACT_CMD:
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

    try:
        doc = fitz.open(file_path)
        pages = []

        # Debug: log poppler path and presence of expected executables
        try:
            print(f"DEBUG: POPPLER_PATH={POPPLER_PATH}")
            if POPPLER_PATH:
                pdfinfo_path = os.path.join(POPPLER_PATH, "pdfinfo.exe")
                pdftoppm_path = os.path.join(POPPLER_PATH, "pdftoppm.exe")
                print(f"DEBUG: pdfinfo exists: {os.path.exists(pdfinfo_path)} -> {pdfinfo_path}")
                print(f"DEBUG: pdftoppm exists: {os.path.exists(pdftoppm_path)} -> {pdftoppm_path}")
        except Exception:
            pass

        # Convert all pages to images once (for OCR fallback)
        images = convert_from_path(file_path, poppler_path=POPPLER_PATH)

        for i, page in enumerate(doc):
            extracted_text = page.get_text("text").strip()

            # Force OCR when:
            #   1. Extracted text is too short (sparse/image page), OR
            #   2. Text contains broken-font CJK/Hangul garbage, OR
            #   3. Text contains Greek range substitutes (Σ for tt, Θ for ti, etc.), OR
            #   4. Text contains Latin Extended-B ligature substitutes (Ɵ for ti, Ʃ for tt, etc.)
            needs_ocr = (
                len(extracted_text) < 30
                or _has_garbled_cjk(extracted_text)
                or _has_garbled_greek(extracted_text)
                or _has_garbled_latin_ext(extracted_text)
            )

            if needs_ocr:
                try:
                    raw_ocr = pytesseract.image_to_string(images[i]).strip()
                    ocr_text = _clean_ocr_text(raw_ocr)
                    # Prefer OCR result only if it produced more usable text;
                    # fall back to the (garbled) extraction if OCR also fails.
                    final_text = ocr_text if ocr_text else extracted_text
                except Exception:
                    final_text = extracted_text
            else:
                final_text = extracted_text

            if final_text:
                pages.append({
                    "page_number": i + 1,
                    "text": final_text
                })

        return pages

    except Exception as e:
        raise Exception(f"Error extracting text by page: {str(e)}")