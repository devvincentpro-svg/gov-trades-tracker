import requests
from ingestion.normalizer import parse_amount, normalize_type, make_id, clean_ticker
from database import upsert_trade, log_fetch
from config import FINNHUB_API_KEY


def fetch():
    if not FINNHUB_API_KEY:
        return 0

    try:
        resp = requests.get(
            "https://finnhub.io/api/v1/stock/congressional-trading",
            params={"token": FINNHUB_API_KEY},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
    except Exception as e:
        log_fetch("finnhub", 0, f"error: {e}")
        return 0

    count = 0
    for row in data:
        ticker = clean_ticker(row.get("symbol", ""))
        politician = row.get("name", "").strip()
        trade_date = row.get("transactionDate", "")
        trade_type = normalize_type(row.get("transactionType", ""))
        amount_low, amount_high = parse_amount(row.get("amount", ""))

        chamber = "senate" if row.get("chamber", "").lower() == "senate" else "house"

        trade = {
            "id": make_id(politician, ticker, trade_date, trade_type),
            "politician": politician,
            "chamber": chamber,
            "party": row.get("party", ""),
            "state": row.get("state", ""),
            "ticker": ticker,
            "asset_name": row.get("assetDescription", ""),
            "trade_type": trade_type,
            "trade_date": trade_date,
            "disclosed": row.get("filingDate", ""),
            "amount_low": amount_low,
            "amount_high": amount_high,
            "sources": "finnhub",
        }
        upsert_trade(trade)
        count += 1

    log_fetch("finnhub", count, "ok")
    return count
