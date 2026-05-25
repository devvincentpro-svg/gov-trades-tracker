"""Test X API connection and fetch sample tweets."""
import sys
sys.stdout.reconfigure(line_buffering=True)

from dotenv import load_dotenv
load_dotenv()

import os, requests

TOKEN = os.getenv("TWITTER_BEARER_TOKEN", "")
if not TOKEN:
    print("ERROR: TWITTER_BEARER_TOKEN not found in .env")
    sys.exit(1)

HEADERS = {"Authorization": f"Bearer {TOKEN}"}

print(f"Token loaded: {TOKEN[:20]}...")

# Test 1: connexion basique
print("\n[1] Test connexion API X...")
r = requests.get(
    "https://api.twitter.com/2/tweets/search/recent",
    params={"query": "$NVDA lang:en -is:retweet", "max_results": 10,
            "tweet.fields": "created_at,public_metrics"},
    headers=HEADERS, timeout=10
)
print(f"  Status: {r.status_code}")
if r.status_code == 200:
    data = r.json()
    tweets = data.get("data", [])
    meta = data.get("meta", {})
    print(f"  Tweets recus: {len(tweets)} (total dispo: {meta.get('result_count', '?')})")
    for t in tweets[:3]:
        m = t.get("public_metrics", {})
        print(f"  - [{t['created_at'][:10]}] likes:{m.get('like_count',0)} RT:{m.get('retweet_count',0)} | {t['text'][:80]}")
else:
    print(f"  Erreur: {r.text[:300]}")

# Test 2: volume de tweets (counts)
print("\n[2] Test volume tweets $AAPL (7 derniers jours)...")
r2 = requests.get(
    "https://api.twitter.com/2/tweets/counts/recent",
    params={"query": "$AAPL lang:en -is:retweet", "granularity": "day"},
    headers=HEADERS, timeout=10
)
print(f"  Status: {r2.status_code}")
if r2.status_code == 200:
    counts = r2.json().get("data", [])
    total = sum(d.get("tweet_count", 0) for d in counts)
    print(f"  Total tweets $AAPL cette semaine: {total:,}")
    for d in counts[-3:]:
        print(f"  - {d['start'][:10]}: {d['tweet_count']:,} tweets")
else:
    print(f"  Erreur: {r2.text[:300]}")

# Test 3: tweets d'un compte influent
print("\n[3] Recherche tweets journalistes financiers sur $NVDA...")
r3 = requests.get(
    "https://api.twitter.com/2/tweets/search/recent",
    params={"query": "$NVDA (from:reuters OR from:business OR from:WSJ) -is:retweet",
            "max_results": 5, "tweet.fields": "created_at,author_id"},
    headers=HEADERS, timeout=10
)
print(f"  Status: {r3.status_code}")
if r3.status_code == 200:
    tweets3 = r3.json().get("data", [])
    print(f"  {len(tweets3)} tweets trouves")
    for t in tweets3[:2]:
        print(f"  - {t['text'][:100]}")

print("\nConnexion X API: OK" if r.status_code == 200 else "\nConnexion X API: ECHEC")
