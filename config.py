import os
from dotenv import load_dotenv

load_dotenv()

FINNHUB_API_KEY    = os.getenv("FINNHUB_API_KEY", "")
OPENSECRETS_KEY    = os.getenv("OPENSECRETS_KEY", "")
POLL_INTERVAL      = int(os.getenv("POLL_INTERVAL", 900))
DB_PATH            = "trades.db"

HOUSE_JSON_URL     = "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json"
SENATE_API_URL     = "https://senatestockwatcher.com/api"
CAPITOL_TRADES_URL = "https://www.capitoltrades.com/trades"
OPENSECRETS_URL    = "https://www.opensecrets.org/api/"
