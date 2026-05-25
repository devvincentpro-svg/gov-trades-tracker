from apscheduler.schedulers.background import BackgroundScheduler
from ingestion import house_watcher, senate_watcher, finnhub_client
from ingestion import capitol_trades_scraper, congress_api_client, dataroma_scraper, sec_edgar_13f
from ingestion.capitol_trades_by_politician import fetch_watchlist

WATCHLIST = [
    {"bioguide": "P000197", "name": "Nancy Pelosi",    "party": "D", "state": "California",   "chamber": "house"},
    {"bioguide": "M001157", "name": "Michael McCaul",  "party": "R", "state": "Texas",         "chamber": "house"},
    {"bioguide": "K000389", "name": "Ro Khanna",       "party": "D", "state": "California",   "chamber": "house"},
    {"bioguide": "G000590", "name": "Mark Green",      "party": "R", "state": "Tennessee",    "chamber": "house"},
    {"bioguide": "F000479", "name": "John Fetterman",  "party": "D", "state": "Pennsylvania", "chamber": "senate"},
    {"bioguide": "S001189", "name": "Austin Scott",    "party": "R", "state": "Georgia",      "chamber": "house"},
    {"bioguide": "S001150", "name": "Adam Schiff",     "party": "D", "state": "California",   "chamber": "senate"},
]
from market.prices import fetch_prices
from config import POLL_INTERVAL
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def run_all():
    log.info("── House Stock Watcher ──")
    log.info(f"  {house_watcher.fetch()} trades")

    log.info("── Senate Stock Watcher ──")
    log.info(f"  {senate_watcher.fetch()} trades")

    log.info("── Capitol Trades (scraper général) ──")
    log.info(f"  {capitol_trades_scraper.fetch(pages=3)} trades")

    log.info("── Capitol Trades (watchlist par politicien) ──")
    log.info(f"  {fetch_watchlist(WATCHLIST, max_pages=5)} trades")

    log.info("── Finnhub ──")
    log.info(f"  {finnhub_client.fetch()} trades")

    log.info("── Congress.gov — enrichissement parti/état ──")
    log.info(f"  {congress_api_client.enrich_trades()} enrichis")

    log.info("── Prix Yahoo Finance ──")
    fetch_prices()
    log.info("  Prices updated")


def run_pfd_once():
    """Heavy jobs: rebuild Congress index + refresh super investor holdings."""
    log.info("── Congress.gov — rebuild member index ──")
    congress_api_client._MEMBER_INDEX = congress_api_client.build_member_index()
    log.info(f"  {len(congress_api_client._MEMBER_INDEX)} members indexed")

    log.info("── SEC EDGAR — 13F super investor holdings ──")
    log.info(f"  {sec_edgar_13f.fetch()} holdings")

    log.info("── Dataroma — super investor holdings ──")
    log.info(f"  {dataroma_scraper.fetch(max_managers=30)} holdings")


def start() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_all, "interval", seconds=POLL_INTERVAL, id="poll_all")
    # PFD assets: once a day at 06:00
    scheduler.add_job(run_pfd_once, "cron", hour=6, minute=0, id="pfd_daily")
    scheduler.start()
    log.info(f"Scheduler started — polling every {POLL_INTERVAL}s")
    return scheduler
