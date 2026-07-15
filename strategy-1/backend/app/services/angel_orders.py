"""
Angel One SmartAPI — order REST helpers (place / cancel / order book).
"""

from __future__ import annotations

import json
import time
import logging
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

LOG = logging.getLogger(__name__)

PLACE_ORDER_URL = "https://apiconnect.angelone.in/rest/secure/angelbroking/order/v1/placeOrder"
CANCEL_ORDER_URL = "https://apiconnect.angelone.in/rest/secure/angelbroking/order/v1/cancelOrder"
MODIFY_ORDER_URL = "https://apiconnect.angelone.in/rest/secure/angelbroking/order/v1/modifyOrder"
ORDER_BOOK_URL = "https://apiconnect.angelone.in/rest/secure/angelbroking/order/v1/getOrderBook"


def _headers(
    *,
    api_key: str,
    jwt_token: str,
    source_id: str,
    client_local_ip: str,
    client_public_ip: str,
    mac_address: str,
    user_type: str,
) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-PrivateKey": api_key,
        "X-SourceID": source_id,
        "X-ClientLocalIP": client_local_ip,
        "X-ClientPublicIP": client_public_ip,
        "X-MACAddress": mac_address,
        "X-UserType": user_type,
        "Authorization": f"Bearer {jwt_token}",
    }


def _post_json(url: str, body: dict[str, Any], headers: dict[str, str], timeout_sec: float) -> dict[str, Any]:
    raw = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=raw, headers=headers, method="POST")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec, context=ctx) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            data = json.loads(text)
            if not isinstance(data, dict):
                raise RuntimeError(f"Angel order non-object: {text[:400]}")
            return data
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        LOG.warning("Angel order HTTP %s: %s", e.code, err_body[:2000])
        raise RuntimeError(f"Angel order HTTP {e.code}: {err_body[:800]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(str(e.reason or e)) from e


def place_market_order(
    *,
    api_key: str,
    jwt_token: str,
    source_id: str,
    client_local_ip: str,
    client_public_ip: str,
    mac_address: str,
    user_type: str,
    exchange: str,
    tradingsymbol: str,
    symboltoken: str,
    transaction_type: str,
    quantity: int,
    product_type: str = "CARRYFORWARD",
    order_type: str = "MARKET",
    variety: str = "NORMAL",
    timeout_sec: float = 20.0,
) -> dict[str, Any]:
    body = {
        "variety": variety,
        "tradingsymbol": tradingsymbol,
        "symboltoken": str(symboltoken),
        "transactiontype": transaction_type.upper(),
        "exchange": exchange.upper(),
        "ordertype": order_type.upper(),
        "producttype": product_type.upper(),
        "duration": "DAY",
        "price": "0",
        "squareoff": "0",
        "stoploss": "0",
        "quantity": str(int(quantity)),
    }
    h = _headers(
        api_key=api_key,
        jwt_token=jwt_token,
        source_id=source_id,
        client_local_ip=client_local_ip,
        client_public_ip=client_public_ip,
        mac_address=mac_address,
        user_type=user_type,
    )
    return _post_json(PLACE_ORDER_URL, body, h, timeout_sec)


def cancel_order(
    *,
    api_key: str,
    jwt_token: str,
    source_id: str,
    client_local_ip: str,
    client_public_ip: str,
    mac_address: str,
    user_type: str,
    variety: str,
    order_id: str,
    timeout_sec: float = 20.0,
) -> dict[str, Any]:
    body = {"variety": variety, "orderid": order_id}
    h = _headers(
        api_key=api_key,
        jwt_token=jwt_token,
        source_id=source_id,
        client_local_ip=client_local_ip,
        client_public_ip=client_public_ip,
        mac_address=mac_address,
        user_type=user_type,
    )
    return _post_json(CANCEL_ORDER_URL, body, h, timeout_sec)


def modify_order(
    *,
    api_key: str,
    jwt_token: str,
    source_id: str,
    client_local_ip: str,
    client_public_ip: str,
    mac_address: str,
    user_type: str,
    variety: str,
    order_id: str,
    tradingsymbol: str,
    symboltoken: str,
    transaction_type: str,
    exchange: str,
    order_type: str,
    product_type: str,
    duration: str,
    quantity: int,
    price: str = "0",
    trigger_price: str = "0",
    disclosed_quantity: str = "0",
    square_off: str = "0",
    stop_loss: str = "0",
    timeout_sec: float = 20.0,
) -> dict[str, Any]:
    body = {
        "variety": variety,
        "orderid": order_id,
        "tradingsymbol": tradingsymbol,
        "symboltoken": str(symboltoken),
        "transactiontype": transaction_type.upper(),
        "exchange": exchange.upper(),
        "ordertype": order_type.upper(),
        "producttype": product_type.upper(),
        "duration": duration.upper(),
        "price": price,
        "quantity": str(int(quantity)),
        "triggerprice": trigger_price,
        "disclosedqty": disclosed_quantity,
        "squareoff": square_off,
        "stoploss": stop_loss,
    }
    h = _headers(
        api_key=api_key,
        jwt_token=jwt_token,
        source_id=source_id,
        client_local_ip=client_local_ip,
        client_public_ip=client_public_ip,
        mac_address=mac_address,
        user_type=user_type,
    )
    return _post_json(MODIFY_ORDER_URL, body, h, timeout_sec)


def get_order_book(
    *,
    api_key: str,
    jwt_token: str,
    source_id: str,
    client_local_ip: str,
    client_public_ip: str,
    mac_address: str,
    user_type: str,
    timeout_sec: float = 20.0,
) -> dict[str, Any]:
    h = _headers(
        api_key=api_key,
        jwt_token=jwt_token,
        source_id=source_id,
        client_local_ip=client_local_ip,
        client_public_ip=client_public_ip,
        mac_address=mac_address,
        user_type=user_type,
    )
    req = urllib.request.Request(ORDER_BOOK_URL, headers=h, method="GET")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec, context=ctx) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            data = json.loads(text)
            if not isinstance(data, dict):
                raise RuntimeError("order book not dict")
            return data
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise RuntimeError(f"order book HTTP {e.code}: {err_body[:800]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(str(e.reason or e)) from e


def extract_place_ack(raw: Any) -> tuple[str, bool, str]:
    """Parse Angel placeOrder JSON -> (order_id, api_ok, message)."""
    if not isinstance(raw, dict):
        return "", False, str(raw or "Invalid Angel order response")
    data = raw.get("data")
    order_id = ""
    if isinstance(data, dict):
        order_id = str(data.get("orderid") or data.get("orderId") or "").strip()
    elif data not in (None, ""):
        order_id = str(data).strip()
    if not order_id:
        order_id = str(raw.get("orderid") or raw.get("orderId") or "").strip()
    status = raw.get("status")
    ok = status is True or str(status or "").lower() in ("true", "success")
    message = str(raw.get("message") or raw.get("errorcode") or raw.get("errorCode") or "")
    return order_id, ok, message


def parse_order_book_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict) and isinstance(data.get("orderBook"), list):
        return [x for x in data["orderBook"] if isinstance(x, dict)]
    return []


