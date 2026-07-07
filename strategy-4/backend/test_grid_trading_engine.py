from types import SimpleNamespace

from app.services import angel_orders
from app.services import trading_repository as tr
from app.services.grid_trading_engine import _execute_live_order


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
