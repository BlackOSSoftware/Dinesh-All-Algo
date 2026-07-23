from pathlib import Path

from app.services.angel_upstream_gate import (
    angel_rate_limit_remaining,
    clear_angel_rate_limit,
    note_angel_rate_limit,
    recent_angel_jwt_validated,
    note_angel_jwt_validated,
)


def test_rate_limit_backoff_and_clear(tmp_path, monkeypatch):
    from app.services import angel_upstream_gate as gate

    monkeypatch.setattr(gate, "_repo_root", lambda: tmp_path)
    (tmp_path / ".angel_shared").mkdir(parents=True, exist_ok=True)

    clear_angel_rate_limit()
    assert angel_rate_limit_remaining() == 0.0

    wait = note_angel_rate_limit(detail="exceeding access rate")
    assert wait >= 2.0
    assert angel_rate_limit_remaining() > 0

    clear_angel_rate_limit()
    assert angel_rate_limit_remaining() == 0.0


def test_jwt_validate_stamp(tmp_path, monkeypatch):
    from app.services import angel_upstream_gate as gate

    monkeypatch.setattr(gate, "_repo_root", lambda: tmp_path)
    (tmp_path / ".angel_shared").mkdir(parents=True, exist_ok=True)

    assert recent_angel_jwt_validated(max_age_sec=60) is False
    note_angel_jwt_validated()
    assert recent_angel_jwt_validated(max_age_sec=60) is True
