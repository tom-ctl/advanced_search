import json
import logging
import re
from typing import Any, Iterable, List, Optional

from bs4 import BeautifulSoup
from requests import Session

from utils.filters import MAX_MILEAGE, MAX_PRICE, parse_mileage, parse_number, parse_price
from utils.models import Ad

BASE_URL = "https://www.autoscout24.fr"
MAX_PAGES = 5
LAST_STATUS = {"status": "idle", "count": 0, "message": ""}
SEARCHES = [
    ("toyota", "hilux"),
    ("mitsubishi", "l200"),
    ("nissan", "navara"),
    ("ford", "ranger"),
    ("mazda", "bt-50"),
]


def _set_status(status: str, count: int = 0, message: str = "") -> None:
    LAST_STATUS["status"] = status
    LAST_STATUS["count"] = count
    LAST_STATUS["message"] = message


def build_url(make: str, model: str, page: int) -> str:
    return (
        f"{BASE_URL}/lst/{make}/{model}"
        f"?priceTo={MAX_PRICE}&kmto={MAX_MILEAGE}&page={page}"
    )


def _browser_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        "Referer": BASE_URL + "/",
    }


def _extract_text(node: Optional[BeautifulSoup]) -> str:
    return node.get_text(" ", strip=True) if node else ""


def _absolute_link(link: str) -> str:
    if link.startswith("/"):
        return BASE_URL + link
    return link


def _extract_id(link: str) -> str:
    match = re.search(r"/(\d+)(?:[/?#]|$)", link)
    if match:
        return match.group(1)
    return link


def _fetch_page(session: Session, url: str) -> str:
    response = session.get(url, headers=_browser_headers(), timeout=30)
    response.raise_for_status()
    return response.text


def _is_blocked_html(html: str) -> bool:
    lowered = html.lower()
    return "datadome" in lowered or "captcha" in lowered or "temporarily restricted" in lowered


def _extract_price(item: BeautifulSoup, text_blob: str) -> Optional[int]:
    selector_candidates = [
        "[data-testid='price']",
        "[aria-label*='prix']",
        "[aria-label*='price']",
    ]
    for selector in selector_candidates:
        value = _extract_text(item.select_one(selector))
        if value:
            price = parse_price(value)
            if price is not None:
                return price

    for text in item.stripped_strings:
        if "€" not in text and "eur" not in text.lower():
            continue
        price = parse_price(text)
        if price is not None:
            return price

    euro_match = re.search(r"(\d[\d\s.]*)\s*(?:€|eur)", text_blob, re.IGNORECASE)
    if euro_match:
        return parse_price(euro_match.group(1))

    return None


def _extract_article_ads(items: Iterable[BeautifulSoup]) -> List[Ad]:
    parsed_ads: List[Ad] = []

    for item in items:
        link_tag = (
            item.select_one("a[href*='/offres/']")
            or item.select_one("a[href*='/lst/']")
            or item.find("a", href=True)
        )
        if not link_tag or not link_tag.get("href"):
            continue

        link = _absolute_link(link_tag["href"])
        title = (
            _extract_text(item.select_one("h2"))
            or _extract_text(item.select_one("h3"))
            or _extract_text(item.select_one("[data-testid='title']"))
            or _extract_text(link_tag)
        )
        if not title:
            continue

        text_blob = " ".join(item.stripped_strings)
        price = _extract_price(item, text_blob)
        mileage = parse_mileage(text_blob)
        ad_id = item.get("id") or item.get("data-guid") or _extract_id(link)

        parsed_ads.append(
            Ad(
                source="AutoScout24",
                ad_id=str(ad_id),
                title=title,
                price=price,
                mileage=mileage,
                description=text_blob,
                link=link,
            )
        )

    return parsed_ads


def _walk(value: Any) -> Iterable[Any]:
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk(nested)


