from apscheduler.schedulers.background import BackgroundScheduler
from ingestion import house_watcher, senate_watcher, finnhub_client
from ingestion import capitol_trades_scraper, congress_api_client
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

    log.info("── Capitol Trades (scraper) ──")
    log.info(f"  {capitol_trades_scraper.fetch(pages=3)} trades")

    log.info("── Finnhub ──")
    log.info(f"  {finnhub_client.fetch()} trades")

    log.info("── Congress.gov — enrichissement parti/état ──")
    log.info(f"  {congress_api_client.enrich_trades()} enrichis")

    log.info("── Prix Yahoo Finance ──")
    fetch_prices()
    log.info("  Prices updated")


def run_pfd_once():
    """Rebuild Congress member index once a day."""
    log.info("── Congress.gov — rebuild member index ──")
    congress_api_client._MEMBER_INDEX = congress_api_client.build_member_index()
    log.info(f"  {len(congress_api_client._MEMBER_INDEX)} members indexed")


def start() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_all, "interval", seconds=POLL_INTERVAL, id="poll_all")
    # PFD assets: once a day at 06:00
    scheduler.add_job(run_pfd_once, "cron", hour=6, minute=0, id="pfd_daily")
    scheduler.start()
    log.info(f"Scheduler started — polling every {POLL_INTERVAL}s")
    return scheduler
