"""Tests for the SQLite database layer."""

import os
import tempfile

import pytest

from app.database import (
    add_ticker,
    execute_trade,
    get_chat_messages,
    get_portfolio_history,
    get_positions,
    get_trade_history,
    get_user,
    get_watchlist,
    init_db,
    record_portfolio_snapshot,
    remove_ticker,
    reset_portfolio,
    save_chat_message,
    set_db_path,
)


@pytest.fixture(autouse=True)
async def _fresh_db(tmp_path):
    """Each test gets a fresh, empty SQLite database."""
    db_file = str(tmp_path / "test.db")
    set_db_path(db_file)
    await init_db()
    yield
    # cleanup handled by tmp_path


# ---------------------------------------------------------------------------
# Schema & seed
# ---------------------------------------------------------------------------


async def test_schema_creation_from_scratch(tmp_path):
    """init_db creates all tables on a brand-new DB file."""
    db_file = str(tmp_path / "fresh.db")
    set_db_path(db_file)
    await init_db()
    assert os.path.exists(db_file)

    # Can call every query function without error
    user = await get_user()
    assert user["cash_balance"] == 10_000.0


async def test_seed_data_present():
    """Default user and 10 watchlist tickers exist after init."""
    user = await get_user()
    assert user["id"] == "default"
    assert user["cash_balance"] == 10_000.0

    tickers = await get_watchlist()
    assert len(tickers) == 10
    assert "AAPL" in tickers
    assert "NFLX" in tickers


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------


async def test_add_ticker():
    tickers = await get_watchlist()
    assert "PYPL" not in tickers

    await add_ticker("PYPL")
    tickers = await get_watchlist()
    assert "PYPL" in tickers


async def test_add_ticker_idempotent():
    await add_ticker("PYPL")
    await add_ticker("PYPL")  # should not raise
    tickers = await get_watchlist()
    assert tickers.count("PYPL") == 1


async def test_add_ticker_uppercases():
    await add_ticker("pypl")
    tickers = await get_watchlist()
    assert "PYPL" in tickers


async def test_remove_ticker():
    await remove_ticker("AAPL")
    tickers = await get_watchlist()
    assert "AAPL" not in tickers


async def test_remove_nonexistent_ticker():
    await remove_ticker("XXXX")  # should not raise


# ---------------------------------------------------------------------------
# Trade execution — buy
# ---------------------------------------------------------------------------


async def test_buy_updates_cash_and_positions():
    trade = await execute_trade("AAPL", "buy", 10, 150.0)
    assert trade["ticker"] == "AAPL"
    assert trade["side"] == "buy"
    assert trade["quantity"] == 10
    assert trade["price"] == 150.0

    user = await get_user()
    assert user["cash_balance"] == pytest.approx(10_000.0 - 1_500.0)

    positions = await get_positions()
    aapl = [p for p in positions if p["ticker"] == "AAPL"][0]
    assert aapl["quantity"] == 10
    assert aapl["avg_cost"] == pytest.approx(150.0)


async def test_buy_updates_avg_cost():
    await execute_trade("AAPL", "buy", 10, 100.0)
    await execute_trade("AAPL", "buy", 10, 200.0)

    positions = await get_positions()
    aapl = [p for p in positions if p["ticker"] == "AAPL"][0]
    assert aapl["quantity"] == 20
    assert aapl["avg_cost"] == pytest.approx(150.0)


async def test_buy_insufficient_cash():
    with pytest.raises(ValueError, match="Insufficient cash"):
        await execute_trade("AAPL", "buy", 1000, 100.0)  # $100k > $10k


# ---------------------------------------------------------------------------
# Trade execution — sell
# ---------------------------------------------------------------------------


async def test_sell_updates_cash_and_positions():
    await execute_trade("AAPL", "buy", 10, 100.0)
    await execute_trade("AAPL", "sell", 5, 120.0)

    user = await get_user()
    # Started at 10k, spent 1000 buying, gained 600 selling
    assert user["cash_balance"] == pytest.approx(10_000.0 - 1_000.0 + 600.0)

    positions = await get_positions()
    aapl = [p for p in positions if p["ticker"] == "AAPL"][0]
    assert aapl["quantity"] == 5


async def test_sell_entire_position_removes_row():
    await execute_trade("AAPL", "buy", 10, 100.0)
    await execute_trade("AAPL", "sell", 10, 120.0)

    positions = await get_positions()
    assert all(p["ticker"] != "AAPL" for p in positions)


async def test_sell_insufficient_shares():
    with pytest.raises(ValueError, match="Insufficient shares"):
        await execute_trade("AAPL", "sell", 10, 100.0)


async def test_sell_more_than_owned():
    await execute_trade("AAPL", "buy", 5, 100.0)
    with pytest.raises(ValueError, match="Insufficient shares"):
        await execute_trade("AAPL", "sell", 10, 100.0)


# ---------------------------------------------------------------------------
# Trade history
# ---------------------------------------------------------------------------


async def test_trade_history():
    await execute_trade("AAPL", "buy", 10, 100.0)
    await execute_trade("MSFT", "buy", 5, 200.0)

    history = await get_trade_history()
    assert len(history) == 2
    assert history[0]["ticker"] == "AAPL"
    assert history[1]["ticker"] == "MSFT"


# ---------------------------------------------------------------------------
# Portfolio snapshots
# ---------------------------------------------------------------------------


async def test_record_and_get_portfolio_history():
    await record_portfolio_snapshot(10_000.0)
    await record_portfolio_snapshot(10_500.0)

    history = await get_portfolio_history()
    assert len(history) == 2
    assert history[0]["total_value"] == pytest.approx(10_000.0)
    assert history[1]["total_value"] == pytest.approx(10_500.0)


# ---------------------------------------------------------------------------
# Chat messages
# ---------------------------------------------------------------------------


async def test_save_and_get_chat_messages():
    await save_chat_message("user", "Hello")
    await save_chat_message("assistant", "Hi there!", '{"trades": []}')

    msgs = await get_chat_messages()
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "Hello"
    assert msgs[0]["actions"] is None
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["actions"] == '{"trades": []}'


async def test_chat_messages_limit():
    for i in range(30):
        await save_chat_message("user", f"msg {i}")

    msgs = await get_chat_messages(limit=5)
    assert len(msgs) == 5
    # Should be the 5 most recent in chronological order
    assert msgs[0]["content"] == "msg 25"
    assert msgs[4]["content"] == "msg 29"


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


async def test_reset_portfolio():
    await execute_trade("AAPL", "buy", 10, 100.0)
    await record_portfolio_snapshot(9_000.0)
    await save_chat_message("user", "test")

    await reset_portfolio()

    user = await get_user()
    assert user["cash_balance"] == pytest.approx(10_000.0)
    assert await get_positions() == []
    assert await get_trade_history() == []
    assert await get_portfolio_history() == []
    assert await get_chat_messages() == []

    # Watchlist should remain intact
    tickers = await get_watchlist()
    assert len(tickers) == 10
