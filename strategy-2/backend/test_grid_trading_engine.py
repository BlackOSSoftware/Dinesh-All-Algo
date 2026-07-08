from types import SimpleNamespace

from app.config import settings
from app.services import angel_orders
from app.services import trading_repository as tr
from app.services.grid_trading_engine import _execute_live_order, process_user_tick


def test_execute_live_order_accepts_string_orderid_payload(monkeypatch):
    logs = []

    monkeypatch.setattr(
        angel_orders,
        "place_order",
        lambda **kwargs: {"status": True, "data": "251234567890123", "message": "SUCCESS"},
    )
    monkeypatch.setattr(tr, "append_trading_log", lambda *args, **kwargs: logs.append(kwargs))

    instrument = SimpleNamespace(
        exchange="MCX",
        tradingsymbol="NATURALGAS25JUN26FUT",
        token="12345",
        lotsize=1,
        configured=True,
    )

    order_id = _execute_live_order(
        db=object(),
        user_id=1,
        instrument=instrument,
        mode="LIVE",
        action="INITIAL_BUY",
        lots=10,
        grid_price=311.5,
        ltp_at_signal=311.5,
        level_id="BASE",
    )

    assert order_id == "251234567890123"
    assert logs[-1]["action"] == "LIVE_INITIAL_BUY"
    assert logs[-1]["order_id"] == "251234567890123"


def test_process_user_tick_executes_crossed_live_entry_without_live_skipped(monkeypatch):
    logs = []
    saved = {}
    synced = []

    class FakeDb:
        def scalar(self, _query):
            return SimpleNamespace(user_id=1, algo_running=True, trading_mode="LIVE")

    cfg = {
        "startTime": "00:00",
        "endTime": "23:59",
        "market": "CRUDE_OIL",
        "referencePrice": 317.7,
        "initialLots": 10,
        "gridGap": 5,
        "gridLevelsAbove": 1,
        "gridLevelsBelow": 1,
        "lotsPerGrid": 2,
        "grid_runtime": {
            "positionLots": 0,
            "realizedPnl": 0.0,
            "avgEntryPrice": 0.0,
            "lastPrice": 317.6,
            "prevPrice": 317.6,
            "sessionAnchorPrice": 315.0,
            "lastLevelId": None,
            "baseEntered": False,
            "levelStates": {},
            "upperArmLocks": {},
            "upperReenterHold": {},
            "upperPeakSold": 0,
            "nextActionLevel": "BASE",
        },
    }

    class DummySelect:
        def where(self, *_args, **_kwargs):
            return self

    monkeypatch.setattr("app.services.grid_trading_engine.select", lambda *_args, **_kwargs: DummySelect())
    monkeypatch.setattr(tr, "load_config_dict", lambda _db, _user_id: cfg.copy())
    monkeypatch.setattr(
        tr,
        "save_strategy_settings",
        lambda _db, _user_id, config: saved.setdefault("config", config),
    )
    monkeypatch.setattr(
        "app.services.grid_trading_engine._sync_positions_for_actions",
        lambda _db, **kwargs: synced.append(kwargs),
    )
    monkeypatch.setattr(
        tr,
        "append_trading_log",
        lambda *args, **kwargs: logs.append(kwargs),
    )
    monkeypatch.setattr(
        "app.services.grid_trading_engine.get_instrument",
        lambda _market: SimpleNamespace(
            exchange="MCX",
            tradingsymbol="CRUDEOILTEST",
            token="123",
            lotsize=1,
            configured=True,
        ),
    )
    monkeypatch.setattr(
        "app.services.grid_trading_engine.get_quote_by_key",
        lambda _market: SimpleNamespace(price=319.8),
    )
    monkeypatch.setattr(settings, "angel_live_trading_enabled", True, raising=False)
    monkeypatch.setattr(settings, "angel_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "angel_jwt_token", "test-jwt", raising=False)
    monkeypatch.setattr(
        angel_orders,
        "place_order",
        lambda **_kwargs: {"status": True, "data": "ORDER-1", "message": "SUCCESS"},
    )

    process_user_tick(FakeDb(), 1)

    assert synced, "runtime/actions should be persisted after a crossed live entry"
    assert synced[0]["actions"]
    assert synced[0]["actions"][0]["action"] == "INITIAL_BUY"
    assert synced[0]["actions"][0]["level"] == "BASE"
    assert not any(log["action"] == "LIVE_SKIPPED" for log in logs)
    assert any(log["action"] == "LIVE_INITIAL_BUY" for log in logs)
    assert any(log["action"] == "INITIAL_BUY" for log in logs)
