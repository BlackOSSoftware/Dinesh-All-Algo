"""
Angel One SmartAPI — order REST helpers (place / cancel / order book).
"""

from __future__ import annotations

import json
import logging
import ssl
import urllib.error
import urllib.request
from typing import Any

LOG = logging.getLogger(__name__)

PLACE_ORDER_URL = "https://apiconnect.angelone.in/rest/secure/angelbroking/order/v1/placeOrder"
CANCEL_ORDER_URL = "https://apiconnect.angelone.in/rest/secure/angelbroking/order/v1/cancelOrder"
MODIFY_ORDER_URL = "https://apiconnect.angelone.in/rest/secure/angelbroking/order/v1/modifyOrder"
ORDER_BOOK_URL = "https://apiconnect.angelone.in/rest/secure/angelbroking/order/v1/getOrderBook"
SEARCH_SCRIP_URL = "https://apiconnect.angelone.in/rest/secure/angelbroking/order/v1/searchScrip"


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


def _format_limit_price(limit_price: float) -> str:
    rounded = round(limit_price, 2)
    if abs(rounded - round(rounded)) < 1e-9:
        return str(int(round(rounded)))
    return f"{rounded:.2f}"


def place_order(
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
    limit_price: float | None = None,
    variety: str = "NORMAL",
    timeout_sec: float = 20.0,
) -> dict[str, Any]:
    otype = order_type.upper()
    if limit_price is not None and limit_price > 0:
        otype = "LIMIT"
        price_field = _format_limit_price(limit_price)
    elif otype == "LIMIT":
        raise ValueError("LIMIT order requires limit_price")
    else:
        price_field = "0"
        otype = "MARKET"

    body = {
        "variety": variety,
        "tradingsymbol": tradingsymbol,
        "symboltoken": str(symboltoken),
        "transactiontype": transaction_type.upper(),
        "exchange": exchange.upper(),
        "ordertype": otype,
        "producttype": product_type.upper(),
        "duration": "DAY",
        "price": price_field,
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
    return place_order(
        api_key=api_key,
        jwt_token=jwt_token,
        source_id=source_id,
        client_local_ip=client_local_ip,
        client_public_ip=client_public_ip,
        mac_address=mac_address,
        user_type=user_type,
        exchange=exchange,
        tradingsymbol=tradingsymbol,
        symboltoken=symboltoken,
        transaction_type=transaction_type,
        quantity=quantity,
        product_type=product_type,
        order_type=order_type,
        variety=variety,
        timeout_sec=timeout_sec,
    )


def search_scrip(
    *,
    api_key: str,
    jwt_token: str,
    source_id: str,
    client_local_ip: str,
    client_public_ip: str,
    mac_address: str,
    user_type: str,
    exchange: str,
    searchscrip: str,
    timeout_sec: float = 20.0,
) -> dict[str, Any]:
    from app.services.angel_upstream_gate import acquire_angel_upstream_slot

    acquire_angel_upstream_slot()
    body = {"exchange": exchange.upper(), "searchscrip": searchscrip}
    h = _headers(
        api_key=api_key,
        jwt_token=jwt_token,
        source_id=source_id,
        client_local_ip=client_local_ip,
        client_public_ip=client_public_ip,
        mac_address=mac_address,
        user_type=user_type,
    )
    return _post_json(SEARCH_SCRIP_URL, body, h, timeout_sec)


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
