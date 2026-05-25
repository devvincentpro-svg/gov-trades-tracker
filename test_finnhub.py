from dotenv import load_dotenv
load_dotenv()

from ingestion.finnhub_client import enrich_tickers
from database import init_db, get_conn

init_db()
print("Enriching tickers with Finnhub sector data...")
n = enrich_tickers()
print(f"Enriched: {n} tickers")

conn = get_conn()
total = conn.execute("SELECT COUNT(*) FROM ticker_info").fetchone()[0]
sample = conn.execute(
    "SELECT ticker, name, sector, country, market_cap FROM ticker_info LIMIT 10"
).fetchall()
conn.close()

print(f"Total in ticker_info: {total}")
print("Sample:")
for row in sample:
    print(" ", row)
