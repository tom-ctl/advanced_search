import logging
import os
import random
import time
from typing import List

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from scraper.autoscout import scrape_autoscout
from scraper.leboncoin import scrape_leboncoin
from scraper.mobilede import scrape_mobilede
from utils.database import Database
from utils.filters import is_valid_ad
from utils.notifier import TelegramNotifier
from utils.pricing import score_ad
from utils.models import Ad

LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"
DEFAULT_SLEEP_SECONDS = 7200
SLEEP_VARIANCE_SECONDS = 600
MIN_SCRAPER_DELAY_SECONDS = 12
MAX_SCRAPER_DELAY_SECONDS = 20


def configure_logging() -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, log_level, logging.INFO)
    logging.basicConfig(level=level, format=LOG_FORMAT)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.debug("Logging configured at %s level", logging.getLevelName(level))


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }
    )
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\"", "&quot;")
        .replace("'", "&#39;")
    )


def format_message(ad: Ad) -> str:
    title = escape_html(ad.title)
    link = escape_html(ad.link)
    price = f"{ad.price:,}" if ad.price is not None else "n/a"
    mileage = f"{ad.mileage:,}" if ad.mileage is not None else "n/a"
    label = ad.label or "OK"
    return (
        f"🚗 {label}\n\n"
        f"{title}\n\n"
        f"💰 {price} €\n"
        f"📏 {mileage} km\n\n"
        f"🔗 {link}"
    )


def _log_filter_reason(ad: Ad) -> None:
    if ad.price is None:
        logging.debug("Filtered out ad %s because price is missing: %s", ad.ad_id, ad.link)
        return
    if ad.mileage is None:
        logging.debug("Filtered out ad %s because mileage is missing: %s", ad.ad_id, ad.link)
        return
    if not is_valid_ad(ad):
        logging.debug(
            "Filtered out ad %s because it does not meet rules (price=%s, mileage=%s): %s",
            ad.ad_id,
            ad.price,
            ad.mileage,
            ad.link,
        )
        return


def run_cycle(session: requests.Session, db: Database, notifier: TelegramNotifier) -> None:
    logging.info("Starting scrape cycle")

    all_ads: List[Ad] = []
    scrapers = [
        ("AutoScout24", scrape_autoscout),
        ("Mobile.de", scrape_mobilede),
        ("Leboncoin", scrape_leboncoin),
    ]

    for source_name, scraper in scrapers:
        try:
            logging.info("Scraping %s", source_name)
            ads = scraper(session)
            logging.info("Found %d ads on %s", len(ads), source_name)
            all_ads.extend(ads)
            time.sleep(random.uniform(MIN_SCRAPER_DELAY_SECONDS, MAX_SCRAPER_DELAY_SECONDS))
        except Exception as exc:
            logging.exception("Failed to scrape %s: %s", source_name, exc)

    logging.info("Total ads collected: %d", len(all_ads))

    for ad in all_ads:
        if not is_valid_ad(ad) or ad.price is None or ad.mileage is None:
            _log_filter_reason(ad)
            continue

        ad.market_price, ad.score, ad.label = score_ad(ad.price, ad.mileage)
        storage_id = f"{ad.source}:{ad.ad_id}"

        if db.has_seen(storage_id):
            logging.debug("Already notified ad %s", storage_id)
            continue

        message = format_message(ad)
        if notifier.send_message(message):
            db.mark_seen(ad, storage_id)
            logging.info("Notified %s: %s", storage_id, ad.label)
        else:
            logging.warning("Skipping DB save because notification failed for %s", storage_id)


def main() -> None:
    configure_logging()

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        logging.error(
            "Environment variables TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set"
        )
        return

    db = Database("car_alerts.db")
    notifier = TelegramNotifier(bot_token, chat_id)
    session = create_session()

    while True:
        try:
            run_cycle(session, db, notifier)
        except Exception:
            logging.exception("Unexpected error in the main loop")
        delay = DEFAULT_SLEEP_SECONDS + random.uniform(-SLEEP_VARIANCE_SECONDS, SLEEP_VARIANCE_SECONDS)
        logging.info("Sleeping for %.0f seconds before the next cycle", delay)
        time.sleep(delay)


if __name__ == "__main__":
    main()
