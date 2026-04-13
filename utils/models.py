from dataclasses import dataclass
from typing import Optional


@dataclass
class Ad:
    source: str
    ad_id: str
    title: str
    price: Optional[int]
    mileage: Optional[int]
    description: str
    link: str
    market_price: Optional[int] = None
    score: Optional[float] = None
    label: Optional[str] = None
