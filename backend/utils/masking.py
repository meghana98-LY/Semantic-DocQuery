"""
Sensitive data masking utility.

Masks PII / credentials in text before it is stored in the database or
returned to the user.  Applied at two points:
  1. Ingestion time  — chunk_text stored in DocumentChunk is sanitised.
  2. Query-response time — LLM answer and source snippets are sanitised.

Patterns covered
----------------
- Passwords      : "password: secret123", "pwd: abc", "pin: 1234"
- Emails         : user@domain.tld
- UPI IDs        : user@upi, user@okicici, user@oksbi, etc.
- UPI / ATM PINs : "upi pin: 1234", "atm pin: ..."
- Phone numbers  : 10-digit Indian mobile numbers (+91 prefix variants)
- PAN numbers    : AAAAA9999A
- Aadhaar        : 12-digit groups with optional spaces/dashes
- Credit/Debit cards : 16-digit grouped numbers
- Bank account numbers : explicit labels ("account no: 12345...")
- IFSC codes     : AAAA0123456
- CVV            : "cvv: 123"
- OTP            : "otp: 123456"
- Date of birth  : "dob: dd/mm/yyyy" or labeled variants
"""

from __future__ import annotations

import re

# ─────────────────────────────────────────────────────────────────────────────
# Individual patterns  (label, compiled_regex, replacement)
# ─────────────────────────────────────────────────────────────────────────────

_RULES: list[tuple[str, re.Pattern, str]] = []


def _add(label: str, pattern: str, replacement: str, flags: int = re.IGNORECASE) -> None:
    _RULES.append((label, re.compile(pattern, flags), replacement))


# --- Passwords ---
_add(
    "password",
    r"((?:password|passwd|pwd|passcode|pass)\s*[:=]\s*)\S+",
    r"\1[REDACTED]",
)

# --- PIN / OTP ---
_add(
    "pin",
    r"((?:upi\s*pin|atm\s*pin|mpin|m-pin|pin)\s*[:=]\s*)\d{4,8}",
    r"\1[REDACTED]",
)
_add(
    "otp",
    r"(otp\s*[:=]\s*)\d{4,8}",
    r"\1[REDACTED]",
)
_add(
    "cvv",
    r"(cvv\s*[:=]\s*)\d{3,4}",
    r"\1[REDACTED]",
)

# --- UPI IDs (must come before generic email so @upi handles are caught here) ---
_add(
    "upi_id",
    r"\b[\w.\-+]+@(?:upi|okicici|oksbi|okhdfcbank|okaxis|ybl|ibl|axl|"
    r"paytm|phonepe|gpay|apl|barodampay|cnrb|sbi|aubank|indus|rbl|"
    r"kotak|hsbc|citi|icici|hdfc|axis|paytmbank)\b",
    "[UPI-ID REDACTED]",
)

# --- Email addresses ---
_add(
    "email",
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
    "[EMAIL REDACTED]",
)

# --- PAN number  (AAAAA9999A) ---
_add(
    "pan",
    r"\b[A-Z]{5}[0-9]{4}[A-Z]\b",
    "[PAN REDACTED]",
    re.IGNORECASE,   # keep as-is; PAN is uppercase by spec but guard both
)

# --- Aadhaar (12 digits, optionally space/dash separated in groups of 4) ---
_add(
    "aadhaar",
    r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b",
    "[AADHAAR REDACTED]",
)

# --- Credit / Debit card numbers (4-4-4-4, optionally space/dash separated) ---
_add(
    "card_number",
    r"\b(?:\d{4}[\s\-]?){3}\d{4}\b",
    "[CARD-NUMBER REDACTED]",
)

# --- Bank account numbers (explicit label) ---
_add(
    "account_number",
    r"((?:account\s*(?:no|number|num)|a/c\s*(?:no|number|num)?|acc\s*(?:no|number))\s*[:.\-]?\s*)\d[\d\s]{8,17}\d",
    r"\1[ACCOUNT-NO REDACTED]",
)

# --- IFSC codes ---
_add(
    "ifsc",
    r"\b[A-Z]{4}0[A-Z0-9]{6}\b",
    "[IFSC REDACTED]",
    0,   # IFSC is always uppercase; case-sensitive match is safer
)

# --- Indian mobile numbers (+91 prefix or bare 10-digit starting with 6-9) ---
_add(
    "phone",
    r"(?:\+91[\s\-]?|0)?[6-9]\d{9}\b",
    "[PHONE REDACTED]",
)

# --- Date of birth (labeled) ---
_add(
    "dob",
    r"((?:d\.?o\.?b\.?|date\s+of\s+birth)\s*[:=]\s*)"
    r"\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}",
    r"\1[DOB REDACTED]",
)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def mask_sensitive_data(text: str) -> str:
    """
    Apply all masking rules to *text* and return the sanitised version.
    Rules are applied in order; later rules see the already-masked output of
    earlier rules, so overlapping patterns are handled gracefully.
    """
    if not text:
        return text
    for _label, pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text
