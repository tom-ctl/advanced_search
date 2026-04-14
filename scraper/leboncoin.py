import logging
import random
import time
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from utils.filters import MAX_MILEAGE, MAX_PRICE, SEARCH_KEYWORDS, parse_mileage, parse_price
from utils.models import Ad

DEBUG = True
SESSION_PATH = Path("session.json")
DEBUG_HTML_PATH = Path("debug.html")
DEBUG_SCREENSHOT_PATH = Path("debug.png")
MAX_PAGES = 5
MAX_KEYWORDS_PER_RUN = 5
LAST_STATUS = {"status": "idle", "count": 0, "message": ""}
ACTION_BREAK_MIN_SECONDS = 2
ACTION_BREAK_MAX_SECONDS = 5
PAGE_LOAD_MIN_SECONDS = 5
PAGE_LOAD_MAX_SECONDS = 12
KEYWORD_BREAK_MIN_SECONDS = 15
KEYWORD_BREAK_MAX_SECONDS = 40
ERROR_BREAK_MIN_SECONDS = 30
ERROR_BREAK_MAX_SECONDS = 60
LONG_BREAK_MIN_SECONDS = 120
LONG_BREAK_MAX_SECONDS = 300
SOFT_BAN_BREAK_MIN_SECONDS = 600
SOFT_BAN_BREAK_MAX_SECONDS = 1800
IDLE_BREAK_MIN_SECONDS = 10
IDLE_BREAK_MAX_SECONDS = 30
REALISTIC_NAVIGATION_TIMEOUT_MS = 60000

_ua = None


def _set_status(status: str, count: int = 0, message: str = "") -> None:
    LAST_STATUS["status"] = status
    LAST_STATUS["count"] = count
    LAST_STATUS["message"] = message


def human_delay(a: float = 2, b: float = 6) -> None:
    time.sleep(random.uniform(a, b))


def _get_user_agent_factory():
    global _ua
    if _ua is None:
        from fake_useragent import UserAgent

        _ua = UserAgent()
    return _ua


def get_random_user_agent() -> str:
    return _get_user_agent_factory().random


def _build_search_url(keyword: str, page: int) -> str:
    return (
        "https://www.leboncoin.fr/recherche"
        f"?category=2&text={quote_plus(keyword)}&price=max{MAX_PRICE}&mileage=max{MAX_MILEAGE}&page={page}"
    )


def _extract_text(element) -> str:
    return element.get_text(" ", strip=True) if element else ""


def _extract_browser_ad_id(link: str) -> str:
    parts = [part for part in link.rstrip("/").split("/") if part]
    return parts[-1] if parts else link


def _dump_debug_artifacts(page) -> None:
    if not DEBUG:
        return

    try:
        page.screenshot(path=str(DEBUG_SCREENSHOT_PATH), full_page=True)
    except Exception as exc:
        logging.warning("Leboncoin debug screenshot failed: %s", exc)

    try:
        DEBUG_HTML_PATH.write_text(page.content(), encoding="utf-8")
    except Exception as exc:
        logging.warning("Leboncoin debug html dump failed: %s", exc)


def _idle_pause(reason: str, a: float = IDLE_BREAK_MIN_SECONDS, b: float = IDLE_BREAK_MAX_SECONDS) -> None:
    pause = random.uniform(a, b)
    logging.info("Leboncoin idle pause reason=%s duration=%.2fs", reason, pause)
    time.sleep(pause)


def _is_blocked(content: str) -> bool:
    lowered = content.lower()
    return "datadome" in lowered or "captcha" in lowered


def _is_soft_banned(content: str) -> bool:
    lowered = content.lower()
    return "accès temporairement restreint" in lowered or "acces temporairement restreint" in lowered


def simulate_human(page) -> None:
    for _ in range(random.randint(3, 6)):
        page.mouse.wheel(0, random.randint(200, 800))
        human_delay(0.5, 2)


def _slow_open_search(page, search_url: str) -> str:
    page.goto("https://www.leboncoin.fr", wait_until="domcontentloaded", timeout=REALISTIC_NAVIGATION_TIMEOUT_MS)
    human_delay(PAGE_LOAD_MIN_SECONDS, PAGE_LOAD_MAX_SECONDS)
    _idle_pause("homepage_settle", PAGE_LOAD_MIN_SECONDS, PAGE_LOAD_MAX_SECONDS)

    page.goto(search_url, wait_until="domcontentloaded", timeout=REALISTIC_NAVIGATION_TIMEOUT_MS)
    human_delay(PAGE_LOAD_MIN_SECONDS, PAGE_LOAD_MAX_SECONDS)
    simulate_human(page)
    _idle_pause("search_settle")
    content = page.content()
    _dump_debug_artifacts(page)
    return content


def _parse_browser_results(html: str) -> List[Ad]:
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select("article")
    parsed_ads: List[Ad] = []

    for item in items:
        link_tag = item.find("a", href=True)
        if not link_tag:
            continue

        link = link_tag["href"]
        if link.startswith("/"):
            link = "https://www.leboncoin.fr" + link

        title = (
            _extract_text(item.select_one("p[data-qa-id='aditem_title']"))
            or _extract_text(item.select_one("h2"))
            or _extract_text(link_tag)
        )
        if not title:
            continue

        text_blob = " ".join(item.stripped_strings)
        price = None
        for text in item.stripped_strings:
            if "€" not in text and "eur" not in text.lower():
                continue
            price = parse_price(text)
            if price is not None:
                break

        mileage = parse_mileage(text_blob)
        ad_id = _extract_browser_ad_id(link)
        if not ad_id:
            continue

        parsed_ads.append(
            Ad(
                source="Leboncoin",
                ad_id=ad_id,
                title=title,
                price=price,
                mileage=mileage,
                description=text_blob,
                link=link,
            )
        )

    return parsed_ads


