from apscheduler.schedulers.background import BackgroundScheduler
from ingestion import house_watcher, senate_watcher, finnhub_client
from market.prices import fetch_prices
from config import POLL_INTERVAL
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def run_all():
    log.info("Fetching House trades...")
    n = house_watcher.fetch()
    log.info(f"  House: {n} trades")

    log.info("Fetching Senate trades...")
    n = senate_watcher.fetch()
    log.info(f"  Senate: {n} trades")

    log.info("Fetching Finnhub trades...")
    n = finnhub_client.fetch()
    log.info(f"  Finnhub: {n} trades")

    log.info("Fetching prices...")
    fetch_prices()
    log.info("  Prices updated")


def start() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_all, "interval", seconds=POLL_INTERVAL, id="poll_all")
    scheduler.start()
    log.info(f"Scheduler started — polling every {POLL_INTERVAL}s")
    return scheduler
