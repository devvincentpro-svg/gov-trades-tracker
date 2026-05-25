import os
from dotenv import load_dotenv

load_dotenv()

FINNHUB_API_KEY        = os.getenv("FINNHUB_API_KEY", "")
CONGRESS_API_KEY       = os.getenv("CONGRESS_API_KEY", "DEMO_KEY")  # free at api.data.gov
TWITTER_BEARER_TOKEN   = os.getenv("TWITTER_BEARER_TOKEN", "")      # optional: developer.twitter.com
POLL_INTERVAL          = int(os.getenv("POLL_INTERVAL", 900))
DB_PATH            = "trades.db"

HOUSE_JSON_URL     = "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json"
SENATE_API_URL     = "https://senatestockwatcher.com/api"
CAPITOL_TRADES_URL = "https://www.capitoltrades.com/trades"
OPENSECRETS_URL    = "https://www.opensecrets.org/api/"
