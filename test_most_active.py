import requests
from bs4 import BeautifulSoup
from collections import defaultdict

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
BASE = "https://www.capitoltrades.com"

# Scrape many pages (no date filter = all time) and count trades per politician
trade_counts = defaultdict(lambda: {"count": 0, "party": "", "chamber": "", "state": ""})

print("Scanning Capitol Trades for most active politicians (20 pages)...")
for page in range(1, 21):
    r = requests.get(f"{BASE}/trades", headers=HEADERS, params={"pageSize": 96, "page": page}, timeout=15)
    soup = BeautifulSoup(r.text, "lxml")
    rows = soup.select("table tbody tr")
    if not rows:
        break
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 4:
            continue
        parts = [p.strip() for p in cells[0].get_text(separator="|").split("|") if p.strip()]
        if not parts:
            continue
        name = parts[0]
        party = parts[1] if len(parts) > 1 else ""
        chamber = "senate" if len(parts) > 2 and "senate" in parts[2].lower() else "house"
        state = parts[3] if len(parts) > 3 else ""
        trade_counts[name]["count"] += 1
        trade_counts[name]["party"] = party
        trade_counts[name]["chamber"] = chamber
        trade_counts[name]["state"] = state

# Also check Capitol Trades politicians page for leaderboard
r2 = requests.get(f"{BASE}/politicians?sortBy=trades&sortDir=desc", headers=HEADERS, timeout=15)
soup2 = BeautifulSoup(r2.text, "lxml")
rows2 = soup2.select("table tbody tr")
print(f"\nCapitol Trades politicians leaderboard: {len(rows2)} rows")
for row in rows2[:20]:
    cells = row.find_all("td")
    print(f"  {[c.get_text(strip=True)[:30] for c in cells[:5]]}")

print(f"\nTop 30 most active from page scan:")
sorted_pols = sorted(trade_counts.items(), key=lambda x: x[1]["count"], reverse=True)
for name, info in sorted_pols[:30]:
    print(f"  {name:35s} {info['party']:12s} {info['chamber']:7s} {info['state']:20s} {info['count']:4d} trades")
