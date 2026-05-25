from apscheduler.schedulers.background import BackgroundScheduler
from ingestion import house_watcher, senate_watcher, finnhub_client
from ingestion import capitol_trades_scraper, opensecrets_client
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

    log.info("── OpenSecrets — enrichissement parti/état ──")
    log.info(f"  {opensecrets_client.enrich_with_pfd()} enrichis")

    log.info("── Prix Yahoo Finance ──")
    fetch_prices()
    log.info("  Prices updated")


def run_pfd_once():
    """Heavy job: fetch PFD asset holdings — run once per day."""
    log.info("── OpenSecrets — PFD assets ──")
    log.info(f"  {opensecrets_client.fetch_legislator_assets()} assets")


def start() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_all, "interval", seconds=POLL_INTERVAL, id="poll_all")
    # PFD assets: once a day at 06:00
    scheduler.add_job(run_pfd_once, "cron", hour=6, minute=0, id="pfd_daily")
    scheduler.start()
    log.info(f"Scheduler started — polling every {POLL_INTERVAL}s")
    return scheduler
