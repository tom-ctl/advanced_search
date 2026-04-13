import logging
import os
import random
import time
from typing import List

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from scraper import scrape_autoscout, scrape_mobilede, scrape_leboncoin
from utils.database import Database
from utils.filters import is_valid_ad
from utils.models import Ad

LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"
DEFAULT_SLEEP_SECONDS = 7200
SLEEP_VARIANCE_SECONDS = 600
MIN_REQUEST_DELAY_SECONDS = 5
MAX_REQUEST_DELAY_SECONDS = 15
MIN_KEYWORD_DELAY_SECONDS = 30
MAX_KEYWORD_DELAY_SECONDS = 90


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
                "Chrome/124.0.0.0 Safari/537.36"
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


def print_ad(ad: Ad) -> None:
    print("Title:", ad.title)
    print("Price:", f"{ad.price:,} €")
    print("Mileage:", f"{ad.mileage:,} km")
    print("Link:", ad.link)
    print("Source:", ad.source)
    print("-")


def run_cycle(session: requests.Session, db: Database) -> None:
    logging.info("Starting full scan cycle")
    scraper_functions = [
        ("AutoScout24", scrape_autoscout),
        ("Mobile.de", scrape_mobilede),
        ("Leboncoin", scrape_leboncoin),
    ]
    all_ads: List[Ad] = []

    for source_name, scraper_func in scraper_functions:
        try:
            site_ads = scraper_func(session)
            logging.info("Collected %d ads from %s", len(site_ads), source_name)
            all_ads.extend(site_ads)
        except Exception as exc:
            logging.exception("Scraper %s failed: %s", source_name, exc)
        time.sleep(random.uniform(MIN_REQUEST_DELAY_SECONDS, MAX_REQUEST_DELAY_SECONDS))

    logging.info("Total ads collected before duplicate filter: %d", len(all_ads))
    processed_ids: set[str] = set()

    for ad in all_ads:
        if ad.ad_id in processed_ids:
            continue

        processed_ids.add(ad.ad_id)

        if not is_valid_ad(ad.title, ad.description, ad.price, ad.mileage):
            logging.debug("Filtered out ad %s from %s", ad.ad_id, ad.source)
            continue

        storage_id = f"{ad.source}:{ad.ad_id}"
        if db.has_seen(storage_id):
            logging.debug("Already processed ad %s", storage_id)
            continue

        print_ad(ad)
        db.mark_seen(ad, storage_id)

    logging.info("Scan cycle complete")


def main() -> None:
    configure_logging()
    db = Database("seen_ads.db")
    session = create_session()

    while True:
        try:
            run_cycle(session, db)
        except Exception:
            logging.exception("Unexpected error during scan cycle")

        delay = DEFAULT_SLEEP_SECONDS + random.uniform(-SLEEP_VARIANCE_SECONDS, SLEEP_VARIANCE_SECONDS)
        logging.info("Sleeping for %.0f seconds before next loop", delay)
        time.sleep(delay)


if __name__ == "__main__":
    main()
