import requests
from database import get_conn, log_fetch
from config import OPENSECRETS_KEY, OPENSECRETS_URL

# OpenSecrets CID cache: maps normalized politician name -> CID
_CID_CACHE: dict[str, str] = {}


def _get(method: str, **params) -> dict | None:
    try:
        resp = requests.get(
            OPENSECRETS_URL,
            params={"method": method, "output": "json", "apikey": OPENSECRETS_KEY, **params},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def _load_legislators() -> dict[str, str]:
    """Return {normalized_name: cid} for all current legislators."""
    mapping: dict[str, str] = {}
    # fetch all states (OpenSecrets requires a state code for getLegislators)
    states = [
        "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN",
        "IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV",
        "NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN",
        "TX","UT","VT","VA","WA","WV","WI","WY",
    ]
    for state in states:
        data = _get("getLegislators", id=state)
        if not data:
            continue
        legislators = data.get("response", {}).get("legislator", [])
        if isinstance(legislators, dict):
            legislators = [legislators]
        for leg in legislators:
            attrs = leg.get("@attributes", {})
            name = attrs.get("firstlast", "").strip().lower()
            cid = attrs.get("cid", "")
            if name and cid:
                mapping[name] = cid
    return mapping


def _get_cid(politician: str) -> str | None:
    global _CID_CACHE
    if not _CID_CACHE:
        _CID_CACHE = _load_legislators()
    key = politician.lower().strip()
    # exact match
    if key in _CID_CACHE:
        return _CID_CACHE[key]
    # partial match (last name)
    last = key.split()[-1] if key else ""
    for name, cid in _CID_CACHE.items():
        if last and last in name:
            return cid
    return None


def enrich_with_pfd():
    """Fetch PFD profiles from OpenSecrets and store enriched party/state info in DB."""
    if not OPENSECRETS_KEY:
        return 0

    conn = get_conn()
    politicians = conn.execute(
        "SELECT DISTINCT politician FROM trades WHERE party = '' OR party IS NULL LIMIT 50"
    ).fetchall()
    conn.close()

    enriched = 0
    for (politician,) in politicians:
        cid = _get_cid(politician)
        if not cid:
            continue

        data = _get("memPFDprofile", cid=cid, year=2023)
        if not data:
            continue

        attrs = (
            data.get("response", {})
            .get("member_profile", {})
            .get("@attributes", {})
        )
        party = attrs.get("party", "")
        state = attrs.get("state", "")

        if party or state:
            conn = get_conn()
            conn.execute(
                "UPDATE trades SET party = ?, state = ? WHERE politician = ? AND (party = '' OR party IS NULL)",
                (party, state, politician),
            )
            conn.commit()
            conn.close()
            enriched += 1

    log_fetch("opensecrets", enriched, "ok")
    return enriched


def fetch_legislator_assets() -> int:
    """Pull personal financial holdings (assets > $1k) from PFD for known politicians."""
    if not OPENSECRETS_KEY:
        return 0

    if not _CID_CACHE:
        _load_legislators()

    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pfd_assets (
            cid         TEXT NOT NULL,
            politician  TEXT NOT NULL,
            asset_name  TEXT,
            asset_type  TEXT,
            value_low   INTEGER,
            value_high  INTEGER,
            year        TEXT,
            source      TEXT DEFAULT 'opensecrets',
            PRIMARY KEY (cid, asset_name, year)
        );
    """)
    conn.commit()

    # get politicians we already track in our trades DB
    tracked = conn.execute("SELECT DISTINCT politician FROM trades").fetchall()
    conn.close()

    count = 0
    for (politician,) in tracked:
        cid = _get_cid(politician)
        if not cid:
            continue

        data = _get("memPFDprofile", cid=cid, year=2023)
        if not data:
            continue

        assets = (
            data.get("response", {})
            .get("member_profile", {})
            .get("assets", {})
            .get("asset", [])
        )
        if isinstance(assets, dict):
            assets = [assets]

        conn = get_conn()
        for asset in assets:
            a = asset.get("@attributes", {})
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO pfd_assets VALUES (?,?,?,?,?,?,?,'opensecrets')",
                    (
                        cid, politician,
                        a.get("asset_name", ""),
                        a.get("asset_type", ""),
                        int(a.get("value_low", 0) or 0),
                        int(a.get("value_high", 0) or 0),
                        "2023",
                    ),
                )
                count += 1
            except Exception:
                continue
        conn.commit()
        conn.close()

    log_fetch("opensecrets_pfd", count, "ok")
    return count
