import requests

# Congress.gov API - free DEMO_KEY allows 30 req/hour without registration
# Registered key (free at api.data.gov) allows 1000 req/hour

BASE = "https://api.congress.gov/v3"
KEY = "DEMO_KEY"

# Get current members (119th Congress)
r = requests.get(
    f"{BASE}/member",
    params={"api_key": KEY, "limit": 10, "format": "json", "currentMember": "true"},
    timeout=15,
)
print(f"Status: {r.status_code}")
if r.status_code == 200:
    data = r.json()
    members = data.get("members", [])
    print(f"Total members returned: {len(members)}")
    print(f"Total available: {data.get('pagination', {}).get('count', '?')}")
    for m in members[:3]:
        print({
            "name": m.get("name"),
            "party": m.get("partyName"),
            "state": m.get("state"),
            "chamber": [t.get("chamber") for t in m.get("terms", {}).get("item", [])[-1:]],
        })
else:
    print(r.text[:300])
