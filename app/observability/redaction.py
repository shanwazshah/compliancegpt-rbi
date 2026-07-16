"""PII redaction for logs (spec §16).

Compliance users sometimes paste sensitive identifiers into a question ("re-KYC
for account 123456789012?"). We redact those before anything is written to the
query log, so no raw account/ID numbers are ever persisted.

Order matters: match the most specific patterns (PAN, Aadhaar) before the generic
long-digit-run rule.
"""

from __future__ import annotations

import re

# Indian identifiers: PAN = 5 letters, 4 digits, 1 letter. Aadhaar = 12 digits
# (often spaced 4-4-4). Generic account/card = a run of 9-18 digits.
_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"), "[REDACTED_PAN]"),
    (re.compile(r"\b\d{4}\s\d{4}\s\d{4}\b"), "[REDACTED_AADHAAR]"),
    (re.compile(r"\b\d{9,18}\b"), "[REDACTED_NUMBER]"),
]


def redact(text: str) -> str:
    """Return `text` with PII-like tokens replaced by redaction markers."""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text
