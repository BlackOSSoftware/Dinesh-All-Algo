"""Tests for StocksRin session header provider."""

from app.services.stocksrin.header_provider import build_headers, normalize_authorization
from app.services.stocksrin.cookie_store import StocksRinSession


def test_normalize_authorization_strips_bearer():
    assert normalize_authorization("Bearer abc123") == "abc123"
    assert normalize_authorization("abc123") == "abc123"


def test_build_headers_no_bearer():
    sess = StocksRinSession(
        authorization="tok123",
        user="RS-1",
        cookies={"sid": "xyz"},
    )
    h = build_headers(sess)
    assert len(h["Authorization"]) == 64
    assert not h["Authorization"].lower().startswith("bearer")
    assert h["Authorization"] != "tok123"
    assert len(h["x-request-token"]) == 64
    assert len(h["x-request-nonce"]) == 32
    assert h["x-user"] == "RS-1"
    assert "Origin" in h
