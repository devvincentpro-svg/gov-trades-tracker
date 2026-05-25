import requests
from ingestion.normalizer import parse_amount, normalize_type, make_id, clean_ticker
from database import upsert_trade, log_fetch
from config import HOUSE_JSON_URL


def fetch():
    try:
        resp = requests.get(HOUSE_JSON_URL, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log_fetch("house_watcher", 0, f"error: {e}")
        return 0

    count = 0
    for row in data:
        ticker = clean_ticker(row.get("ticker", ""))
        politician = f"{row.get('representative', '')}".strip()
        trade_date = row.get("transaction_date", "")
        trade_type = normalize_type(row.get("type", ""))
        amount_low, amount_high = parse_amount(row.get("amount", ""))

        trade = {
            "id": make_id(politician, ticker or row.get("asset_description", ""), trade_date, trade_type),
            "politician": politician,
            "chamber": "house",
            "party": row.get("party", ""),
            "state": row.get("district", "")[:2] if row.get("district") else "",
            "ticker": ticker,
            "asset_name": row.get("asset_description", ""),
            "trade_type": trade_type,
            "trade_date": trade_date,
            "disclosed": row.get("disclosure_date", ""),
            "amount_low": amount_low,
            "amount_high": amount_high,
            "sources": "house_watcher",
        }
        upsert_trade(trade)
        count += 1

    log_fetch("house_watcher", count, "ok")
    return count
