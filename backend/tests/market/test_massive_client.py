import asyncio
import pytest
import httpx
import respx
from unittest.mock import AsyncMock, patch

from app.market.massive_client import MassiveClient, BASE_URL
from app.market.cache import PriceCache
from app.market.models import PricePoint


SAMPLE_RESPONSE = {
    "status": "OK",
    "tickers": [
        {
            "ticker": "AAPL",
            "lastTrade": {"p": 189.70, "s": 100},
            "day": {"o": 187.20, "h": 190.50, "l": 186.80, "c": 189.70, "v": 52341234},
            "prevDay": {"c": 187.20},
        },
        {
            "ticker": "MSFT",
            "lastTrade": {"p": 420.50, "s": 50},
            "day": {"o": 418.0, "h": 422.0, "l": 417.0, "c": 420.50, "v": 20000000},
            "prevDay": {"c": 418.0},
        },
    ],
}


# ------------------------------------------------------------------ add/remove

def test_add_ticker():
    client = MassiveClient(api_key="test-key")
    client.add_ticker("AAPL")
    assert "AAPL" in client._tickers


def test_add_ticker_normalises_case():
    client = MassiveClient(api_key="test-key")
    client.add_ticker("aapl")
    assert "AAPL" in client._tickers


def test_remove_ticker():
    client = MassiveClient(api_key="test-key")
    client.add_ticker("AAPL")
    client.remove_ticker("AAPL")
    assert "AAPL" not in client._tickers


def test_remove_ticker_normalises_case():
    client = MassiveClient(api_key="test-key")
    client.add_ticker("AAPL")
    client.remove_ticker("aapl")
    assert "AAPL" not in client._tickers


def test_remove_unknown_ticker_is_noop():
    client = MassiveClient(api_key="test-key")
    # Should not raise
    client.remove_ticker("UNKNOWN")


def test_remove_ticker_clears_prev_price():
    client = MassiveClient(api_key="test-key")
    client.add_ticker("AAPL")
    client._prev_prices["AAPL"] = 190.0
    client.remove_ticker("AAPL")
    assert "AAPL" not in client._prev_prices


# ------------------------------------------------------------------ source_name

def test_source_name():
    client = MassiveClient(api_key="test-key")
    assert client.source_name == "MassiveAPI"


# ------------------------------------------------------------------ _fetch_prices

@pytest.mark.asyncio
@respx.mock
async def test_fetch_prices_parses_last_trade():
    respx.get(f"{BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers").mock(
        return_value=httpx.Response(200, json=SAMPLE_RESPONSE)
    )
    client = MassiveClient(api_key="test-key")
    async with httpx.AsyncClient(timeout=10.0) as http_client:
        prices = await client._fetch_prices(http_client, ["AAPL", "MSFT"])
    assert prices["AAPL"] == 189.70
    assert prices["MSFT"] == 420.50


@pytest.mark.asyncio
@respx.mock
async def test_fetch_prices_falls_back_to_day_close():
    response_data = {
        "status": "OK",
        "tickers": [
            {
                "ticker": "AAPL",
                "lastTrade": None,  # no last trade
                "day": {"c": 188.50},
            }
        ],
    }
    respx.get(f"{BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers").mock(
        return_value=httpx.Response(200, json=response_data)
    )
    client = MassiveClient(api_key="test-key")
    async with httpx.AsyncClient(timeout=10.0) as http_client:
        prices = await client._fetch_prices(http_client, ["AAPL"])
    assert prices["AAPL"] == 188.50


@pytest.mark.asyncio
@respx.mock
async def test_fetch_prices_skips_ticker_without_price():
    response_data = {
        "status": "OK",
        "tickers": [
            {
                "ticker": "AAPL",
                "lastTrade": None,
                "day": None,
            }
        ],
    }
    respx.get(f"{BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers").mock(
        return_value=httpx.Response(200, json=response_data)
    )
    client = MassiveClient(api_key="test-key")
    async with httpx.AsyncClient(timeout=10.0) as http_client:
        prices = await client._fetch_prices(http_client, ["AAPL"])
    assert "AAPL" not in prices


@pytest.mark.asyncio
@respx.mock
async def test_fetch_prices_skips_entry_without_ticker_field():
    response_data = {
        "status": "OK",
        "tickers": [
            {"lastTrade": {"p": 100.0}},  # missing "ticker" field
        ],
    }
    respx.get(f"{BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers").mock(
        return_value=httpx.Response(200, json=response_data)
    )
    client = MassiveClient(api_key="test-key")
    async with httpx.AsyncClient(timeout=10.0) as http_client:
        prices = await client._fetch_prices(http_client, ["AAPL"])
    assert prices == {}


