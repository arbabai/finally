import asyncio
import pytest
from app.market.cache import PriceCache
from app.market.models import PricePoint


@pytest.mark.asyncio
async def test_update_and_get():
    cache = PriceCache()
    point = PricePoint.from_prices("AAPL", 190.0, 189.5)
    await cache.update(point)
    result = await cache.get("AAPL")
    assert result is not None
    assert result.price == 190.0


@pytest.mark.asyncio
async def test_get_missing_ticker_returns_none():
    cache = PriceCache()
    result = await cache.get("ZZZZ")
    assert result is None


@pytest.mark.asyncio
async def test_remove():
    cache = PriceCache()
    await cache.update(PricePoint.from_prices("AAPL", 190.0, 189.5))
    await cache.remove("AAPL")
    assert await cache.get("AAPL") is None


@pytest.mark.asyncio
async def test_remove_nonexistent_is_noop():
    cache = PriceCache()
    # Should not raise
    await cache.remove("UNKNOWN")


@pytest.mark.asyncio
async def test_get_all_empty():
    cache = PriceCache()
    result = await cache.get_all()
    assert result == {}


@pytest.mark.asyncio
async def test_get_all_returns_snapshot():
    cache = PriceCache()
    p1 = PricePoint.from_prices("AAPL", 190.0, 189.5)
    p2 = PricePoint.from_prices("MSFT", 420.0, 419.0)
    await cache.update(p1)
    await cache.update(p2)
    all_prices = await cache.get_all()
    assert set(all_prices.keys()) == {"AAPL", "MSFT"}
    assert all_prices["AAPL"].price == 190.0
    assert all_prices["MSFT"].price == 420.0


@pytest.mark.asyncio
async def test_get_all_returns_copy():
    """Mutating the returned dict should not affect the cache."""
    cache = PriceCache()
    await cache.update(PricePoint.from_prices("AAPL", 190.0, 189.5))
    all_prices = await cache.get_all()
    all_prices["FAKE"] = PricePoint.from_prices("FAKE", 1.0, 1.0)
    # Cache should still only have AAPL
    result = await cache.get_all()
    assert "FAKE" not in result


@pytest.mark.asyncio
async def test_subscriber_receives_update():
    cache = PriceCache()
    queue = cache.subscribe()
    point = PricePoint.from_prices("TSLA", 175.0, 174.0)
    await cache.update(point)
    received = queue.get_nowait()
    assert received.ticker == "TSLA"
    assert received.price == 175.0
    cache.unsubscribe(queue)


@pytest.mark.asyncio
async def test_multiple_subscribers_all_receive():
    cache = PriceCache()
    q1 = cache.subscribe()
    q2 = cache.subscribe()
    point = PricePoint.from_prices("NVDA", 880.0, 879.0)
    await cache.update(point)
    r1 = q1.get_nowait()
    r2 = q2.get_nowait()
    assert r1.ticker == "NVDA"
    assert r2.ticker == "NVDA"
    cache.unsubscribe(q1)
    cache.unsubscribe(q2)


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery():
    cache = PriceCache()
    queue = cache.subscribe()
    cache.unsubscribe(queue)
    await cache.update(PricePoint.from_prices("AAPL", 190.0, 189.5))
    assert queue.empty()


@pytest.mark.asyncio
async def test_unsubscribe_nonexistent_is_noop():
    cache = PriceCache()
    fake_queue: asyncio.Queue = asyncio.Queue()
    # Should not raise
    cache.unsubscribe(fake_queue)


@pytest.mark.asyncio
async def test_slow_subscriber_drops_update():
    """A full queue should not block the update path."""
    cache = PriceCache()
    queue = cache.subscribe()
    # Fill the queue to capacity (maxsize=200)
    for i in range(200):
        await cache.update(PricePoint.from_prices("AAPL", 190.0 + i, 190.0 + i - 1))
    # One more update must not raise
    await cache.update(PricePoint.from_prices("AAPL", 999.0, 998.0))
    cache.unsubscribe(queue)


@pytest.mark.asyncio
async def test_update_overwrites_previous():
    cache = PriceCache()
    await cache.update(PricePoint.from_prices("AAPL", 190.0, 189.5))
    await cache.update(PricePoint.from_prices("AAPL", 192.0, 190.0))
    result = await cache.get("AAPL")
    assert result is not None
    assert result.price == 192.0
