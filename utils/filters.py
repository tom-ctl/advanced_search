import re
import unicodedata
from typing import List, Optional, Tuple

DEBUG = True
MAX_PRICE = 15000
MAX_MILEAGE = 250000

SEARCH_KEYWORDS: List[str] = [
    "navara",
    "l200",
    "hilux",
    "ranger",
    "bt-50",
    "bt50",
    "b2500",
    "dmax",
    "pickup",
    "pick up",
    "pick-up",
    "landcruiser",
    "land cruiser",
    "patrol",
    "ram",
]

MATCH_KEYWORDS: List[str] = [
    "navara",
    "l200",
    "hilux",
    "ranger",
    "bt50",
    "b2500",
    "dmax",
    "pickup",
    "pick up",
    "pick-up",
    "landcruiser",
    "patrol",
    "ram",
]

MATCH_KEYWORDS_NORMALIZED = [
    re.sub(r"[\s\-]", "", keyword.lower()) for keyword in MATCH_KEYWORDS
]


def parse_number(text: str, max_value: Optional[int] = None) -> Optional[int]:
    if not text:
        return None

    chunks = re.findall(r"\d[\d\s.,]*", text.replace("\u00a0", " "))
    candidates = []
    for chunk in chunks:
        digits = re.sub(r"[^\d]", "", chunk)
        if not digits:
            continue
        value = int(digits)
        if max_value is not None and value > max_value:
            continue
        candidates.append(value)

    if not candidates:
        return None

    return max(candidates)


def normalize_text(text: str) -> str:
    cleaned = unicodedata.normalize("NFD", text or "")
    cleaned = "".join(ch for ch in cleaned if unicodedata.category(ch) != "Mn")
    return cleaned.lower()


def normalize(text: str) -> str:
    text = normalize_text(text)
    return re.sub(r"[\s\-]", "", text)


def parse_price(text: str) -> Optional[int]:
    return parse_number(text, max_value=100000)


def parse_integer(raw: str) -> Optional[int]:
    return parse_price(raw)


def parse_mileage(text: str) -> Optional[int]:
    if not text:
        return None

    match = re.search(
        r"(\d[\d\s.,]*)\s*(?:km|kilometres?|kilometers?)",
        normalize_text(text),
        re.IGNORECASE,
    )
    if not match:
        return None

    return parse_number(match.group(1), max_value=MAX_MILEAGE)


def match_keywords(title: str, description: str) -> bool:
    text = normalize(f"{title} {description}")
    return any(keyword in text for keyword in MATCH_KEYWORDS_NORMALIZED)


def is_valid(ad: dict) -> Tuple[bool, str]:
    price = ad.get("price")
    mileage = ad.get("km")
    title = ad.get("title") or ""
    description = ad.get("description") or ""

    if not match_keywords(title, description):
        return False, "keyword"
    if price is None:
        return False, "no_price"
    if mileage is None:
        return False, "no_km"
    if price > MAX_PRICE:
        return False, "price"
    if mileage > MAX_MILEAGE:
        return False, "km"
    if "hs" in normalize(title):
        return False, "hs"
    return True, "ok"


def is_valid_ad(
    title: str,
    description: str,
    price: Optional[int],
    mileage: Optional[int],
) -> Tuple[bool, str]:
    return is_valid(
        {
            "title": title,
            "description": description,
            "price": price,
            "km": mileage,
        }
    )
