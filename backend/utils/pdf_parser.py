import os
import re
import fitz  # PyMuPDF
import pytesseract
from pdf2image import convert_from_path
from dotenv import load_dotenv

load_dotenv()

# Read OCR-related paths from .env
TESSERACT_CMD = os.getenv("TESSERACT_CMD")
POPPLER_PATH = os.getenv("POPPLER_PATH")

# Set Tesseract path if provided
if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD


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
    try:
        doc = fitz.open(file_path)
        pages = []

        # Convert all pages to images once (for OCR fallback)
        images = convert_from_path(file_path, poppler_path=POPPLER_PATH)

        for i, page in enumerate(doc):
            extracted_text = page.get_text("text").strip()

            # If extracted text is too short, use OCR
            if len(extracted_text) < 30:
                try:
                    raw_ocr = pytesseract.image_to_string(images[i]).strip()
                    final_text = _clean_ocr_text(raw_ocr)
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