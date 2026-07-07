"""Tests for StocksRin HMAC token generation."""

import hashlib
import hmac

from datetime import datetime, timezone

from app.services.stocksrin.token_generator import (
    generate_daily_app_authorization,
    generate_request_credentials,
)


def test_daily_app_authorization_vector():
    token = generate_daily_app_authorization(utc_date="2026-06-29")
    assert len(token) == 64
    assert token == generate_daily_app_authorization(utc_date="2026-06-29")


def test_generate_credentials_format():
    nonce, token = generate_request_credentials(hmac_key="stocksrinkey")
    assert len(nonce) == 32
    assert len(token) == 64
    expected = hmac.new(b"stocksrinkey", nonce.encode(), hashlib.sha256).hexdigest()
    assert token == expected
