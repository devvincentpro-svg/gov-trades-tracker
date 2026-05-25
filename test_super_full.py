from dotenv import load_dotenv
load_dotenv()

from database import init_db, get_conn
from ingestion import sec_edgar_13f, dataroma_scraper
from analysis.cross_reference import get_shared_tickers, get_top_aligned_trades

init_db()

print("=" * 60)
print("SEC EDGAR — 15 super investors 13F")
print("=" * 60)
n_sec = sec_edgar_13f.fetch()
print(f"Holdings ingested: {n_sec}")

print("\n" + "=" * 60)
print("Dataroma — 30 super investors")
print("=" * 60)
n_dat = dataroma_scraper.fetch(max_managers=30)
print(f"Holdings ingested: {n_dat}")

conn = get_conn()
inv_count = conn.execute("SELECT COUNT(DISTINCT manager_id) FROM super_investors").fetchone()[0]
hold_count = conn.execute("SELECT COUNT(*) FROM super_holdings").fetchone()[0]
conn.close()

print(f"\nTotal super investors tracked: {inv_count}")
print(f"Total holdings in DB: {hold_count}")

print("\n" + "=" * 60)
print("CROSS-REFERENCE: Tickers held by politicians AND super investors")
print("=" * 60)
shared = get_shared_tickers()
print(f"Shared tickers found: {len(shared)}")
for s in shared[:15]:
    print(f"  {s['ticker']:8s}  {s['super_investors']:2d} super investors  {s['politicians']:2d} politicians  vol ${s['pol_volume']:>10,}")

print("\n" + "=" * 60)
print("TOP ALIGNED POLITICAL TRADES")
print("=" * 60)
top = get_top_aligned_trades(10)
for t in top:
    print(f"  {t['ticker']:6s}  {t['trade_type']:4s}  {t['politician']:30s}  score {t['alignment_score']:5.1f}%  top: {t['top_investor'][:30]}")
