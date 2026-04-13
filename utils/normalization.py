import re
import unicodedata


def normalize_text(text: str) -> str:
    cleaned = unicodedata.normalize("NFKD", text or "")
    cleaned = "".join(ch for ch in cleaned if not unicodedata.combining(ch))
    return cleaned.lower()


def normalize_for_matching(text: str) -> str:
    normalized = normalize_text(text)
    return re.sub(r"[\W_]+", "", normalized)


def normalize_keyword(keyword: str) -> str:
    return normalize_for_matching(keyword)
