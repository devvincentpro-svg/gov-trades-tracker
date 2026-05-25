"""
Match top active traders from Capitol Trades to Congress.gov bioguide IDs,
then fetch their full trading history.
"""
from dotenv import load_dotenv
load_dotenv()

import requests, time
from database import init_db, get_conn
from ingestion.capitol_trades_by_politician import fetch_politician
from config import CONGRESS_API_KEY

BASE_CONGRESS = "https://api.congress.gov/v3"

# Top traders identified from scan
TOP_TRADERS = [
    "Ro Khanna", "Michael McCaul", "Gil Cisneros", "Richard Blumenthal",
    "Scott Peters", "Jared Moskowitz", "Mark Warner", "Josh Gottheimer",
    "Diana Harshbarger", "Maria Elvira Salazar", "April McClain Delaney",
    "Rich McCormick", "John Boozman", "Byron Donalds", "Thomas Kean Jr",
    "Brian Babin", "Lizzie Fletcher", "Rick Larsen", "Chuck Fleischmann",
    "Dave McCormick", "Lori Trahan", "Bill Keating", "Lloyd Smucker",
    "August Pfluger", "Lloyd Doggett", "David Taylor", "Tim Moore",
    "Dwight Evans", "John Fetterman",
]

# Hardcoded fallback bioguide IDs (from Congress.gov) for known traders
KNOWN_BIOGUIDES = {
    "Ro Khanna":              ("K000389", "D", "California",    "house"),
    "Michael McCaul":         ("M001157", "R", "Texas",         "house"),
    "Richard Blumenthal":     ("B001277", "D", "Connecticut",   "senate"),
    "Scott Peters":           ("P000608", "D", "California",    "house"),
    "Jared Moskowitz":        ("M001219", "D", "Florida",       "house"),
    "Mark Warner":            ("W000805", "D", "Virginia",      "senate"),
    "Josh Gottheimer":        ("G000583", "D", "New Jersey",    "house"),
    "Diana Harshbarger":      ("H001085", "R", "Tennessee",     "house"),
    "Maria Elvira Salazar":   ("S001235", "R", "Florida",       "house"),
    "April McClain Delaney":  ("D000631", "D", "Maryland",      "house"),
    "Rich McCormick":         ("M001228", "R", "Georgia",       "house"),
    "John Boozman":           ("B001236", "R", "Arkansas",      "senate"),
    "Byron Donalds":          ("D000625", "R", "Florida",       "house"),
    "Thomas Kean Jr":         ("K000397", "R", "New Jersey",    "house"),
    "Brian Babin":            ("B000755", "R", "Texas",         "house"),
    "Lizzie Fletcher":        ("F000462", "D", "Texas",         "house"),
    "Rick Larsen":            ("L000560", "D", "Washington",    "house"),
    "Chuck Fleischmann":      ("F000459", "R", "Tennessee",     "house"),
    "Dave McCormick":         ("M001230", "R", "Pennsylvania",  "senate"),
    "Lori Trahan":            ("T000465", "D", "Massachusetts", "house"),
    "Bill Keating":           ("K000375", "D", "Massachusetts", "house"),
    "Lloyd Smucker":          ("S001199", "R", "Pennsylvania",  "house"),
    "August Pfluger":         ("P000599", "R", "Texas",         "house"),
    "Lloyd Doggett":          ("D000399", "D", "Texas",         "house"),
    "Tim Moore":              ("M001232", "R", "North Carolina","house"),
    "Dwight Evans":           ("E000296", "D", "Pennsylvania",  "house"),
    "John Fetterman":         ("F000479", "D", "Pennsylvania",  "senate"),
    # Gil Cisneros and David Taylor left Congress — Capitol Trades still has their history
    "Gil Cisneros":           ("C001114", "D", "California",    "house"),
    "David Taylor":           ("T000479", "R", "Pennsylvania",  "house"),
}


