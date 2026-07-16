"""Tests for PII redaction of log text (spec §16)."""

from app.observability.redaction import redact


def test_redacts_account_number():
    out = redact("What is the KYC status for account 123456789012?")
    assert "123456789012" not in out
    assert "REDACTED" in out


def test_redacts_pan():
    out = redact("My PAN is ABCDE1234F, is re-KYC due?")
    assert "ABCDE1234F" not in out
    assert "[REDACTED_PAN]" in out


def test_redacts_aadhaar_spaced():
    out = redact("Aadhaar 1234 5678 9012 for verification")
    assert "1234 5678 9012" not in out
    assert "[REDACTED_AADHAAR]" in out


def test_leaves_normal_text_untouched():
    text = "What is the re-KYC periodicity for a low-risk NBFC customer?"
    assert redact(text) == text
