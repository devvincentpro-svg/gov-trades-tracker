import requests
from database import get_conn, log_fetch
from config import FINNHUB_API_KEY

# The congressional-trading endpoint requires a paid Finnhub plan.
# On the free tier we use Finnhub to enrich tickers with sector/industry data.


def _get(path: str, **params):
    if not FINNHUB_API_KEY:
        return None
    try:
        resp = requests.get(
            f"https://finnhub.io/api/v1/{path}",
            params={"token": FINNHUB_API_KEY, **params},
            timeout=10,
        )
        if resp.status_code == 403:
            return None  # endpoint not available on free tier
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def enrich_tickers():
    """Fetch sector/industry/name for each ticker we track and store in ticker_info table."""
    if not FINNHUB_API_KEY:
        return 0

    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ticker_info (
            ticker      TEXT PRIMARY KEY,
            name        TEXT,
            sector      TEXT,
            industry    TEXT,
            country     TEXT,
            market_cap  INTEGER,
            updated_at  TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()

    tickers = conn.execute(
        """SELECT DISTINCT ticker FROM trades
           WHERE ticker != ''
           AND ticker NOT IN (SELECT ticker FROM ticker_info)
           LIMIT 30"""
    ).fetchall()
    conn.close()

    count = 0
    for (ticker,) in tickers:
        data = _get("stock/profile2", symbol=ticker)
        if not data or not data.get("name"):
            continue

        conn = get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO ticker_info
               (ticker, name, sector, industry, country, market_cap)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                ticker,
                data.get("name", ""),
                data.get("finnhubIndustry", ""),
                data.get("finnhubIndustry", ""),
                data.get("country", ""),
                int(data.get("marketCapitalization", 0) or 0),
            ),
        )
        conn.commit()
        conn.close()
        count += 1

    log_fetch("finnhub_enrich", count, "ok")
    return count


def fetch() -> int:
    """Compatibility stub — enrich tickers instead of fetching trades."""
    return enrich_tickers()
