"""One-shot: fetch news for top tickers + compute lead times."""
from dotenv import load_dotenv
load_dotenv()

from database import init_db, get_conn
from ingestion.news_fetcher import fetch_news_for_ticker
from analysis.news_correlation import compute_lead_times
import time

init_db()

conn = get_conn()
rows = conn.execute("""
    SELECT ticker, politician, COUNT(*) as cnt
    FROM trades WHERE ticker != ''
    GROUP BY ticker
    ORDER BY cnt DESC LIMIT 25
""").fetchall()
conn.close()

print(f"Fetching news for {len(rows)} top tickers...")
total = 0
for ticker, politician, cnt in rows:
    n = fetch_news_for_ticker(ticker, politician, days_back=60)
    print(f"  {ticker:8s} ({cnt:3d} trades)  -> {n:3d} new articles")
    total += n
    time.sleep(1.0)

print(f"\nTotal articles fetched: {total}")
print("Computing trade lead times...")
links = compute_lead_times(window_days=30)
print(f"News-trade links computed: {links}")

conn = get_conn()
news_count = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
links_count = conn.execute("SELECT COUNT(*) FROM news_trades").fetchone()[0]
ahead = conn.execute("SELECT COUNT(*) FROM news_trades WHERE lead_days > 3").fetchone()[0]
conn.close()
print(f"\nDB: {news_count} news articles | {links_count} trade-news links | {ahead} trades > 3 days ahead")
