from dotenv import load_dotenv
load_dotenv()

from database import init_db, get_conn
from ingestion.capitol_trades_by_politician import fetch_watchlist

init_db()

# Politicians explicitly requested — bioguide IDs from Congress.gov
WATCHLIST = [
    {"bioguide": "P000197", "name": "Nancy Pelosi",    "party": "D", "state": "California",  "chamber": "house"},
    {"bioguide": "M001157", "name": "Michael McCaul",  "party": "R", "state": "Texas",        "chamber": "house"},
    {"bioguide": "K000389", "name": "Ro Khanna",       "party": "D", "state": "California",  "chamber": "house"},
    {"bioguide": "G000590", "name": "Mark Green",      "party": "R", "state": "Tennessee",   "chamber": "house"},
    {"bioguide": "F000479", "name": "John Fetterman",  "party": "D", "state": "Pennsylvania","chamber": "senate"},
    {"bioguide": "S001189", "name": "Austin Scott",    "party": "R", "state": "Georgia",     "chamber": "house"},
    # Possible matches for ambiguous names:
    {"bioguide": "J000294", "name": "Hakeem Jeffries", "party": "D", "state": "New York",    "chamber": "house"},
    {"bioguide": "S001150", "name": "Adam Schiff",     "party": "D", "state": "California",  "chamber": "senate"},
]

print(f"Fetching {len(WATCHLIST)} politicians from Capitol Trades...")
total = fetch_watchlist(WATCHLIST, max_pages=10)
print(f"Total trades ingested: {total}")

conn = get_conn()
for pol in WATCHLIST:
    name = pol["name"]
    count = conn.execute("SELECT COUNT(*) FROM trades WHERE politician = ?", (name,)).fetchone()[0]
    print(f"  {name:30s}: {count:3d} trades")
conn.close()
