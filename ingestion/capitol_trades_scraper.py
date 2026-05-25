import requests
from bs4 import BeautifulSoup
from ingestion.normalizer import parse_amount, normalize_type, make_id, clean_ticker
from database import upsert_trade, log_fetch
from config import CAPITOL_TRADES_URL

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def _parse_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    trades = []

    # Capitol Trades renders trades in <tbody> rows
    rows = soup.select("table tbody tr")
    if not rows:
        # fallback: look for article/div-based trade cards
        rows = soup.select("[data-testid='trade-row'], .trade-row, article")

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 6:
            continue

        try:
            # Column order on capitoltrades.com (as of 2025-2026):
            # 0: politician name + party + chamber
            # 1: asset (ticker + name)
            # 2: trade type
            # 3: trade date
            # 4: disclosed date
            # 5: amount range
            politician_cell = cells[0]
            politician = politician_cell.get_text(separator=" ", strip=True)
            # extract party from badge
            party_tag = politician_cell.find(class_=lambda c: c and "party" in c.lower())
            party = party_tag.get_text(strip=True) if party_tag else ""

            asset_cell = cells[1]
            ticker_tag = asset_cell.find(class_=lambda c: c and "ticker" in c.lower())
            ticker = clean_ticker(ticker_tag.get_text(strip=True) if ticker_tag else "")
            asset_name = asset_cell.get_text(separator=" ", strip=True)

            trade_type = normalize_type(cells[2].get_text(strip=True))
            trade_date = cells[3].get_text(strip=True)
            disclosed  = cells[4].get_text(strip=True)
            amount_low, amount_high = parse_amount(cells[5].get_text(strip=True))

            # detect chamber from URL or text
            chamber_tag = politician_cell.find(class_=lambda c: c and "chamber" in c.lower())
            chamber_raw = chamber_tag.get_text(strip=True).lower() if chamber_tag else ""
            chamber = "senate" if "senate" in chamber_raw or "sen" in chamber_raw else "house"

            trades.append({
                "id": make_id(politician, ticker or asset_name, trade_date, trade_type),
                "politician": politician,
                "chamber": chamber,
                "party": party,
                "state": "",
                "ticker": ticker,
                "asset_name": asset_name,
                "trade_type": trade_type,
                "trade_date": trade_date,
                "disclosed": disclosed,
                "amount_low": amount_low,
                "amount_high": amount_high,
                "sources": "capitol_trades",
            })
        except Exception:
            continue

    return trades


def fetch(pages: int = 3) -> int:
    count = 0
    session = requests.Session()
    session.headers.update(HEADERS)

    for page in range(1, pages + 1):
        params = {
            "pageSize": 96,
            "page": page,
            "txDate": "90d",
        }
        try:
            resp = session.get(CAPITOL_TRADES_URL, params=params, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            log_fetch("capitol_trades", count, f"error page {page}: {e}")
            break

        trades = _parse_page(resp.text)
        if not trades:
            break

        for t in trades:
            upsert_trade(t)
            count += 1

    log_fetch("capitol_trades", count, "ok")
    return count
