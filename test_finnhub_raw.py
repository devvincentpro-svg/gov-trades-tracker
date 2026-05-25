import requests
import json

KEY = "d8abo6hr01ql25r6tgrgd8abo6hr01ql25r6tgs0"

# Test 1: congressional trading (bulk)
r1 = requests.get(
    "https://finnhub.io/api/v1/stock/congressional-trading",
    params={"token": KEY},
    timeout=15,
)
print(f"Status: {r1.status_code}")
print(f"Response: {r1.text[:500]}")

# Test 2: with a specific symbol
r2 = requests.get(
    "https://finnhub.io/api/v1/stock/congressional-trading",
    params={"symbol": "AAPL", "token": KEY},
    timeout=15,
)
print(f"\nWith symbol AAPL — Status: {r2.status_code}")
print(f"Response: {r2.text[:500]}")
