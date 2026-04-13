import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class Ad:
    source_name: str
    ad_id: str
    title: str
    price: int
    mileage: int
    description: str
    link: str


PRICE_PATTERN = re.compile(
    r"(?<!\d)(?P<value>\d{1,3}(?:[ \u202f\.\,]\d{3})*)(?:\s*(?:€|eur))?",
    re.IGNORECASE,
)
MILEAGE_PATTERN = re.compile(
    r"(?<!\d)(?P<value>\d{1,3}(?:[ \u202f\.\,]\d{3})*)\s*(?:km|kilom[eè]tres?)",
    re.IGNORECASE,
)


def _extract_int(text: str) -> Optional[int]:
    if not text:
        return None

    value = re.sub(r"[\u00A0\s\.,]", "", text)
    if not value.isdigit():
        return None
    return int(value)


def parse_price(raw: str) -> Optional[int]:
    if not raw:
        return None
    raw = raw.replace("\u202f", " ").replace("\xa0", " ")
    for match in PRICE_PATTERN.finditer(raw):
        candidate = _extract_int(match.group("value"))
        if candidate is not None and candidate > 0:
            return candidate
    return None


def parse_mileage(raw: str) -> Optional[int]:
    if not raw:
        return None
    raw = raw.replace("\u202f", " ").replace("\xa0", " ")
    match = MILEAGE_PATTERN.search(raw)
    if not match:
        return None
    return _extract_int(match.group("value"))


def extract_id_from_url(url: str) -> str:
    if not url:
        return ""
    match = re.search(r"(\d{5,})", url)
    return match.group(1) if match else url
