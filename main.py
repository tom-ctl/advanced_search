import logging
import os
import random
import time
from pathlib import Path
from typing import List, Optional

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from scraper import scrape_autoscout, scrape_leboncoin
from utils.database import Database
from utils.filters import DEBUG, is_valid_ad
from utils.models import Ad
from utils.notifier import TelegramNotifier
from utils.pricing import score_ad

LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"
DEFAULT_SLEEP_SECONDS = 7200
SLEEP_VARIANCE_SECONDS = 600
MIN_REQUEST_DELAY_SECONDS = 2
MAX_REQUEST_DELAY_SECONDS = 5


def load_project_env() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(dotenv_path=env_path, override=False)
    logging.debug("Environment loaded from %s", env_path)


def configure_logging() -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, log_level, logging.INFO)
    logging.basicConfig(level=level, format=LOG_FORMAT)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.debug("Logging configured at %s level", logging.getLevelName(level))


def create_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
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


def create_notifier() -> Optional[TelegramNotifier]:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        logging.warning("Telegram notifier disabled because TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing")
        return None

    logging.info("Telegram notifier enabled")
    return TelegramNotifier(bot_token=bot_token, chat_id=chat_id)


def print_ad(ad: Ad) -> None:
    print("Title:", ad.title)
    print("Price:", f"{ad.price:,} EUR" if ad.price is not None else "N/A")
    print("Mileage:", f"{ad.mileage:,} km" if ad.mileage is not None else "N/A")
    print("Link:", ad.link)
    print("Source:", ad.source)
    print("-")


def format_telegram_message(ad: Ad) -> str:
    label = ad.label or "OK"
    price = f"{ad.price:,} EUR" if ad.price is not None else "N/A"
    mileage = f"{ad.mileage:,} km" if ad.mileage is not None else "N/A"
    score = f"{ad.score:.3f}" if ad.score is not None else "N/A"
    market_price = f"{ad.market_price:,} EUR" if ad.market_price is not None else "N/A"
    return (
        f"{label}\n"
        f"{ad.title}\n"
        f"Prix: {price}\n"
        f"Kilometrage: {mileage}\n"
        f"Prix marche estime: {market_price}\n"
        f"Score: {score}\n"
        f"Source: {ad.source}\n"
        f"{ad.link}"
    )


def run_cycle(session: requests.Session, db: Database, notifier: Optional[TelegramNotifier]) -> None:
    logging.info("Starting full scan cycle")
    scraper_functions = [
        ("AutoScout24", scrape_autoscout),
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

    print(f"TOTAL SCRAPED: {len(all_ads)}")

    valid_ads: List[Ad] = []
    for ad in all_ads:
        valid, reason = is_valid_ad(ad.title, ad.description, ad.price, ad.mileage)
        if not valid:
            if DEBUG:
                print(f"[REJECTED - {reason}] {ad.title} | {ad.price}EUR | {ad.mileage}km | {ad.source}")
            continue

        if ad.price is not None and ad.mileage is not None:
            market_price, score, label = score_ad(ad.price, ad.mileage)
            ad.market_price = market_price
            ad.score = score
            ad.label = label

        if DEBUG:
            print(f"[ACCEPTED] {ad.title} | {ad.price}EUR | {ad.mileage}km | {ad.source}")
        valid_ads.append(ad)

    print(f"VALID ADS: {len(valid_ads)}")

    processed_ids: set[str] = set()
    for ad in valid_ads:
        if ad.ad_id in processed_ids:
            logging.debug("Duplicate ad within cycle %s:%s", ad.source, ad.ad_id)
            continue

        processed_ids.add(ad.ad_id)
        storage_id = f"{ad.source}:{ad.ad_id}"
        should_notify, reason = db.should_notify(ad, storage_id)
        if not should_notify:
            if DEBUG:
                print(f"[SKIPPED - {reason}] {storage_id} | current_price={ad.price}")
            db.upsert_ad(ad, storage_id, notified=False)
            continue

        print_ad(ad)
        if DEBUG:
            print(f"[NOTIFY - {reason}] {storage_id} | current_price={ad.price}")
        sent = False
        if notifier is not None:
            sent = notifier.send_message(format_telegram_message(ad))
            logging.info("Telegram send status for %s: %s", storage_id, sent)
        else:
            logging.warning("Telegram notifier unavailable, ad not sent for %s", storage_id)

        db.upsert_ad(ad, storage_id, notified=sent)

    logging.info("Scan cycle complete")


def main() -> None:
    configure_logging()
    load_project_env()
    db = Database("car_alerts.db")
    session = create_session()
    notifier = create_notifier()

    while True:
        try:
            run_cycle(session, db, notifier)
        except Exception:
            logging.exception("Unexpected error during scan cycle")

        delay = DEFAULT_SLEEP_SECONDS + random.uniform(-SLEEP_VARIANCE_SECONDS, SLEEP_VARIANCE_SECONDS)
        logging.info("Sleeping for %.0f seconds before next loop", delay)
        time.sleep(delay)


if __name__ == "__main__":
    main()
