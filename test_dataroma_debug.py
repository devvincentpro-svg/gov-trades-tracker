import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.dataroma.com/",
}

r = requests.get("https://www.dataroma.com/m/holdings.php?m=BRK", headers=HEADERS, timeout=15)
print(f"Status: {r.status_code}, size: {len(r.content)}")

soup = BeautifulSoup(r.text, "lxml")

# Find all tables
tables = soup.find_all("table")
print(f"Tables: {len(tables)}")
for i, t in enumerate(tables[:3]):
    rows = t.find_all("tr")
    print(f"  Table {i}: id={t.get('id')} class={t.get('class')} rows={len(rows)}")
    for row in rows[:3]:
        cells = row.find_all(["td","th"])
        print(f"    cells={len(cells)}: {[c.get_text(strip=True)[:20] for c in cells[:6]]}")
