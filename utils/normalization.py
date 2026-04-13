import re
import unicodedata


def normalize_text(text: str) -> str:
    cleaned = unicodedata.normalize("NFD", text or "")
    cleaned = "".join(ch for ch in cleaned if unicodedata.category(ch) != "Mn")
    return cleaned.lower()


def normalize(text: str) -> str:
    text = normalize_text(text)
    return re.sub(r"[\s\-]+", "", text)


def normalize_for_matching(text: str) -> str:
    normalized = normalize_text(text)
    return re.sub(r"[\W_]+", "", normalized)


def normalize_keyword(keyword: str) -> str:
    return normalize(keyword)
