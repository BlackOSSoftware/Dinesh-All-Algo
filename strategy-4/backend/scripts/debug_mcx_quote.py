"""Debug MCX quote raw Angel response. Run: python scripts/debug_mcx_quote.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.mcx_instruments import load_mcx_instruments
from app.services.mcx_quotes import fetch_all_mcx_quotes, _extract_ltp_map
from app.services.angel_quote import post_market_quote, _truthy_status
from app.config import settings

def main():
    inst = load_mcx_instruments()
    print("=== instruments ===")
    for k, v in inst.items():
        print(k, v.tradingsymbol, v.token)

    tokens = {}
    for v in inst.values():
        if v.token:
            tokens.setdefault(v.exchange, []).append(v.token)

    for mode in ("LTP", "OHLC", "FULL"):
        print(f"\n=== mode {mode} ===")
        raw = post_market_quote(
            mode=mode,
            exchange_tokens=tokens,
            timeout_sec=15,
            api_key=settings.angel_api_key.strip(),
            jwt_token=settings.angel_jwt_token.strip(),
            source_id=settings.angel_source_id,
            client_local_ip=settings.angel_client_local_ip,
            client_public_ip=settings.angel_client_public_ip,
            mac_address=settings.angel_mac_address,
            user_type=settings.angel_user_type,
        )
        print("status", _truthy_status(raw))
        data = raw.get("data") or {}
        fetched = data.get("fetched") or []
        print("fetched count", len(fetched))
        for row in fetched:
            print(json.dumps(row, indent=2))
        print("ltp_map", _extract_ltp_map(raw))

    print("\n=== fetch_all_mcx_quotes ===")
    for q in fetch_all_mcx_quotes():
        print(q)

if __name__ == "__main__":
    main()
