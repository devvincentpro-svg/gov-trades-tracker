import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}

# Detailed column structure for politician page + check pagination
r = requests.get("https://www.capitoltrades.com/politicians/P000197", headers=HEADERS, timeout=15)
soup = BeautifulSoup(r.text, "lxml")

# politician info
h1 = soup.find("h1") or soup.find("h2")
print("Politician:", h1.get_text(strip=True) if h1 else "unknown")

rows = soup.select("table tbody tr")
print(f"Rows: {len(rows)}")
if rows:
    # header
    headers = soup.select("table thead th")
    print("Headers:", [h.get_text(strip=True) for h in headers])
    # first 3 rows
    for row in rows[:3]:
        cells = row.find_all("td")
        for i, c in enumerate(cells):
            links = c.find_all("a")
            ticker = next((l.get_text(strip=True) for l in links if l.get("href","").startswith("/issuers")), "")
            print(f"  [{i}] text={c.get_text(separator='|', strip=True)[:40]} ticker={ticker}")
        print()

# check pagination
pag = soup.select("[class*='pagination'], [class*='Pagination'], nav")
print(f"Pagination elements: {len(pag)}")
page2 = requests.get("https://www.capitoltrades.com/politicians/P000197?page=2", headers=HEADERS, timeout=15)
soup2 = BeautifulSoup(page2.text, "lxml")
rows2 = soup2.select("table tbody tr")
print(f"Page 2 rows: {len(rows2)}")

# Check how many pages Pelosi has total
# look for total count
count_el = soup.find(string=lambda t: t and "trade" in t.lower() and any(c.isdigit() for c in (t or "")))
print(f"Count element: {count_el}")
