import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.5"}
BASE = "https://www.capitoltrades.com"

# Test different date ranges and page counts
params_tests = [
    {"pageSize": 96, "page": 10, "txDate": "90d"},
    {"pageSize": 96, "page": 1},   # no date filter
    {"pageSize": 96, "page": 5},
    {"pageSize": 96, "page": 10},
    {"pageSize": 96, "page": 20},
]

for params in params_tests:
    r = requests.get(f"{BASE}/trades", headers=HEADERS, params=params, timeout=15)
    soup = BeautifulSoup(r.text, "lxml")
    rows = soup.select("table#grid tr td:first-child")  # check if rows exist
    rows2 = soup.select("table tbody tr")
    label = str(params)
    print(f"{r.status_code} | rows={len(rows2)} | {label}")
    if rows2:
        # show first politician in this page
        cells = rows2[0].find_all("td")
        if len(cells) > 3:
            print(f"  First: {cells[0].get_text(separator='|', strip=True)[:60]} | date: {cells[3].get_text(strip=True)}")

# Check politician search page
print("\n--- Politician search page ---")
r2 = requests.get(f"{BASE}/politicians", headers=HEADERS, timeout=15)
soup2 = BeautifulSoup(r2.text, "lxml")
pol_links = soup2.select("a[href*='/politicians/']")
print(f"Politician links: {len(pol_links)}")
# search for specific names
names_to_find = ["pelosi", "mccaul", "fetterman", "green", "scott", "khanna"]
for name in names_to_find:
    matches = [a for a in pol_links if name.lower() in a.get_text(strip=True).lower() or name.lower() in a.get("href","").lower()]
    if matches:
        for m in matches[:2]:
            print(f"  FOUND {name}: {m.get('href')} | {m.get_text(strip=True)[:40]}")
    else:
        print(f"  NOT FOUND: {name}")
