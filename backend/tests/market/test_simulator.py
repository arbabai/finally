import asyncio
import pytest
from app.market.simulator import (
    MarketSimulator,
    SEED_PRICES,
    DEFAULT_SEED_PRICE,
    TICKER_CONFIGS,
    DEFAULT_CONFIG,
    TickerState,
)
from app.market.cache import PriceCache
from app.market.models import PricePoint


# ------------------------------------------------------------------ add/remove

def test_add_ticker():
    sim = MarketSimulator()
    sim.add_ticker("AAPL")
    assert "AAPL" in sim._states


def test_add_ticker_normalises_case():
    sim = MarketSimulator()
    sim.add_ticker("aapl")
    assert "AAPL" in sim._states
    assert "aapl" not in sim._states


def test_add_ticker_idempotent():
    sim = MarketSimulator()
    sim.add_ticker("AAPL")
    price_before = sim._states["AAPL"].price
    sim.add_ticker("AAPL")  # second call — should not reset price
    assert sim._states["AAPL"].price == price_before


def test_remove_ticker():
    sim = MarketSimulator()
    sim.add_ticker("AAPL")
    sim.remove_ticker("AAPL")
    assert "AAPL" not in sim._states


def test_remove_ticker_normalises_case():
    sim = MarketSimulator()
    sim.add_ticker("AAPL")
    sim.remove_ticker("aapl")
    assert "AAPL" not in sim._states


def test_remove_unknown_ticker_is_noop():
    sim = MarketSimulator()
    # Should not raise
    sim.remove_ticker("UNKNOWN")


# ------------------------------------------------------------------ seed prices

def test_known_ticker_uses_seed_price():
    sim = MarketSimulator()
    sim.add_ticker("AAPL")
    assert sim._states["AAPL"].price == SEED_PRICES["AAPL"]


def test_all_known_tickers_use_correct_seed():
    sim = MarketSimulator()
    for ticker, expected_price in SEED_PRICES.items():
        sim.add_ticker(ticker)
        assert sim._states[ticker].price == expected_price, f"{ticker}: expected {expected_price}"


def test_unknown_ticker_gets_default_seed():
    sim = MarketSimulator()
    sim.add_ticker("ZZZZ")
    assert sim._states["ZZZZ"].price == DEFAULT_SEED_PRICE


def test_unknown_ticker_gets_default_config():
    sim = MarketSimulator()
    sim.add_ticker("ZZZZ")
    config = sim._states["ZZZZ"].config
    assert config.sigma == DEFAULT_CONFIG.sigma
    assert config.mu == DEFAULT_CONFIG.mu
    assert config.sector == DEFAULT_CONFIG.sector


def test_known_ticker_uses_correct_config():
    sim = MarketSimulator()
    sim.add_ticker("AAPL")
    config = sim._states["AAPL"].config
    assert config == TICKER_CONFIGS["AAPL"]


# ------------------------------------------------------------------ tick logic

def test_tick_sets_prev_price_before_update():
    sim = MarketSimulator()
    sim.add_ticker("AAPL")
    initial_price = sim._states["AAPL"].price
    states = dict(sim._states)
    sim._tick(states)
    assert states["AAPL"].prev_price == initial_price


def test_tick_price_stays_positive():
    sim = MarketSimulator()
    sim.add_ticker("AAPL")
    states = dict(sim._states)
    for _ in range(100):
        sim._tick(states)
    assert states["AAPL"].price > 0


def test_price_floor_enforced():
    """Price must never fall below 0.01."""
    sim = MarketSimulator()
    sim.add_ticker("AAPL")
    states = dict(sim._states)
    for _ in range(1000):
        sim._tick(states)
    assert states["AAPL"].price >= 0.01


def test_tick_prev_price_chain():
    """prev_price on tick N equals price on tick N-1."""
    sim = MarketSimulator()
    sim.add_ticker("MSFT")
    states = dict(sim._states)
    sim._tick(states)
    price_after_tick1 = states["MSFT"].price
    sim._tick(states)
    assert states["MSFT"].prev_price == price_after_tick1


def test_tick_multiple_tickers():
    sim = MarketSimulator()
    for ticker in ["AAPL", "MSFT", "TSLA"]:
        sim.add_ticker(ticker)
    states = dict(sim._states)
    sim._tick(states)
    for ticker in ["AAPL", "MSFT", "TSLA"]:
        assert states[ticker].price > 0


def test_tick_empty_states_does_not_raise():
    sim = MarketSimulator()
    # No tickers added — should not raise
    sim._tick({})


def test_tick_multiple_sectors():
    """Tickers from different sectors should all advance correctly."""
    sim = MarketSimulator()
    sim.add_ticker("AAPL")   # tech
    sim.add_ticker("JPM")    # finance
    sim.add_ticker("TSLA")   # auto
    states = dict(sim._states)
    sim._tick(states)
    for ticker in ["AAPL", "JPM", "TSLA"]:
        assert states[ticker].price > 0
        assert states[ticker].prev_price > 0


# ------------------------------------------------------------------ source_name

def test_source_name():
    sim = MarketSimulator()
    assert sim.source_name == "Simulator"


# ------------------------------------------------------------------ async lifecycle

@pytest.mark.asyncio
async def test_start_writes_to_cache():
    sim = MarketSimulator()
    sim.add_ticker("AAPL")
    cache = PriceCache()

    try:
        await asyncio.wait_for(sim.start(cache), timeout=1.2)
    except asyncio.TimeoutError:
        pass  # expected — stop() was not called

    result = await cache.get("AAPL")
    assert result is not None
    assert isinstance(result, PricePoint)
    assert result.price > 0


@pytest.mark.asyncio
async def test_stop_terminates_start():
    sim = MarketSimulator()
    sim.add_ticker("AAPL")
    cache = PriceCache()

    async def run_and_stop():
        task = asyncio.create_task(sim.start(cache))
        await asyncio.sleep(0.6)
        await sim.stop()
        await asyncio.wait_for(task, timeout=2.0)

    await run_and_stop()
    # If we got here, stop() successfully terminated start()


@pytest.mark.asyncio
async def test_stop_is_idempotent():
    sim = MarketSimulator()
    await sim.stop()
    await sim.stop()
    # Should not raise


@pytest.mark.asyncio
async def test_add_ticker_during_run():
    """add_ticker called while the simulator is running should work."""
    sim = MarketSimulator()
    sim.add_ticker("AAPL")
    cache = PriceCache()

    async def run_and_add():
        task = asyncio.create_task(sim.start(cache))
        await asyncio.sleep(0.3)
        sim.add_ticker("MSFT")
        await asyncio.sleep(0.6)
        await sim.stop()
        await asyncio.wait_for(task, timeout=2.0)

    await run_and_add()
    msft = await cache.get("MSFT")
    assert msft is not None
    assert msft.price > 0


@pytest.mark.asyncio
async def test_remove_ticker_during_run():
    """remove_ticker called while the simulator is running stops updates."""
    sim = MarketSimulator()
    sim.add_ticker("AAPL")
    sim.add_ticker("MSFT")
    cache = PriceCache()

    async def run_and_remove():
        task = asyncio.create_task(sim.start(cache))
        await asyncio.sleep(0.3)
        sim.remove_ticker("MSFT")
        await asyncio.sleep(0.6)
        await sim.stop()
        await asyncio.wait_for(task, timeout=2.0)

    await run_and_remove()
    assert "MSFT" not in sim._states
