from dotenv import load_dotenv
load_dotenv()

from database import get_conn
from ingestion.congress_api_client import enrich_trades, build_member_index

print("Building Congress member index...")
idx = build_member_index()
print(f"  {len(idx)} entries indexed")

print("\nEnriching trades with party/state...")
n = enrich_trades()
print(f"  {n} politicians enriched")

conn = get_conn()
sample = conn.execute(
    "SELECT politician, chamber, party, state FROM trades WHERE party != '' LIMIT 8"
).fetchall()
missing = conn.execute(
    "SELECT COUNT(*) FROM trades WHERE party = '' OR party IS NULL"
).fetchone()[0]
total = conn.execute("SELECT COUNT(DISTINCT politician) FROM trades").fetchone()[0]
conn.close()

print(f"\nPoliticians with party data: {total - missing}/{total}")
print("Sample:")
for row in sample:
    print(" ", row)
