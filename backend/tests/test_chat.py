"""Tests for the LLM chat integration module."""

import json
import os
import tempfile

import pytest

from app.chat import (
    MOCK_RESPONSE,
    ChatResponse,
    TradeAction,
    WatchlistChange,
    build_portfolio_context,
    process_chat,
)
from app.database import init_db, set_db_path, get_chat_messages, get_positions, get_watchlist
from app.market.cache import PriceCache
from app.market.models import PricePoint


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _temp_db(tmp_path):
    """Point the DB at a fresh temp file for every test."""
    db_path = str(tmp_path / "test.db")
    set_db_path(db_path)
    yield


@pytest.fixture
def cache():
    return PriceCache()


@pytest.fixture
def mock_env(monkeypatch):
    """Set LLM_MOCK=true for tests."""
    monkeypatch.setenv("LLM_MOCK", "true")


async def _seed_cache(cache: PriceCache) -> None:
    """Populate cache with prices for default tickers."""
    tickers = {
        "AAPL": 190.0, "GOOGL": 175.0, "MSFT": 420.0, "AMZN": 185.0,
        "TSLA": 250.0, "NVDA": 880.0, "META": 500.0, "JPM": 195.0,
        "V": 280.0, "NFLX": 620.0,
    }
    for ticker, price in tickers.items():
        await cache.update(PricePoint.from_prices(ticker, price, price - 1.0))


# ---------------------------------------------------------------------------
# ChatResponse parsing tests
# ---------------------------------------------------------------------------


class TestChatResponseParsing:
    def test_full_response(self):
        raw = json.dumps({
            "message": "Bought AAPL",
            "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 10}],
            "watchlist_changes": [{"ticker": "PYPL", "action": "add"}],
        })
        resp = ChatResponse.model_validate_json(raw)
        assert resp.message == "Bought AAPL"
        assert len(resp.trades) == 1
        assert resp.trades[0].ticker == "AAPL"
        assert len(resp.watchlist_changes) == 1

    def test_message_only(self):
        raw = json.dumps({"message": "Hello!"})
        resp = ChatResponse.model_validate_json(raw)
        assert resp.message == "Hello!"
        assert resp.trades == []
        assert resp.watchlist_changes == []

    def test_empty_arrays(self):
        raw = json.dumps({"message": "Hi", "trades": [], "watchlist_changes": []})
        resp = ChatResponse.model_validate_json(raw)
        assert resp.trades == []
        assert resp.watchlist_changes == []

    def test_missing_message_raises(self):
        raw = json.dumps({"trades": []})
        with pytest.raises(Exception):
            ChatResponse.model_validate_json(raw)

    def test_multiple_trades(self):
        raw = json.dumps({
            "message": "Executed trades",
            "trades": [
                {"ticker": "AAPL", "side": "buy", "quantity": 5},
                {"ticker": "GOOGL", "side": "sell", "quantity": 3},
            ],
        })
        resp = ChatResponse.model_validate_json(raw)
        assert len(resp.trades) == 2
        assert resp.trades[1].side == "sell"


# ---------------------------------------------------------------------------
# Mock mode tests
# ---------------------------------------------------------------------------


class TestMockMode:
    async def test_mock_returns_deterministic_response(self, cache, mock_env):
        await init_db()
        await _seed_cache(cache)
        result = await process_chat("hello", cache)
        assert result["message"] == MOCK_RESPONSE.message
        assert result["trades_executed"] == []
        assert result["watchlist_changes_executed"] == []
        assert result["errors"] == []

    async def test_mock_mode_env_var_case_insensitive(self, cache, monkeypatch):
        monkeypatch.setenv("LLM_MOCK", "True")
        await init_db()
        await _seed_cache(cache)
        result = await process_chat("test", cache)
        assert result["message"] == MOCK_RESPONSE.message


# ---------------------------------------------------------------------------
# Portfolio context tests
# ---------------------------------------------------------------------------


