"""
Scrape Capitol Trades politician-specific pages using Congress.gov bioguide IDs.
URL: https://www.capitoltrades.com/politicians/{BIOGUIDE_ID}?page=N
Covers up to 3 years of history per politician.
"""
import re
import time
import requests
from bs4 import BeautifulSoup
from ingestion.normalizer import normalize_type, make_id
from database import upsert_trade, get_conn, log_fetch

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}
BASE = "https://www.capitoltrades.com"

_AMOUNT_RE = re.compile(r"([\d.]+)([KM]?)[\s–\-]+([\d.]+)([KM]?)", re.IGNORECASE)


def _parse_amount(raw: str):
    def to_int(n, u):
        v = float(n)
        return int(v * 1_000_000 if u.upper() == "M" else v * 1_000 if u.upper() == "K" else v)
    m = _AMOUNT_RE.search(raw)
    if m:
        return to_int(m.group(1), m.group(2)), to_int(m.group(3), m.group(4))
    return None, None


def _parse_ticker(raw: str) -> str:
    m = re.search(r"\b([A-Z]{1,5}):US\b", raw)
    return m.group(1) if m else ""


def _scrape_politician_page(bioguide: str, name: str, party: str, state: str, chamber: str, page: int) -> list[dict]:
    url = f"{BASE}/politicians/{bioguide}"
    params = {"page": page} if page > 1 else {}
    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=15)
        r.raise_for_status()
    except Exception:
        return []

    soup = BeautifulSoup(r.text, "lxml")
    rows = soup.select("table tbody tr")
    trades = []

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 5:
            continue
        try:
            # [0] Traded Issuer — "CompanyName|TICKER:US"
            raw0 = cells[0].get_text(separator="|", strip=True)
            ticker = _parse_ticker(raw0)
            asset_name = raw0.split("|")[0].strip()

            # [1] Published (disclosure date) — "26 Jan|2026"
            disclosed = cells[1].get_text(separator=" ", strip=True)

            # [2] Traded (trade date) — "16 Jan|2026"
            trade_date = cells[2].get_text(separator=" ", strip=True)

            # [4] Type — "buy" / "sell"
            trade_type = normalize_type(cells[4].get_text(strip=True))

            # [5] Size — "1M–5M", "500K–1M"
            amount_low, amount_high = _parse_amount(cells[5].get_text(strip=True))

            trades.append({
                "id": make_id(name, ticker or asset_name, trade_date, trade_type),
                "politician": name,
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


def fetch_politician(bioguide: str, name: str, party: str = "", state: str = "", chamber: str = "house", max_pages: int = 10) -> int:
    count = 0
    for page in range(1, max_pages + 1):
        trades = _scrape_politician_page(bioguide, name, party, state, chamber, page)
        if not trades:
            break
        for t in trades:
            upsert_trade(t)
        count += len(trades)
        time.sleep(0.4)
    return count


def fetch_watchlist(watchlist: list[dict], max_pages: int = 10) -> int:
    """
    watchlist: list of {bioguide, name, party, state, chamber}
    Uses Congress.gov API data if available.
    """
    total = 0
    for pol in watchlist:
        n = fetch_politician(
            pol["bioguide"], pol["name"],
            pol.get("party", ""), pol.get("state", ""), pol.get("chamber", "house"),
            max_pages=max_pages,
        )
        total += n
        time.sleep(0.3)

    log_fetch("capitol_trades_by_politician", total, "ok")
    return total


def fetch_all_from_congress_api(max_pages_per_pol: int = 5) -> int:
    """Scrape trades for ALL 536 current Congress members using their bioguide IDs."""
    from ingestion.congress_api_client import load_all_members, _normalize_party, _normalize_chamber

    members = load_all_members()
    total = 0
    for m in members:
        name_raw = m.get("name", "")
        # Convert "Last, First" → "First Last"
        if "," in name_raw:
            parts = name_raw.split(",", 1)
            name = f"{parts[1].strip()} {parts[0].strip()}"
        else:
            name = name_raw

        bioguide = m.get("bioguideId", "")
        party = _normalize_party(m.get("partyName", ""))
        state = m.get("state", "")
        terms = m.get("terms", {}).get("item", [])
        chamber = _normalize_chamber(terms)

        if not bioguide:
            continue

        n = fetch_politician(bioguide, name, party, state, chamber, max_pages=max_pages_per_pol)
        total += n
        time.sleep(0.3)

    log_fetch("capitol_trades_all_congress", total, "ok")
    return total
