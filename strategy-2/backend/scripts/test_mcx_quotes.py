"""Print resolved MCX tokens and sample LTP (run from backend folder)."""
from app.services.mcx_instruments import load_mcx_instruments
from app.services.mcx_quotes import fetch_all_mcx_quotes

if __name__ == "__main__":
    inst = load_mcx_instruments()
    for k, v in inst.items():
        print(k, v.token, v.tradingsymbol, v.configured)
    print("--- quotes ---")
    for q in fetch_all_mcx_quotes():
        print(q.key, q.price, q.source, q.error or "")
