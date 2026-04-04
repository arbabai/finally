from dataclasses import dataclass
from typing import Literal
import time


@dataclass
class PricePoint:
    ticker: str
    price: float
    prev_price: float          # Price from the immediately preceding update
    timestamp: float           # Unix epoch seconds (float)
    change_direction: Literal["up", "down", "flat"]

    @classmethod
    def from_prices(cls, ticker: str, price: float, prev_price: float) -> "PricePoint":
        if price > prev_price:
            direction = "up"
        elif price < prev_price:
            direction = "down"
        else:
            direction = "flat"
        return cls(
            ticker=ticker,
            price=price,
            prev_price=prev_price,
            timestamp=time.time(),
            change_direction=direction,
        )

    def to_sse_dict(self) -> dict:
        """Serialised form sent over the SSE stream."""
        return {
            "ticker": self.ticker,
            "price": round(self.price, 4),
            "prev_price": round(self.prev_price, 4),
            "timestamp": self.timestamp,
            "direction": self.change_direction,
        }