def find_order_book_row(rows: list[dict[str, Any]], order_id: str) -> dict[str, Any] | None:
    oid = (order_id or "").strip()
    if not oid:
        return None
    for r in rows:
        rid = str(r.get("orderid") or r.get("orderId") or "").strip()
        if rid == oid:
            return r
    return None


def classify_order_book_status(row: dict[str, Any] | None) -> tuple[str, float, str]:
    """Return (COMPLETE|REJECTED|CANCELLED|OPEN|UNKNOWN, avg_price, text)."""
    if not row:
        return "UNKNOWN", 0.0, ""
    status = str(row.get("orderstatus") or row.get("orderStatus") or "").strip().lower()
    text = str(
        row.get("text")
        or row.get("rejectreason")
        or row.get("rejectReason")
        or row.get("statusmessage")
        or row.get("StatusMessage")
        or ""
    )
    try:
        avg = float(row.get("averageprice") or row.get("averagePrice") or 0)
    except (TypeError, ValueError):
        avg = 0.0
    if status in ("rejected",) or "reject" in status:
        return "REJECTED", avg, text or status
    if status in ("cancelled", "canceled"):
        return "CANCELLED", avg, text or status
    if status in ("complete", "filled"):
        return "COMPLETE", avg, text or status
    if status in (
        "open",
        "trigger pending",
        "pending",
        "open pending",
        "modify pending",
        "after market order req received",
    ):
        return "OPEN", avg, text or status
    return "UNKNOWN", avg, text or status


@dataclass(frozen=True)
class LiveOrderResult:
    order_id: str
    filled: bool
    status: str
    average_price: float
    message: str


def await_order_terminal(
    *,
    order_id: str,
    api_key: str,
    jwt_token: str,
    source_id: str,
    client_local_ip: str,
    client_public_ip: str,
    mac_address: str,
    user_type: str,
    timeout_sec: float = 4.0,
    poll_interval_sec: float = 0.12,
    cancel_if_unfilled: bool = True,
) -> LiveOrderResult:
    """Poll Angel order book until COMPLETE / REJECTED / CANCELLED, or timeout.

    On timeout with unfilled order, optionally cancel so broker and local state stay aligned.
    Positions must only be created when filled=True.
    """
    oid = (order_id or "").strip()
    if not oid:
        return LiveOrderResult("", False, "PLACE_FAILED", 0.0, "missing order id")

    hdr = dict(
        api_key=api_key,
        jwt_token=jwt_token,
        source_id=source_id,
        client_local_ip=client_local_ip,
        client_public_ip=client_public_ip,
        mac_address=mac_address,
        user_type=user_type,
    )
    deadline = time.monotonic() + max(0.4, float(timeout_sec))
    last_status = "UNKNOWN"
    last_msg = ""
    last_avg = 0.0

    def _once() -> LiveOrderResult | None:
        nonlocal last_status, last_msg, last_avg
        book = get_order_book(timeout_sec=min(8.0, max(2.0, float(timeout_sec))), **hdr)
        row = find_order_book_row(parse_order_book_rows(book), oid)
        status, avg, msg = classify_order_book_status(row)
        last_status, last_msg, last_avg = status, msg, avg
        if status == "COMPLETE":
            return LiveOrderResult(oid, True, status, float(avg or 0.0), msg or "FILLED")
        if status in ("REJECTED", "CANCELLED"):
            return LiveOrderResult(oid, False, status, 0.0, msg or status)
        return None

    while time.monotonic() < deadline:
        try:
            done = _once()
            if done is not None:
                return done
        except Exception as exc:  # noqa: BLE001
            last_msg = str(exc)
        time.sleep(max(0.05, float(poll_interval_sec)))

    if cancel_if_unfilled:
        try:
            cancel_order(variety="NORMAL", order_id=oid, timeout_sec=8.0, **hdr)
        except Exception:  # noqa: BLE001
            pass
        try:
            done = _once()
            if done is not None:
                return done
        except Exception as exc:  # noqa: BLE001
            last_msg = str(exc)

    return LiveOrderResult(
        oid,
        False,
        last_status if last_status not in ("UNKNOWN",) else "OPEN",
        float(last_avg or 0.0),
        last_msg or "order not broker-confirmed (unfilled)",
    )
