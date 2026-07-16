"""Tests for API-key auth and the rate limiter (spec §16)."""

import types

import pytest
from fastapi import HTTPException

from app.api import security
from app.config import settings


def _fake_request(host: str = "1.2.3.4"):
    return types.SimpleNamespace(client=types.SimpleNamespace(host=host))


def test_api_key_open_when_unset(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "")
    security.require_api_key(x_api_key=None)  # no raise


def test_api_key_enforced_when_set(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret")
    with pytest.raises(HTTPException) as exc:
        security.require_api_key(x_api_key="wrong")
    assert exc.value.status_code == 401
    security.require_api_key(x_api_key="secret")  # correct key passes


def test_rate_limit_blocks_after_limit(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_min", 3)
    security._hits.clear()
    req = _fake_request("test-client")
    for _ in range(3):
        security.rate_limit(req, x_api_key=None)  # first 3 pass
    with pytest.raises(HTTPException) as exc:
        security.rate_limit(req, x_api_key=None)  # 4th blocked
    assert exc.value.status_code == 429