@pytest.mark.asyncio
@respx.mock
async def test_fetch_prices_raises_on_http_error():
    respx.get(f"{BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers").mock(
        return_value=httpx.Response(403)
    )
    client = MassiveClient(api_key="bad-key")
    async with httpx.AsyncClient(timeout=10.0) as http_client:
        with pytest.raises(httpx.HTTPStatusError):
            await client._fetch_prices(http_client, ["AAPL"])


@pytest.mark.asyncio
@respx.mock
async def test_fetch_prices_empty_tickers_array():
    response_data = {"status": "OK", "tickers": []}
    respx.get(f"{BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers").mock(
        return_value=httpx.Response(200, json=response_data)
    )
    client = MassiveClient(api_key="test-key")
    async with httpx.AsyncClient(timeout=10.0) as http_client:
        prices = await client._fetch_prices(http_client, ["UNKNOWN"])
    assert prices == {}


# ------------------------------------------------------------------ start / stop

@pytest.mark.asyncio
@respx.mock
async def test_start_writes_to_cache():
    respx.get(f"{BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers").mock(
        return_value=httpx.Response(200, json=SAMPLE_RESPONSE)
    )
    client = MassiveClient(api_key="test-key", poll_interval=0.1)
    client.add_ticker("AAPL")
    cache = PriceCache()

    task = asyncio.create_task(client.start(cache))
    await asyncio.sleep(0.25)
    await client.stop()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except asyncio.TimeoutError:
        task.cancel()

    result = await cache.get("AAPL")
    assert result is not None
    assert result.price == 189.70


@pytest.mark.asyncio
@respx.mock
async def test_start_tracks_prev_price():
    """Second poll should use the first poll's price as prev_price."""
    call_count = 0

    def response_factory(request):
        nonlocal call_count
        call_count += 1
        price = 189.70 if call_count == 1 else 191.00
        return httpx.Response(200, json={
            "status": "OK",
            "tickers": [{"ticker": "AAPL", "lastTrade": {"p": price}, "day": {"c": price}}],
        })

    respx.get(f"{BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers").mock(
        side_effect=response_factory
    )
    client = MassiveClient(api_key="test-key", poll_interval=0.1)
    client.add_ticker("AAPL")
    cache = PriceCache()

    task = asyncio.create_task(client.start(cache))
    await asyncio.sleep(0.35)
    await client.stop()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except asyncio.TimeoutError:
        task.cancel()

    result = await cache.get("AAPL")
    assert result is not None
    # After second poll, prev_price should be the first poll's price
    assert result.prev_price == 189.70
    assert result.price == 191.00


@pytest.mark.asyncio
async def test_stop_is_idempotent():
    client = MassiveClient(api_key="test-key")
    await client.stop()
    await client.stop()
    # Should not raise


@pytest.mark.asyncio
@respx.mock
async def test_start_handles_http_403_without_crashing():
    respx.get(f"{BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers").mock(
        return_value=httpx.Response(403)
    )
    client = MassiveClient(api_key="bad-key", poll_interval=0.1)
    client.add_ticker("AAPL")
    cache = PriceCache()

    task = asyncio.create_task(client.start(cache))
    await asyncio.sleep(0.25)
    await client.stop()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except asyncio.TimeoutError:
        task.cancel()
    # Should have completed without raising


@pytest.mark.asyncio
@respx.mock
async def test_start_handles_timeout_without_crashing():
    respx.get(f"{BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers").mock(
        side_effect=httpx.TimeoutException("timeout")
    )
    client = MassiveClient(api_key="test-key", poll_interval=0.1)
    client.add_ticker("AAPL")
    cache = PriceCache()

    task = asyncio.create_task(client.start(cache))
    await asyncio.sleep(0.25)
    await client.stop()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except asyncio.TimeoutError:
        task.cancel()
    # Should have completed without raising


@pytest.mark.asyncio
async def test_start_skips_poll_when_no_tickers():
    """When watchlist is empty, no HTTP calls should be made."""
    client = MassiveClient(api_key="test-key", poll_interval=0.1)
    cache = PriceCache()

    task = asyncio.create_task(client.start(cache))
    await asyncio.sleep(0.25)
    await client.stop()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except asyncio.TimeoutError:
        task.cancel()
    # No tickers — cache should be empty
    all_prices = await cache.get_all()
    assert all_prices == {}
