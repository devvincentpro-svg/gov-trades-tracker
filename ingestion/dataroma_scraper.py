import re
import time
import requests
from bs4 import BeautifulSoup
from database import get_conn, log_fetch

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.dataroma.com/",
}
BASE = "https://www.dataroma.com"


def _init_tables():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS super_investors (
            manager_id  TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            source      TEXT DEFAULT 'dataroma',
            updated_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS super_holdings (
            manager_id  TEXT NOT NULL,
            ticker      TEXT NOT NULL,
            company     TEXT,
            pct_port    REAL,
            value_usd   INTEGER,
            shares      INTEGER,
            activity    TEXT,
            quarter     TEXT,
            source      TEXT DEFAULT 'dataroma',
            updated_at  TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (manager_id, ticker)
        );
    """)
    conn.commit()
    conn.close()


def _get_managers() -> list[dict]:
    r = requests.get(f"{BASE}/m/managers.php", headers=HEADERS, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    managers = []
    for a in soup.select("a[href*='holdings.php?m=']"):
        href = a.get("href", "")
        m = re.search(r"m=([A-Z0-9]+)", href)
        if m:
            managers.append({"id": m.group(1), "name": a.get_text(strip=True)})
    return managers


def _parse_holdings(manager_id: str, html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    holdings = []

    # Dataroma table#grid columns (0-based):
    # [0] History  [1] Stock(link)  [2] % Portfolio  [3] Activity  [4] Shares  [5] Reported Price
    rows = soup.select("table#grid tr")

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 3:
            continue
        try:
            # [1] Stock cell — contains <a href="...sym=TICKER"> Company Name
            stock_cell = cells[1]
            link = stock_cell.find("a")
            if not link:
                continue
            href = link.get("href", "")
            tick_m = re.search(r"sym=([A-Z.\-]+)", href)
            ticker = tick_m.group(1).upper() if tick_m else link.get_text(strip=True).upper()
            company = stock_cell.get_text(separator=" ", strip=True)

            # [2] % of Portfolio
            pct_raw = cells[2].get_text(strip=True).replace("%", "").replace(",", "")
            try:
                pct = float(pct_raw)
            except ValueError:
                pct = 0.0

            # [3] Recent Activity (New, Add, Reduce, Sold)
            activity = cells[3].get_text(strip=True) if len(cells) > 3 else ""

            # [4] Shares
            shares_raw = cells[4].get_text(strip=True).replace(",", "") if len(cells) > 4 else "0"
            try:
                shares = int(shares_raw)
            except ValueError:
                shares = 0

            holdings.append({
                "manager_id": manager_id,
                "ticker": ticker,
                "company": company,
                "pct_port": pct,
                "value_usd": 0,   # not directly shown; computed from shares * price elsewhere
                "shares": shares,
                "activity": activity,
            })
        except Exception:
            continue

    return holdings


def fetch(max_managers: int = 30) -> int:
    _init_tables()
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        managers = _get_managers()
    except Exception as e:
        log_fetch("dataroma", 0, f"managers error: {e}")
        return 0

    # Store manager list
    conn = get_conn()
    for mgr in managers:
        conn.execute(
            "INSERT OR REPLACE INTO super_investors (manager_id, name, source) VALUES (?,?,'dataroma')",
            (mgr["id"], mgr["name"]),
        )
    conn.commit()
    conn.close()

    count = 0
    for mgr in managers[:max_managers]:
        try:
            resp = session.get(f"{BASE}/m/holdings.php?m={mgr['id']}", timeout=15)
            resp.raise_for_status()
            holdings = _parse_holdings(mgr["id"], resp.text)

            conn = get_conn()
            for h in holdings:
                conn.execute(
                    """INSERT OR REPLACE INTO super_holdings
                       (manager_id, ticker, company, pct_port, value_usd, shares, activity, quarter)
                       VALUES (?,?,?,?,?,?,?, date('now'))""",
                    (h["manager_id"], h["ticker"], h["company"],
                     h["pct_port"], h["value_usd"], h["shares"], h["activity"]),
                )
            conn.commit()
            conn.close()
            count += len(holdings)
            time.sleep(0.4)  # be polite to Dataroma
        except Exception:
            continue

    log_fetch("dataroma", count, "ok")
    return count
