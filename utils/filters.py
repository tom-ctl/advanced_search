import re
from typing import List, Optional

from .normalization import normalize_for_matching, normalize_text, normalize_keyword

BASE_KEYWORDS: List[str] = [
    "navara",
    "l200",
    "triton",
    "hilux",
    "ranger",
    "raptor",
    "wildtrack",
    "bt-50",
    "bt50",
    "b2500",
    "pickup",
    "landcruiser",
    "land cruiser",
    "patrol",
    "gladiator",
    "ram",
]

EXTENDED_KEYWORDS: List[str] = [
    "4x4",
    "tout terrain",
    "offroad",
    "utilitaire 4x4",
    "double cabine",
    "pick up",
    "pick-up",
    "camionnette 4x4",
    "benne",
    "plateau",
    "nissan pickup",
    "toyota pickup",
    "mitsubishi pickup",
    "ford pickup",
    "mazda pickup",
    "dodge ram",
    "jeep pickup",
    "suv 4x4",
]

SEARCH_KEYWORDS = BASE_KEYWORDS + EXTENDED_KEYWORDS
SEARCH_KEYWORDS_NORMALIZED = [normalize_keyword(word) for word in SEARCH_KEYWORDS]


def parse_integer(raw: str) -> Optional[int]:
    if not raw:
        return None

    cleaned = re.sub(r"[\u00A0\s\.,]+", "", raw)
    if not cleaned.isdigit():
        return None

    return int(cleaned)


def contains_keyword(text: str) -> bool:
    normalized = normalize_for_matching(text)
    return any(keyword in normalized for keyword in SEARCH_KEYWORDS_NORMALIZED)


def contains_hs(text: str) -> bool:
    normalized = normalize_text(text)
    return bool(re.search(r"\bhs\b", normalized))


def is_valid_ad(title: str, description: str, price: Optional[int], mileage: Optional[int]) -> bool:
    if price is None or mileage is None:
        return False
    if price >= 10000:
        return False
    if mileage >= 250000:
        return False

    combined = f"{title} {description}"
    if contains_hs(combined):
        return False

    if not contains_keyword(combined):
        return False

    return True