class TestBuildPortfolioContext:
    async def test_context_includes_cash(self, cache):
        await init_db()
        await _seed_cache(cache)
        ctx = await build_portfolio_context(cache)
        assert "Cash: $10,000.00" in ctx

    async def test_context_includes_watchlist(self, cache):
        await init_db()
        await _seed_cache(cache)
        ctx = await build_portfolio_context(cache)
        assert "AAPL" in ctx
        assert "$190.00" in ctx

    async def test_context_no_positions(self, cache):
        await init_db()
        await _seed_cache(cache)
        ctx = await build_portfolio_context(cache)
        assert "Positions: none" in ctx


# ---------------------------------------------------------------------------
# process_chat integration tests (mock mode)
# ---------------------------------------------------------------------------


class TestProcessChat:
    async def test_saves_messages_to_db(self, cache, mock_env):
        await init_db()
        await _seed_cache(cache)
        await process_chat("What should I buy?", cache)
        messages = await get_chat_messages()
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "What should I buy?"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == MOCK_RESPONSE.message

    async def test_assistant_message_has_actions(self, cache, mock_env):
        await init_db()
        await _seed_cache(cache)
        await process_chat("test", cache)
        messages = await get_chat_messages()
        assistant_msg = messages[1]
        actions = json.loads(assistant_msg["actions"])
        assert "trades_executed" in actions
        assert "watchlist_changes_executed" in actions
        assert "errors" in actions

    async def test_return_shape(self, cache, mock_env):
        await init_db()
        await _seed_cache(cache)
        result = await process_chat("hi", cache)
        assert "message" in result
        assert "trades_executed" in result
        assert "watchlist_changes_executed" in result
        assert "errors" in result


# ---------------------------------------------------------------------------
# Trade auto-execution tests
# ---------------------------------------------------------------------------


class TestTradeAutoExecution:
    async def test_executes_buy_trade(self, cache, monkeypatch):
        """Simulate LLM returning a buy trade and verify it executes."""
        monkeypatch.setenv("LLM_MOCK", "false")
        await init_db()
        await _seed_cache(cache)

        fake_response = ChatResponse(
            message="Buying 5 shares of AAPL",
            trades=[TradeAction(ticker="AAPL", side="buy", quantity=5)],
            watchlist_changes=[],
        )

        async def mock_call_llm(context, history, user_message):
            return fake_response

        monkeypatch.setattr("app.chat._call_llm", mock_call_llm)

        result = await process_chat("buy 5 AAPL", cache)
        assert len(result["trades_executed"]) == 1
        assert result["trades_executed"][0]["ticker"] == "AAPL"
        assert result["trades_executed"][0]["side"] == "buy"
        assert result["trades_executed"][0]["quantity"] == 5

        # Verify position was created
        positions = await get_positions()
        assert any(p["ticker"] == "AAPL" for p in positions)

    async def test_trade_error_insufficient_cash(self, cache, monkeypatch):
        """Verify error when buying more than cash allows."""
        monkeypatch.setenv("LLM_MOCK", "false")
        await init_db()
        await _seed_cache(cache)

        # Try to buy way more than $10k allows
        fake_response = ChatResponse(
            message="Buying lots",
            trades=[TradeAction(ticker="AAPL", side="buy", quantity=1000)],
            watchlist_changes=[],
        )

        async def mock_call_llm(context, history, user_message):
            return fake_response

        monkeypatch.setattr("app.chat._call_llm", mock_call_llm)

        result = await process_chat("buy 1000 AAPL", cache)
        assert len(result["trades_executed"]) == 1
        assert result["trades_executed"][0]["status"] == "error"
        assert len(result["errors"]) == 1
        assert "Insufficient cash" in result["errors"][0]

    async def test_trade_no_price_available(self, cache, monkeypatch):
        """Verify error when ticker has no price in cache."""
        monkeypatch.setenv("LLM_MOCK", "false")
        await init_db()

        fake_response = ChatResponse(
            message="Buying XYZ",
            trades=[TradeAction(ticker="XYZ", side="buy", quantity=1)],
            watchlist_changes=[],
        )

        async def mock_call_llm(context, history, user_message):
            return fake_response

        monkeypatch.setattr("app.chat._call_llm", mock_call_llm)

        result = await process_chat("buy XYZ", cache)
        assert len(result["errors"]) == 1
        assert "No price available" in result["errors"][0]


