from app.services.mcx_scrip_resolver import (
    _save_disk_cache,
    _stale_cached_entry,
    tradingsymbol_is_expired,
)


def test_tradingsymbol_is_expired_for_rolled_crude_contract():
    assert tradingsymbol_is_expired("CRUDEOIL20JUL26FUT") is True
    assert tradingsymbol_is_expired("CRUDEOILM20JUL26FUT") is True


def test_tradingsymbol_is_live_for_next_month_contract():
    assert tradingsymbol_is_expired("CRUDEOIL19AUG26FUT") is False
    assert tradingsymbol_is_expired("NATURALGAS28JUL26FUT") is False


def test_stale_cache_ignores_expired_contract(tmp_path, monkeypatch):
    from app.services import mcx_scrip_resolver as resolver

    cache_path = tmp_path / "mcx_tokens_cache.json"
    monkeypatch.setattr(resolver, "_CACHE_PATH", cache_path)

    _save_disk_cache(
        {
            "CRUDE_OIL": {
                "key": "CRUDE_OIL",
                "token": "12345",
                "tradingsymbol": "CRUDEOIL20JUL26FUT",
                "_ts": 1.0,
            }
        }
    )

    assert _stale_cached_entry("CRUDE_OIL") is None
    assert "CRUDE_OIL" not in cache_path.read_text(encoding="utf-8")