def build_member_index() -> dict:
    """Fetch all current Congress members and index by last name."""
    index = {}
    for offset in range(0, 800, 250):
        r = requests.get(
            f"{BASE_CONGRESS}/member",
            params={"api_key": CONGRESS_API_KEY, "format": "json",
                    "limit": 250, "offset": offset, "currentMember": "true"},
            timeout=15,
        )
        if r.status_code != 200:
            print(f"  API error at offset {offset}: {r.status_code}")
            break
        members = r.json().get("members", [])
        if not members:
            break
        for m in members:
            name_raw = m.get("name", "")
            if "," in name_raw:
                last = name_raw.split(",")[0].strip().lower()
                index.setdefault(last, []).append(m)
        print(f"  Fetched {offset + len(members)} members...")
        time.sleep(0.5)
    return index


def find_member(name: str, index: dict) -> dict | None:
    parts = name.lower().split()
    last = parts[-1]
    first = parts[0]
    candidates = index.get(last, [])
    for m in candidates:
        mname = m.get("name", "").lower()
        if first in mname:
            return m
    # Try partial last name match (e.g. "Kean Jr" → "kean")
    if len(parts) >= 2:
        last2 = parts[-2].lower()
        candidates2 = index.get(last2, [])
        for m in candidates2:
            mname = m.get("name", "").lower()
            if first in mname:
                return m
    return None


def normalize_party(raw: str) -> str:
    r = raw.lower()
    if "democrat" in r:
        return "D"
    if "republican" in r:
        return "R"
    return "I"


def normalize_chamber(terms) -> str:
    if not terms:
        return "house"
    last_term = terms[-1] if isinstance(terms, list) else terms.get("item", [{}])[-1]
    return "senate" if "senate" in last_term.get("chamber", "").lower() else "house"


init_db()

print("Fetching Congress member index...")
member_index = build_member_index()
print(f"Indexed {sum(len(v) for v in member_index.values())} current members\n")

print("Resolving bioguide IDs...")
resolved = []
for name in TOP_TRADERS:
    # First try live API lookup
    m = find_member(name, member_index)
    if m:
        bio = m.get("bioguideId", "")
        party = normalize_party(m.get("partyName", ""))
        state = m.get("state", "")
        terms = m.get("terms", {}).get("item", [])
        chamber = normalize_chamber(terms)
        resolved.append({"name": name, "bioguide": bio, "party": party, "state": state, "chamber": chamber})
        print(f"  API {name:35s} -> {bio} ({party}, {state}, {chamber})")
    elif name in KNOWN_BIOGUIDES:
        bio, party, state, chamber = KNOWN_BIOGUIDES[name]
        resolved.append({"name": name, "bioguide": bio, "party": party, "state": state, "chamber": chamber})
        print(f"  HDC {name:35s} -> {bio} ({party}, {state}, {chamber})")
    else:
        print(f"  --- NOT FOUND: {name}")

print(f"\nResolved {len(resolved)}/{len(TOP_TRADERS)} politicians")
print("\nFetching trading history from Capitol Trades...")

total = 0
for pol in resolved:
    if not pol["bioguide"]:
        continue
    n = fetch_politician(
        pol["bioguide"], pol["name"], pol["party"], pol["state"], pol["chamber"],
        max_pages=15
    )
    print(f"  {pol['name']:35s}: {n:4d} trades")
    total += n
    time.sleep(0.3)

print(f"\nTotal new trades ingested: {total}")

conn = get_conn()
total_db = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
unique_pols = conn.execute("SELECT COUNT(DISTINCT politician) FROM trades").fetchone()[0]
top10 = conn.execute("""
    SELECT politician, party, chamber, COUNT(*) as cnt,
           SUM((COALESCE(amount_low,0)+COALESCE(amount_high,0))/2) as vol
    FROM trades GROUP BY politician ORDER BY cnt DESC LIMIT 10
""").fetchall()
conn.close()

print(f"\nDB summary: {total_db} trades | {unique_pols} politicians")
print("\nTop 10 by trade count:")
for row in top10:
    print(f"  {row[0]:35s} {row[1]:2s} {row[2]:7s} {row[3]:4d} trades  ${row[4]:>12,} vol")
