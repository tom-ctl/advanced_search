import logging
import random
import re
import time
from typing import List, Optional

from bs4 import BeautifulSoup
from requests import Session

from utils.filters import parse_integer, normalize_text
from utils.models import Ad

SEARCH_URL = (
    "https://www.mobile.de/en/search.html?isSearchRequest=true&sb=rel&vc=Car"
    "&priceTo=10000&maxMileage=250000"
)


def _fetch_page(session: Session, url: str) -> str:
    response = session.get(url, timeout=20)
    response.raise_for_status()
    time.sleep(random.uniform(1.5, 3.0))
    return response.text


def _extract_text(element: Optional[BeautifulSoup]) -> str:
    return element.get_text(" ", strip=True) if element else ""


def _find_price(node: BeautifulSoup) -> Optional[int]:
    selectors = ["span.price-block__price", "div[data-testid='price']", "span[data-testid='price']"]
    for selector in selectors:
        tag = node.select_one(selector)
        if tag:
            value = _extract_text(tag)
            price = parse_integer(value)
            if price is not None:
                return price

    text = " ".join(node.stripped_strings)
    match = re.search(r"(\d[\d\s,.]*)(?:€|EUR)", text, re.IGNORECASE)
    return parse_integer(match.group(1)) if match else None


def _find_mileage(node: BeautifulSoup) -> Optional[int]:
    text = " ".join(node.stripped_strings)
    match = re.search(r"(\d[\d\s,.]*)\s*(?:km|kilometers|kilometres)", text, re.IGNORECASE)
    return parse_integer(match.group(1)) if match else None


def _extract_id(link: str) -> str:
    match = re.search(r"/(\d+)(?:\.html)?", link)
    if match:
        return match.group(1)
    return link


def scrape_mobilede(session: Session) -> List[Ad]:
    logging.info("Loading Mobile.de search page")
    html = _fetch_page(session, SEARCH_URL)
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select("li[data-testid='listing-item']") or soup.select("article") or soup.select("div.cBox-body--resultitem")
    results: List[Ad] = []

    for item in items:
        link_tag = item.find("a", href=True)
        if not link_tag:
            continue
        link = link_tag["href"]
        if link.startswith("/"):
            link = "https://www.mobile.de" + link

        title = _extract_text(item.select_one("h2")) or _extract_text(link_tag)
        price = _find_price(item)
        mileage = _find_mileage(item)
        description = _extract_text(item.select_one("p"))
        if not description:
            description = normalize_text(_extract_text(item))

        ad_id = _extract_id(link)
        if not title or not ad_id:
            continue

        results.append(
            Ad(
                source="Mobile.de",
                ad_id=ad_id,
                title=title,
                price=price,
                mileage=mileage,
                description=description,
                link=link,
            )
        )
    return results
