from typing import Tuple


def estimate_market_price(mileage: int) -> int:
    market_price = 12000
    if mileage > 200000:
        market_price -= 3000
    elif mileage < 150000:
        market_price += 2000
    return max(market_price, 5000)


def score_ad(price: int, mileage: int) -> Tuple[int, float, str]:
    market_price = estimate_market_price(mileage)
    score = round((market_price - price) / market_price, 3)
    if score > 0.3:
        label = "EXCELLENT DEAL"
    elif score > 0.1:
        label = "GOOD DEAL"
    else:
        label = "OK"
    return market_price, score, label