def _extract_json_ads(html: str) -> List[Ad]:
    soup = BeautifulSoup(html, "html.parser")
    parsed_ads: List[Ad] = []

    for script in soup.select("script[type='application/ld+json'], script#__NEXT_DATA__"):
        raw = script.string or script.get_text(strip=True)
        if not raw:
            continue

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue

        for node in _walk(payload):
            if not isinstance(node, dict):
                continue

            url = node.get("url") or node.get("offerUrl") or node.get("detailPageUrl") or ""
            vehicle = node.get("vehicle") if isinstance(node.get("vehicle"), dict) else {}
            title = (
                node.get("name")
                or node.get("title")
                or node.get("headline")
                or vehicle.get("modelVersionInput")
                or vehicle.get("model")
                or ""
            )
            if not url or "/offres/" not in str(url):
                continue

            mileage = None
            raw_mileage = (
                node.get("mileageFromOdometer")
                or node.get("mileage")
                or node.get("distance")
                or node.get("km")
                or vehicle.get("mileageInKm")
            )
            if isinstance(raw_mileage, dict):
                mileage = parse_number(
                    str(raw_mileage.get("value") or raw_mileage.get("name") or ""),
                    max_value=MAX_MILEAGE,
                )
            else:
                mileage = parse_number(str(raw_mileage or ""), max_value=MAX_MILEAGE) or parse_mileage(
                    json.dumps(node, ensure_ascii=False)
                )

            raw_price = node.get("price") or node.get("rawPrice") or node.get("amount")
            if isinstance(raw_price, dict):
                price = parse_price(
                    str(
                        raw_price.get("value")
                        or raw_price.get("amount")
                        or raw_price.get("priceFormatted")
                        or ""
                    )
                )
            else:
                price = parse_price(str(raw_price or ""))

            link = _absolute_link(str(url))
            ad_id = str(node.get("id") or node.get("identifier") or _extract_id(link))
            description = (
                node.get("description")
                or node.get("subtitle")
                or vehicle.get("subtitle")
                or title
            )
            if vehicle:
                make = vehicle.get("make") or ""
                model = vehicle.get("model") or ""
                version = vehicle.get("modelVersionInput") or ""
                title = " ".join(part for part in [make, model, version] if part).strip() or title

            parsed_ads.append(
                Ad(
                    source="AutoScout24",
                    ad_id=ad_id,
                    title=title,
                    price=price,
                    mileage=mileage,
                    description=description,
                    link=link,
                )
            )

    return parsed_ads


def scrape_autoscout(session: Session) -> List[Ad]:
    _set_status("running", 0, "scan started")
    results: List[Ad] = []
    seen_ids: set[str] = set()

    for make, model in SEARCHES:
        for page in range(1, MAX_PAGES + 1):
            url = build_url(make, model, page)
            logging.info("AutoScout request make=%s model=%s page=%s url=%s", make, model, page, url)

            try:
                html = _fetch_page(session, url)
            except Exception as exc:
                _set_status("error", len(results), f"{make} {model} page {page}: {exc}")
                logging.exception(
                    "AutoScout request failed make=%s model=%s page=%s: %s",
                    make,
                    model,
                    page,
                    exc,
                )
                continue

            if _is_blocked_html(html):
                message = f"blocked on {make} {model} page {page}"
                _set_status("blocked", len(results), message)
                logging.warning("AutoScout block detected: %s", message)
                return results

            soup = BeautifulSoup(html, "html.parser")
            items = soup.select("article") or soup.select("[data-testid='listing']")
            print(f"[AUTOSCOUT] {make} {model} page {page} -> {len(items)} items")
            logging.debug("AutoScout DOM items make=%s model=%s page=%s count=%s", make, model, page, len(items))

            json_ads = _extract_json_ads(html)
            logging.info(
                "AutoScout JSON parsed make=%s model=%s page=%s count=%s",
                make,
                model,
                page,
                len(json_ads),
            )
            parsed_ads = json_ads or _extract_article_ads(items)

            if not parsed_ads:
                logging.warning("AutoScout parsed 0 ads make=%s model=%s page=%s", make, model, page)
                continue

            page_added = 0
            for ad in parsed_ads:
                if not ad.title or not ad.link or not ad.ad_id:
                    logging.debug("AutoScout skipped incomplete ad make=%s model=%s page=%s", make, model, page)
                    continue
                if ad.ad_id in seen_ids:
                    logging.debug("AutoScout duplicate ad_id=%s", ad.ad_id)
                    continue

                seen_ids.add(ad.ad_id)
                results.append(ad)
                page_added += 1

            logging.info(
                "AutoScout parsed make=%s model=%s page=%s added=%s cumulative=%s",
                make,
                model,
                page,
                page_added,
                len(results),
            )

    if results:
        _set_status("ok", len(results), "ads collected")
    else:
        _set_status("empty", 0, "no ads collected")
    return results
