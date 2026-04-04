import time
import pytest
from app.market.models import PricePoint


def test_direction_up():
    p = PricePoint.from_prices("X", 101.0, 100.0)
    assert p.change_direction == "up"


def test_direction_down():
    p = PricePoint.from_prices("X", 99.0, 100.0)
    assert p.change_direction == "down"


def test_direction_flat():
    p = PricePoint.from_prices("X", 100.0, 100.0)
    assert p.change_direction == "flat"


def test_to_sse_dict_keys():
    p = PricePoint.from_prices("AAPL", 190.0, 189.5)
    d = p.to_sse_dict()
    assert set(d.keys()) == {"ticker", "price", "prev_price", "timestamp", "direction"}


def test_to_sse_dict_values():
    p = PricePoint.from_prices("AAPL", 190.1234567, 189.5)
    d = p.to_sse_dict()
    assert d["ticker"] == "AAPL"
    assert d["price"] == round(190.1234567, 4)
    assert d["prev_price"] == round(189.5, 4)
    assert d["direction"] == "up"


def test_timestamp_is_recent():
    before = time.time()
    p = PricePoint.from_prices("AAPL", 190.0, 189.5)
    after = time.time()
    assert before <= p.timestamp <= after


def test_ticker_preserved():
    p = PricePoint.from_prices("TSLA", 175.0, 174.0)
    assert p.ticker == "TSLA"


def test_price_and_prev_price_stored():
    p = PricePoint.from_prices("MSFT", 420.5, 419.0)
    assert p.price == 420.5
    assert p.prev_price == 419.0


def test_equal_prices_flat():
    p = PricePoint.from_prices("GOOGL", 175.0, 175.0)
    assert p.change_direction == "flat"
    assert p.price == p.prev_price


def test_to_sse_dict_direction_down():
    p = PricePoint.from_prices("JPM", 198.0, 200.0)
    d = p.to_sse_dict()
    assert d["direction"] == "down"
