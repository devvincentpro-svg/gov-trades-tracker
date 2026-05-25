import time
import requests
import xml.etree.ElementTree as ET
from database import get_conn, log_fetch

SEC_HEADERS = {"User-Agent": "GovTradesTracker admin@example.com"}
BASE = "https://data.sec.gov"

# Famous super investors: name → CIK (zero-padded to 10 digits)
SUPER_INVESTORS = {
    "Warren Buffett (Berkshire)": "0001067983",
    "Bill Ackman (Pershing Square)": "0001336528",
    "Michael Burry (Scion Asset)": "0001649339",
    "David Tepper (Appaloosa)": "0001656456",
    "Ray Dalio (Bridgewater)": "0001350694",
    "George Soros (Soros Fund)": "0001029160",
    "Stanley Druckenmiller (Duquesne)": "0001536411",
    "Seth Klarman (Baupost)": "0001061768",
    "Carl Icahn": "0001174922",
    "Ken Griffin (Citadel)": "0001423053",
    "David Einhorn (Greenlight)": "0001079114",
    "Dan Loeb (Third Point)": "0001404912",
    "Chase Coleman (Tiger Global)": "0001167483",
    "Philippe Laffont (Coatue)": "0001336652",
    "Larry Robbins (Glenview)": "0001279936",
}

NS = "http://www.sec.gov/edgar/document/thirteenf/informationtable"


def _get(url: str) -> requests.Response | None:
    try:
        r = requests.get(url, headers=SEC_HEADERS, timeout=20)
        r.raise_for_status()
        return r
    except Exception:
        return None


def _latest_13f_accession(cik: str) -> tuple[str, str] | None:
    """Return (accession_no_raw, filing_date) for the latest 13F-HR."""
    r = _get(f"{BASE}/submissions/CIK{cik}.json")
    if not r:
        return None
    data = r.json()
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    for i, form in enumerate(forms):
        if form in ("13F-HR", "13F-HR/A"):
            return recent["accessionNumber"][i], recent["filingDate"][i]
    return None


def _parse_infotable(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    holdings = []
    for info in root.iter(f"{{{NS}}}infoTable"):
        name   = info.findtext(f"{{{NS}}}nameOfIssuer", "")
        cusip  = info.findtext(f"{{{NS}}}cusip", "")
        value  = info.findtext(f"{{{NS}}}value", "0") or "0"
        shares_el = info.find(f"{{{NS}}}shrsOrPrnAmt")
        shares = shares_el.findtext(f"{{{NS}}}sshPrnamt", "0") if shares_el is not None else "0"

        holdings.append({
            "issuer": name.strip(),
            "cusip": cusip.strip(),
            "value_usd": int(value.replace(",", "")),
            "shares": int(shares.replace(",", "")),
        })
    return holdings


def _get_holdings_xml(cik: str, accession: str) -> str | None:
    acc_clean = accession.replace("-", "")
    cik_int = str(int(cik))  # remove leading zeros for URL

    # Try index to find the infotable XML filename
    idx = _get(f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_clean}/index.json")
    if idx:
        items = idx.json().get("directory", {}).get("item", [])
        # Prefer the largest XML file (infotable) — not the primary_doc
        xml_files = [f["name"] for f in items if f["name"].endswith(".xml") and f["name"] != "primary_doc.xml"]
        if xml_files:
            url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_clean}/{xml_files[0]}"
            r = _get(url)
            if r:
                return r.text

    # Fallback: try common filename pattern
    r = _get(f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_clean}/form13fInfoTable.xml")
    return r.text if r else None


def fetch() -> int:
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS super_investors (
            manager_id  TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            source      TEXT DEFAULT 'sec_edgar',
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
            source      TEXT DEFAULT 'sec_edgar',
            updated_at  TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (manager_id, ticker)
        );
        CREATE TABLE IF NOT EXISTS cusip_map (
            cusip   TEXT PRIMARY KEY,
            issuer  TEXT,
            ticker  TEXT
        );
    """)
    conn.commit()
    conn.close()

    total = 0
    for name, cik in SUPER_INVESTORS.items():
        result = _latest_13f_accession(cik)
        if not result:
            continue
        accession, filing_date = result
        quarter = filing_date[:7]  # "2026-02"

        xml_text = _get_holdings_xml(cik, accession)
        if not xml_text:
            continue

        holdings = _parse_infotable(xml_text)
        if not holdings:
            continue

        # Calculate total portfolio value for % allocation
        total_value = sum(h["value_usd"] for h in holdings) or 1

        conn = get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO super_investors (manager_id, name, source) VALUES (?,?,'sec_edgar')",
            (cik, name),
        )
        for h in holdings:
            pct = round(h["value_usd"] / total_value * 100, 2)
            conn.execute(
                """INSERT OR REPLACE INTO super_holdings
                   (manager_id, ticker, company, pct_port, value_usd, shares, quarter, source)
                   VALUES (?,?,?,?,?,?,?,'sec_edgar')""",
                (cik, h["cusip"], h["issuer"], pct, h["value_usd"], h["shares"], quarter),
            )
            # store cusip->issuer for enrichment
            conn.execute(
                "INSERT OR IGNORE INTO cusip_map (cusip, issuer) VALUES (?,?)",
                (h["cusip"], h["issuer"]),
            )
        conn.commit()
        conn.close()
        total += len(holdings)
        time.sleep(0.3)

    log_fetch("sec_edgar_13f", total, "ok")
    return total
