import requests
import time
from database import get_conn, log_fetch
from config import CONGRESS_API_KEY

BASE = "https://api.congress.gov/v3"

# DEMO_KEY: 30 req/hour without registration
# Free registered key at api.data.gov: 1000 req/hour


def _get(path: str, **params) -> dict | None:
    try:
        resp = requests.get(
            f"{BASE}/{path}",
            params={"api_key": CONGRESS_API_KEY, "format": "json", **params},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def load_all_members() -> list[dict]:
    """Fetch all current members from Congress.gov with pagination."""
    members = []
    offset = 0
    limit = 250

    while True:
        data = _get("member", currentMember="true", limit=limit, offset=offset)
        if not data:
            break
        batch = data.get("members", [])
        if not batch:
            break
        members.extend(batch)
        total = data.get("pagination", {}).get("count", 0)
        offset += limit
        if offset >= total:
            break
        time.sleep(0.5)  # respect rate limit

    return members


def _normalize_party(raw: str) -> str:
    r = raw.lower()
    if "democrat" in r:
        return "D"
    if "republican" in r:
        return "R"
    if "independent" in r:
        return "I"
    return raw[:1].upper() if raw else ""


def _normalize_chamber(terms: list) -> str:
    if not terms:
        return ""
    last = terms[-1].get("chamber", "")
    return "senate" if "senate" in last.lower() else "house"


def build_member_index() -> dict[str, dict]:
    """Return {last_name_lower: {party, state, chamber, full_name}} for fuzzy matching."""
    members = load_all_members()
    index: dict[str, dict] = {}

    for m in members:
        name = m.get("name", "")          # format: "Last, First"
        party = _normalize_party(m.get("partyName", ""))
        state = m.get("state", "")
        terms = m.get("terms", {}).get("item", [])
        chamber = _normalize_chamber(terms)

        # store by last name and full name variants
        last = name.split(",")[0].strip().lower()
        first_last = ""
        if "," in name:
            parts = name.split(",", 1)
            first_last = f"{parts[1].strip()} {parts[0].strip()}".lower()

        entry = {"party": party, "state": state, "chamber": chamber, "full_name": name}
        index[last] = entry
        if first_last:
            index[first_last] = entry

    return index


_MEMBER_INDEX: dict[str, dict] = {}


def _get_index() -> dict[str, dict]:
    global _MEMBER_INDEX
    if not _MEMBER_INDEX:
        _MEMBER_INDEX = build_member_index()
    return _MEMBER_INDEX


def lookup(politician: str) -> dict | None:
    """Fuzzy lookup: return {party, state, chamber} for a politician name string."""
    idx = _get_index()
    key = politician.lower().strip()

    if key in idx:
        return idx[key]

    # try last name only
    last = key.split()[-1] if key else ""
    if last in idx:
        return idx[last]

    # try first word of name (some names stored as "First Last")
    first = key.split()[0] if key else ""
    for stored_key, val in idx.items():
        if last and last in stored_key:
            return val

    return None


def enrich_trades() -> int:
    """Update party/state/chamber for trades that are missing this info."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT politician FROM trades WHERE party = '' OR party IS NULL"
    ).fetchall()
    conn.close()

    enriched = 0
    for (politician,) in rows:
        info = lookup(politician)
        if not info:
            continue

        conn = get_conn()
        conn.execute(
            "UPDATE trades SET party = ?, state = ? WHERE politician = ? AND (party = '' OR party IS NULL)",
            (info["party"], info["state"], politician),
        )
        conn.commit()
        conn.close()
        enriched += 1

    log_fetch("congress_api", enriched, "ok")
    return enriched
