import re
import unicodedata
from typing import Optional

from .models import Ad

SEARCH_KEYWORDS = [
    "navara",
    "l200",
    "triton",
    "hilux",
    "ranger",
    "raptor",
    "wildtrack",
    "bt-50",
    "b2500",
    "pickup",
    "landcruiser",
    "patrol",
    "gladiator",
    "ram",
]

KEYWORD_PATTERNS = [
    r"navara",
    r"l[-_ ]*200",
    r"triton",
    r"hilux",
    r"ranger",
    r"raptor",
    r"wildtrack",
    r"bt[-_ ]*50",
    r"b2500",
    r"pickup",
    r"landcruiser",
    r"patrol",
    r"gladiator",
    r"ram",
]

KEYWORD_REGEX = re.compile(r"\b(?:" + r"|".join(KEYWORD_PATTERNS) + r")\b", re.IGNORECASE)

PRICE_CLEANER = re.compile(r"[^0-9,\.\s]")
NUMBER_EXTRACTOR = re.compile(r"[0-9]+(?:[.,\s][0-9]{3})*")


def normalize_text(text: str) -> str:
    cleaned = unicodedata.normalize("NFKD", text or "")
    cleaned = "".join(ch for ch in cleaned if not unicodedata.combining(ch))
    return cleaned.lower()


def parse_integer(raw: str) -> Optional[int]:
    if not raw:
        return None

    safe = PRICE_CLEANER.sub("", raw)
    match = NUMBER_EXTRACTOR.search(safe)
    if not match:
        return None

    digits = match.group(0).replace(" ", "").replace(".", "").replace(",", "")
    return int(digits) if digits.isdigit() else None


def contains_keyword(text: str) -> bool:
    normalized = normalize_text(text)
    normalized = re.sub(r"[\W_]+", " ", normalized)
    return bool(KEYWORD_REGEX.search(normalized))


def is_valid_ad(ad: Ad) -> bool:
    if ad.price is None or ad.mileage is None:
        return False

    combined_text = f"{ad.title}\n{ad.description}"
    if not contains_keyword(combined_text):
        return False

    if ad.price >= 10000:
        return False

    if ad.mileage >= 250000:
        return False

    normalized_desc = normalize_text(ad.description)
    if re.search(r"\bhs\b", normalized_desc):
        return False

    return True
