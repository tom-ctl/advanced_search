import logging
import os
import time
from typing import Any, List, Optional
from urllib.parse import quote_plus

from bs4 import BeautifulSoup
from requests import Response, Session

from utils.filters import MAX_MILEAGE, MAX_PRICE, SEARCH_KEYWORDS, parse_mileage, parse_number, parse_price
from utils.models import Ad

API_URL = "https://api.leboncoin.fr/finder/search"
SEARCH_URL_TEMPLATE = (
    "https://www.leboncoin.fr/recherche?category=2"
    "&text={keyword}&price=max{max_price}&mileage=max{max_mileage}&page={page}"
)
MAX_PAGES = 5
PAGE_SIZE = 50


def _api_headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://www.leboncoin.fr",
        "Referer": "https://www.leboncoin.fr/",
    }


def _payload(keyword: str, offset: int) -> dict[str, Any]:
    return {
        "filters": {
            "category": {"id": "2"},
            "enums": {"ad_type": ["offer"]},
            "keywords": keyword,
            "ranges": {
                "price": {"max": MAX_PRICE},
                "mileage": {"max": MAX_MILEAGE},
            },
        },
        "limit": PAGE_SIZE,
        "offset": offset,
    }


def _extract_text(element: Optional[BeautifulSoup]) -> str:
    return element.get_text(" ", strip=True) if element else ""


def _extract_mileage(attributes: list[dict[str, Any]]) -> Optional[int]:
    for attr in attributes:
        if attr.get("key") != "vehicle_mileage":
            continue

        raw_value = str(attr.get("value") or attr.get("values") or "")
        mileage = parse_number(raw_value, max_value=MAX_MILEAGE)
        if mileage is not None:
            return mileage

    return None


def _extract_description(ad_data: dict[str, Any]) -> str:
    description = ad_data.get("body") or ad_data.get("description") or ""
    if description:
        return description

    parts: list[str] = []
    for attr in ad_data.get("attributes", []):
        value = attr.get("value_label") or attr.get("value") or ""
        if value:
            parts.append(str(value))
    return " ".join(parts)


def _extract_link(ad_data: dict[str, Any]) -> str:
    raw_url = ad_data.get("url") or ad_data.get("list_url") or ""
    if raw_url.startswith("/"):
        return "https://www.leboncoin.fr" + raw_url
    return raw_url


def _parse_api_ad(ad_data: dict[str, Any]) -> Optional[Ad]:
    title = (ad_data.get("subject") or "").strip()
    if not title:
        return None

    price = None
    raw_price = ad_data.get("price")
    if isinstance(raw_price, list) and raw_price:
        price = parse_price(str(raw_price[0]))
    elif raw_price is not None:
        price = parse_price(str(raw_price))

    mileage = _extract_mileage(ad_data.get("attributes", []))
    if mileage is None:
        mileage = parse_mileage(_extract_description(ad_data))

    link = _extract_link(ad_data)
    ad_id = str(ad_data.get("list_id") or ad_data.get("ad_id") or link)
    if not ad_id or not link:
        return None

    return Ad(
        source="Leboncoin",
        ad_id=ad_id,
        title=title,
        price=price,
        mileage=mileage,
        description=_extract_description(ad_data),
        link=link,
    )


def _build_search_url(keyword: str, page: int) -> str:
    return SEARCH_URL_TEMPLATE.format(
        keyword=quote_plus(keyword),
        max_price=MAX_PRICE,
        max_mileage=MAX_MILEAGE,
        page=page,
    )


def _extract_browser_ad_id(link: str) -> str:
    parts = [part for part in link.rstrip("/").split("/") if part]
    return parts[-1] if parts else link


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

        if not title or not ad_id:
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


def _is_datadome_blocked(response: Response) -> bool:
    if response.status_code != 403:
        return False
    if response.headers.get("x-datadome") == "protected":
        return True
    return "captcha-delivery.com" in response.text or "datadome" in response.text.lower()


def _load_browser_page(url: str) -> Optional[str]:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except ImportError:
        logging.exception("Selenium is not installed; cannot run Leboncoin browser fallback")
        return None

    chrome_path = os.getenv("LEBONCOIN_CHROME_BINARY", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    binary_location = chrome_path if os.path.exists(chrome_path) else edge_path if os.path.exists(edge_path) else None
    if not binary_location:
        logging.error("No Chrome/Edge binary found for Leboncoin browser fallback")
        return None

    wait_seconds = int(os.getenv("LEBONCOIN_BROWSER_WAIT_SECONDS", "10"))
    headless = os.getenv("LEBONCOIN_BROWSER_HEADLESS", "0") == "1"

    options = Options()
    options.binary_location = binary_location
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1400,1000")
    if headless:
        options.add_argument("--headless=new")

    logging.warning(
        "Leboncoin browser fallback starting url=%s binary=%s headless=%s",
        url,
        binary_location,
        headless,
    )

    driver = None
    try:
        driver = webdriver.Chrome(options=options)
        driver.get(url)
        time.sleep(wait_seconds)
        html = driver.page_source
        logging.info("Leboncoin browser fallback loaded %s characters", len(html))
        return html
    except Exception as exc:
        logging.exception("Leboncoin browser fallback failed for %s: %s", url, exc)
        return None
    finally:
        if driver is not None:
            driver.quit()


def _scrape_browser_fallback(keyword: str, page: int) -> List[Ad]:
    url = _build_search_url(keyword, page)
    html = _load_browser_page(url)
    if not html:
        return []

    ads = _parse_browser_results(html)
    print(f"[LBC_BROWSER] {keyword} page {page} -> {len(ads)} ads")
    logging.info("Leboncoin browser fallback keyword=%s page=%s ads=%s", keyword, page, len(ads))
    return ads


def scrape_leboncoin(session: Session) -> List[Ad]:
    results: List[Ad] = []
    seen_ids: set[str] = set()
    browser_fallback_enabled = True

    for keyword in SEARCH_KEYWORDS:
        for page in range(1, MAX_PAGES + 1):
            offset = (page - 1) * PAGE_SIZE
            payload = _payload(keyword, offset)
            logging.info("Leboncoin API request keyword=%s page=%s offset=%s", keyword, page, offset)

            try:
                response = session.post(API_URL, json=payload, headers=_api_headers(), timeout=30)
                if _is_datadome_blocked(response):
                    raise PermissionError("DataDome blocked Leboncoin API request")
                response.raise_for_status()
                data = response.json()
                ads_data = data.get("ads") or data.get("ad_list") or []
                print(f"[LBC] {keyword} page {page} -> {len(ads_data)} ads")
                parsed_ads = [_parse_api_ad(ad_data) for ad_data in ads_data]
            except PermissionError as exc:
                logging.warning("Leboncoin API blocked keyword=%s page=%s: %s", keyword, page, exc)
                if not browser_fallback_enabled:
                    break
                parsed_ads = _scrape_browser_fallback(keyword, page)
                if not parsed_ads:
                    break
            except Exception as exc:
                logging.exception("Leboncoin API request failed keyword=%s page=%s: %s", keyword, page, exc)
                break

            page_added = 0
            for ad in parsed_ads:
                if ad is None:
                    continue
                if ad.ad_id in seen_ids:
                    logging.debug("Leboncoin duplicate ad_id=%s", ad.ad_id)
                    continue

                seen_ids.add(ad.ad_id)
                results.append(ad)
                page_added += 1

            logging.info(
                "Leboncoin parsed keyword=%s page=%s added=%s cumulative=%s",
                keyword,
                page,
                page_added,
                len(results),
            )

            if not parsed_ads:
                break

    return results
