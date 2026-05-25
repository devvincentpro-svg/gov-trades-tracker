from database import init_db, get_conn
from ingestion.capitol_trades_scraper import fetch

init_db()
print("Fetching Capitol Trades (5 pages x 96)...")
n = fetch(pages=5)
print(f"Ingested: {n} trades")

conn = get_conn()
total = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
chambers = conn.execute("SELECT chamber, COUNT(*) FROM trades GROUP BY chamber").fetchall()
tickers = conn.execute("SELECT COUNT(DISTINCT ticker) FROM trades WHERE ticker != ''").fetchone()[0]
sample = conn.execute(
    "SELECT politician, chamber, party, state, ticker, trade_type, trade_date, amount_low, amount_high FROM trades LIMIT 5"
).fetchall()
conn.close()

print(f"DB total: {total} trades")
print(f"Chambers: {chambers}")
print(f"Unique tickers: {tickers}")
print("Sample rows:")
for row in sample:
    print(" ", row)
