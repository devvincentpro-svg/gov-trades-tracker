import requests
from bs4 import BeautifulSoup
import json

r = requests.get(
    "https://www.capitoltrades.com/trades?pageSize=96&txDate=90d",
    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
    timeout=15,
)
soup = BeautifulSoup(r.text, "lxml")

tables = soup.find_all("table")
print(f"Tables found: {len(tables)}")

rows = soup.select("table tbody tr")
print(f"Table rows: {len(rows)}")

if rows:
    cells = rows[0].find_all("td")
    print(f"Cells in first row: {len(cells)}")
    for i, c in enumerate(cells):
        print(f"  [{i}] {c.get_text(separator='|', strip=True)[:80]}")
else:
    next_data = soup.find("script", id="__NEXT_DATA__")
    print("Next.js data found:", next_data is not None)
    if next_data:
        data = json.loads(next_data.string)
        props = data.get("props", {}).get("pageProps", {})
        print("pageProps keys:", list(props.keys())[:10])
        # try to find trades list
        for key in props:
            val = props[key]
            if isinstance(val, list) and len(val) > 0:
                print(f"  List '{key}': {len(val)} items, sample keys: {list(val[0].keys()) if isinstance(val[0], dict) else type(val[0])}")
    else:
        scripts = soup.find_all("script")
        print(f"Total scripts: {len(scripts)}")
        for s in scripts[:5]:
            txt = s.string or ""
            if "trade" in txt.lower() and len(txt) > 100:
                print("Possible trade script (first 300):", txt[:300])
                break