def _selected_keywords() -> List[str]:
    return SEARCH_KEYWORDS[:MAX_KEYWORDS_PER_RUN]


def _maybe_long_pause(keyword_index: int, next_break_after: int) -> int:
    if keyword_index > 0 and keyword_index % next_break_after == 0:
        pause = random.uniform(LONG_BREAK_MIN_SECONDS, LONG_BREAK_MAX_SECONDS)
        logging.info("Leboncoin long human pause for %.2f seconds", pause)
        time.sleep(pause)
        return random.randint(3, 5)
    return next_break_after


def scrape_leboncoin(session) -> List[Ad]:
    del session

    _set_status("running", 0, "scan started")
    results: List[Ad] = []
    seen_ids: set[str] = set()
    next_break_after = random.randint(3, 5)

    try:
        from playwright.sync_api import sync_playwright
        from playwright_stealth import Stealth
    except ImportError as exc:
        _set_status("error", 0, f"dependencies missing: {exc}")
        logging.warning("Leboncoin Playwright dependencies missing: %s", exc)
        return results

    keywords = _selected_keywords()
    if not keywords:
        _set_status("empty", 0, "no keywords selected")
        logging.warning("Leboncoin has no keywords selected")
        return results

    logging.info("Leboncoin starting safe browser run with %s keywords", len(keywords))
    stealth = Stealth(
        navigator_languages_override=("fr-FR", "fr"),
        navigator_platform_override="Win32",
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=False,
            slow_mo=random.randint(150, 350),
        )

        context_kwargs = {
            "user_agent": get_random_user_agent(),
            "locale": "fr-FR",
            "viewport": {"width": 1280, "height": 800},
        }
        if SESSION_PATH.exists():
            context_kwargs["storage_state"] = str(SESSION_PATH)

        context = browser.new_context(**context_kwargs)
        stealth.apply_stealth_sync(context)
        page = context.new_page()
        stealth.apply_stealth_sync(page)

        try:
            for keyword_index, keyword in enumerate(keywords, start=1):
                next_break_after = _maybe_long_pause(keyword_index - 1, next_break_after)

                for page_number in range(1, MAX_PAGES + 1):
                    search_url = _build_search_url(keyword, page_number)
                    logging.info(
                        "Leboncoin safe navigation keyword=%s page=%s url=%s",
                        keyword,
                        page_number,
                        search_url,
                    )

                    try:
                        content = _slow_open_search(page, search_url)
                        context.storage_state(path=str(SESSION_PATH))
                    except Exception as exc:
                        print(f"Leboncoin error for keyword={keyword} page={page_number}: {exc}")
                        _set_status("error", len(results), f"{keyword} page {page_number}: {exc}")
                        logging.warning(
                            "Leboncoin navigation failed keyword=%s page=%s: %s",
                            keyword,
                            page_number,
                            exc,
                        )
                        pause = random.uniform(ERROR_BREAK_MIN_SECONDS, ERROR_BREAK_MAX_SECONDS)
                        logging.info("Leboncoin error cooldown for %.2f seconds", pause)
                        time.sleep(pause)
                        break

                    if _is_blocked(content):
                        print("WARNING: BLOCK DETECTED")
                        _set_status("blocked", len(results), f"captcha/datadome on {keyword} page {page_number}")
                        logging.warning(
                            "Leboncoin blocking detected, stopping scraping immediately keyword=%s page=%s",
                            keyword,
                            page_number,
                        )
                        return results

                    if _is_soft_banned(content):
                        print("WARNING: TEMPORARY RESTRICTED ACCESS DETECTED")
                        cooldown = random.uniform(SOFT_BAN_BREAK_MIN_SECONDS, SOFT_BAN_BREAK_MAX_SECONDS)
                        _set_status("soft_ban", len(results), f"temporary restricted access on {keyword} page {page_number}")
                        logging.warning(
                            "Leboncoin soft ban detected keyword=%s page=%s cooldown=%.2fs",
                            keyword,
                            page_number,
                            cooldown,
                        )
                        time.sleep(cooldown)
                        return results

                    parsed_ads = _parse_browser_results(content)
                    print(f"[LBC_PLAYWRIGHT] {keyword} page {page_number} -> {len(parsed_ads)} ads")
                    logging.info(
                        "Leboncoin parsed keyword=%s page=%s parsed=%s cumulative=%s",
                        keyword,
                        page_number,
                        len(parsed_ads),
                        len(results),
                    )

                    page_added = 0
                    for ad in parsed_ads:
                        if ad.ad_id in seen_ids:
                            continue
                        seen_ids.add(ad.ad_id)
                        results.append(ad)
                        page_added += 1

                    logging.info(
                        "Leboncoin accepted keyword=%s page=%s added=%s cumulative=%s",
                        keyword,
                        page_number,
                        page_added,
                        len(results),
                    )

                    _idle_pause("post_extract")
                    keyword_pause = random.uniform(KEYWORD_BREAK_MIN_SECONDS, KEYWORD_BREAK_MAX_SECONDS)
                    logging.info(
                        "Leboncoin human cooldown keyword=%s page=%s for %.2f seconds",
                        keyword,
                        page_number,
                        keyword_pause,
                    )
                    time.sleep(keyword_pause)

                    if not parsed_ads:
                        break
        finally:
            try:
                context.storage_state(path=str(SESSION_PATH))
            except Exception as exc:
                logging.warning("Leboncoin could not persist session state: %s", exc)
            context.close()
            browser.close()

    if results and LAST_STATUS["status"] == "running":
        _set_status("ok", len(results), "ads collected")
    elif not results and LAST_STATUS["status"] == "running":
        _set_status("empty", 0, "no ads collected")
    return results
