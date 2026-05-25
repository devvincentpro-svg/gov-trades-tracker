import re
import requests
from bs4 import BeautifulSoup
from ingestion.normalizer import normalize_type, make_id
from database import upsert_trade, log_fetch
from config import CAPITOL_TRADES_URL

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# Matches "1K–15K", "15K–50K", "500K–1M", "1M–5M"
_AMOUNT_RE = re.compile(r"([\d.]+)([KM]?)[\s–-]+([\d.]+)([KM]?)", re.IGNORECASE)


def _parse_amount_kt(raw: str):
    """Convert Capitol Trades shorthand (e.g. '1K–15K') to integer range."""
    if not raw or raw.strip().lower() in ("undisclosed", "n/a", ""):
        return None, None

    def to_int(num: str, unit: str) -> int:
        n = float(num)
        u = unit.upper()
        if u == "K":
            return int(n * 1_000)
        if u == "M":
            return int(n * 1_000_000)
        return int(n)

    m = _AMOUNT_RE.search(raw)
    if m:
        return to_int(m.group(1), m.group(2)), to_int(m.group(3), m.group(4))
    return None, None


def _parse_ticker(raw: str) -> str:
    """Extract ticker from 'ADI:US' → 'ADI'."""
    if not raw:
        return ""
    return raw.split(":")[0].strip().upper()


def _parse_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    rows = soup.select("table tbody tr")
    trades = []

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 8:
            continue
        try:
            # [0] Politician | Party | Chamber | State
            parts0 = [p.strip() for p in cells[0].get_text(separator="|").split("|") if p.strip()]
            politician = parts0[0] if parts0 else ""
            party      = parts0[1] if len(parts0) > 1 else ""
            chamber_r  = parts0[2].lower() if len(parts0) > 2 else "house"
            state      = parts0[3] if len(parts0) > 3 else ""
            chamber    = "senate" if "senate" in chamber_r or "sen" in chamber_r else "house"

            # [1] Asset name | TICKER:US
            parts1 = [p.strip() for p in cells[1].get_text(separator="|").split("|") if p.strip()]
            asset_name = parts1[0] if parts1 else ""
            ticker     = _parse_ticker(parts1[1]) if len(parts1) > 1 else ""

            # [2] Disclosed date/time (e.g. "13:01|Today" or "May 20|2026")
            disclosed = cells[2].get_text(separator=" ", strip=True)

            # [3] Trade date (e.g. "29 Apr|2026")
            trade_date = cells[3].get_text(separator=" ", strip=True)

            # [6] Trade type
            trade_type = normalize_type(cells[6].get_text(strip=True))

            # [7] Amount range (e.g. "1K–15K")
            amount_raw = cells[7].get_text(strip=True)
            amount_low, amount_high = _parse_amount_kt(amount_raw)

            trades.append({
                "id": make_id(politician, ticker or asset_name, trade_date, trade_type),
                "politician": politician,
                "chamber": chamber,
                "party": party,
                "state": state,
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


def fetch(pages: int = 5) -> int:
    count = 0
    session = requests.Session()
    session.headers.update(HEADERS)

    for page in range(1, pages + 1):
        try:
            resp = session.get(
                CAPITOL_TRADES_URL,
                params={"pageSize": 96, "page": page, "txDate": "90d"},
                timeout=20,
            )
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
