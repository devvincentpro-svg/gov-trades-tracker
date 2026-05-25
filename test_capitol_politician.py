import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
BASE = "https://www.capitoltrades.com"

# Try politician-specific pages with known bioguide IDs from Congress.gov
# Nancy Pelosi: P000197, John Fetterman: F000479, Austin Scott: S001189, Mark Green: G000590
bioguides = {
    "Nancy Pelosi": "P000197",
    "John Fetterman": "F000479",
    "Austin Scott": "S001189",
    "Mark Green": "G000590",
    "Michael McCaul": "M001157",
    "Ro Khanna": "K000389",
}

for name, bio in bioguides.items():
    # Try different URL patterns
    for url in [
        f"{BASE}/politicians/{bio}",
        f"{BASE}/trades?politician={bio}",
        f"{BASE}/politicians/{bio.lower()}",
    ]:
        r = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        soup = BeautifulSoup(r.text, "lxml")
        rows = soup.select("table tbody tr")
        title = soup.find("title")
        print(f"{name} | {r.status_code} | rows={len(rows)} | url={url}")
        if rows:
            cells = rows[0].find_all("td")
            print(f"  First row cells: {len(cells)}: {[c.get_text(strip=True)[:20] for c in cells[:5]]}")
            break
        if r.status_code == 200 and "not found" not in (title.string or "").lower():
            print(f"  Title: {title.string if title else 'none'}")
            # look for any data
            links = soup.select("a[href*='trades']")[:3]
            print(f"  Trade links: {[l.get('href') for l in links]}")
            break
