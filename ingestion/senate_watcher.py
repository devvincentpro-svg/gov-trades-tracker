import requests
from ingestion.normalizer import parse_amount, normalize_type, make_id, clean_ticker
from database import upsert_trade, log_fetch
from config import SENATE_API_URL


def fetch():
    try:
        resp = requests.get(SENATE_API_URL, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log_fetch("senate_watcher", 0, f"error: {e}")
        return 0

    count = 0
    for filing in data:
        senator = f"{filing.get('first_name', '')} {filing.get('last_name', '')}".strip()
        disclosed = filing.get("date_recieved", "")  # API typo intentional

        for tx in filing.get("transactions", []):
            ticker = clean_ticker(tx.get("ticker", ""))
            trade_date = tx.get("transaction_date", "")
            trade_type = normalize_type(tx.get("type", ""))
            amount_low, amount_high = parse_amount(tx.get("amount", ""))

            trade = {
                "id": make_id(senator, ticker or tx.get("asset_description", ""), trade_date, trade_type),
                "politician": senator,
                "chamber": "senate",
                "party": "",
                "state": "",
                "ticker": ticker,
                "asset_name": tx.get("asset_description", ""),
                "trade_type": trade_type,
                "trade_date": trade_date,
                "disclosed": disclosed,
                "amount_low": amount_low,
                "amount_high": amount_high,
                "sources": "senate_watcher",
            }
            upsert_trade(trade)
            count += 1

    log_fetch("senate_watcher", count, "ok")
    return count
