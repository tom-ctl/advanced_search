import logging
import random
import re
import time
from typing import List, Optional

from bs4 import BeautifulSoup
from requests import Session

from urllib.parse import quote_plus

from utils.filters import parse_integer, normalize_text, SEARCH_KEYWORDS
from utils.models import Ad

SEARCH_URL_TEMPLATE = (
    "https://www.leboncoin.fr/recherche?category=2&text={keyword}&price=max10000&max=250000"
)


def _browser_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Referer": "https://www.leboncoin.fr/",
    }


def _fetch_page(session: Session, url: str) -> str:
    session.get("https://www.leboncoin.fr", timeout=20, headers=_browser_headers())
    response = session.get(url, timeout=20, headers=_browser_headers())
    response.raise_for_status()
    time.sleep(random.uniform(6.0, 10.0))
    return response.text


def _extract_text(element: Optional[BeautifulSoup]) -> str:
    return element.get_text(" ", strip=True) if element else ""


def _find_price(node: BeautifulSoup) -> Optional[int]:
    selectors = ["span[data-qa-id='aditem_price']", "div[data-qa-id='aditem_price']"]
    for selector in selectors:
        tag = node.select_one(selector)
        if tag:
            value = _extract_text(tag)
            price = parse_integer(value)
            if price is not None:
                return price

    text = " ".join(node.stripped_strings)
    matches = re.findall(r"(\d[\d\s,.]*)\s*(?:€|eur)", text, re.IGNORECASE)
    prices = [parse_integer(match) for match in matches if parse_integer(match) is not None]
    return max(prices) if prices else None


def _find_mileage(node: BeautifulSoup) -> Optional[int]:
    text = " ".join(node.stripped_strings)
    match = re.search(r"(\d[\d\s,.]*)\s*(?:km|kilom[eè]tres?)", text, re.IGNORECASE)
    return parse_integer(match.group(1)) if match else None


def _extract_id(link: str) -> str:
    match = re.search(r"/(\d+)(?:\.htm|\.html)?", link)
    if match:
        return match.group(1)
    return link


def scrape_leboncoin(session: Session) -> List[Ad]:
    results: List[Ad] = []
    seen_ids: set[str] = set()

    for keyword in SEARCH_KEYWORDS:
        search_url = SEARCH_URL_TEMPLATE.format(keyword=quote_plus(keyword))
        logging.info("Loading Leboncoin search page for '%s'", keyword)
        try:
            html = _fetch_page(session, search_url)
        except Exception as exc:
            logging.warning("Leboncoin request failed for '%s': %s", keyword, exc)
            continue
        soup = BeautifulSoup(html, "html.parser")
        items = soup.select("li[data-qa-id='aditem_container']") or soup.select("article")

        for item in items:
            link_tag = item.find("a", href=True)
            if not link_tag:
                continue
            link = link_tag["href"]
            if link.startswith("/"):
                link = "https://www.leboncoin.fr" + link

            title = _extract_text(item.select_one("h2")) or _extract_text(link_tag)
            price = _find_price(item)
            mileage = _find_mileage(item)
            description = _extract_text(item.select_one("p"))
            if not description:
                description = normalize_text(_extract_text(item))

            ad_id = _extract_id(link)
            if not title or not ad_id:
                continue

            if ad_id in seen_ids:
                continue

            seen_ids.add(ad_id)
            results.append(
                Ad(
                    source="Leboncoin",
                    ad_id=ad_id,
                    title=title,
                    price=price,
                    mileage=mileage,
                    description=description,
                    link=link,
                )
            )
    return results