# ---------------------------------------------------------------------------
# Watchlist change auto-execution tests
# ---------------------------------------------------------------------------


class TestWatchlistAutoExecution:
    async def test_adds_ticker_to_watchlist(self, cache, monkeypatch):
        monkeypatch.setenv("LLM_MOCK", "false")
        await init_db()
        await _seed_cache(cache)

        fake_response = ChatResponse(
            message="Added PYPL",
            trades=[],
            watchlist_changes=[WatchlistChange(ticker="PYPL", action="add")],
        )

        async def mock_call_llm(context, history, user_message):
            return fake_response

        monkeypatch.setattr("app.chat._call_llm", mock_call_llm)

        result = await process_chat("add PYPL", cache)
        assert len(result["watchlist_changes_executed"]) == 1
        assert result["watchlist_changes_executed"][0]["ticker"] == "PYPL"
        assert result["watchlist_changes_executed"][0]["action"] == "add"
        assert result["watchlist_changes_executed"][0]["status"] == "success"

        watchlist = await get_watchlist()
        assert "PYPL" in watchlist

    async def test_removes_ticker_from_watchlist(self, cache, monkeypatch):
        monkeypatch.setenv("LLM_MOCK", "false")
        await init_db()
        await _seed_cache(cache)

        fake_response = ChatResponse(
            message="Removed NFLX",
            trades=[],
            watchlist_changes=[WatchlistChange(ticker="NFLX", action="remove")],
        )

        async def mock_call_llm(context, history, user_message):
            return fake_response

        monkeypatch.setattr("app.chat._call_llm", mock_call_llm)

        result = await process_chat("remove NFLX", cache)
        assert len(result["watchlist_changes_executed"]) == 1

        watchlist = await get_watchlist()
        assert "NFLX" not in watchlist

    async def test_calls_market_source_on_add(self, cache, monkeypatch):
        monkeypatch.setenv("LLM_MOCK", "false")
        await init_db()
        await _seed_cache(cache)

        added_tickers = []

        class FakeMarketSource:
            def add_ticker(self, ticker):
                added_tickers.append(ticker)

            def remove_ticker(self, ticker):
                pass

        fake_response = ChatResponse(
            message="Added PYPL",
            trades=[],
            watchlist_changes=[WatchlistChange(ticker="PYPL", action="add")],
        )

        async def mock_call_llm(context, history, user_message):
            return fake_response

        monkeypatch.setattr("app.chat._call_llm", mock_call_llm)

        await process_chat("add PYPL", cache, market_source=FakeMarketSource())
        assert "PYPL" in added_tickers

    async def test_calls_market_source_on_remove(self, cache, monkeypatch):
        monkeypatch.setenv("LLM_MOCK", "false")
        await init_db()
        await _seed_cache(cache)

        removed_tickers = []

        class FakeMarketSource:
            def add_ticker(self, ticker):
                pass

            def remove_ticker(self, ticker):
                removed_tickers.append(ticker)

        fake_response = ChatResponse(
            message="Removed NFLX",
            trades=[],
            watchlist_changes=[WatchlistChange(ticker="NFLX", action="remove")],
        )

        async def mock_call_llm(context, history, user_message):
            return fake_response

        monkeypatch.setattr("app.chat._call_llm", mock_call_llm)

        await process_chat("remove NFLX", cache, market_source=FakeMarketSource())
        assert "NFLX" in removed_tickers
