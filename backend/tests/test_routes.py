"""Tests for API route handlers.

Uses httpx AsyncClient with a test app that has mocked
database functions and pre-populated app.state.
"""

from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from app.market.cache import PriceCache
from app.market.models import PricePoint
from app.routes import health, stream, watchlist, portfolio, chat


# ---------- fixtures ----------

@pytest.fixture
def price_cache():
    return PriceCache()


@pytest.fixture
def mock_market_source():
    source = MagicMock()
    source.add_ticker = MagicMock()
    source.remove_ticker = MagicMock()
    return source


@pytest.fixture
def test_app(price_cache, mock_market_source):
    app = FastAPI()
    app.include_router(health.router, prefix="/api")
    app.include_router(stream.router, prefix="/api")
    app.include_router(watchlist.router, prefix="/api")
    app.include_router(portfolio.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    app.state.cache = price_cache
    app.state.market_source = mock_market_source
    return app


@pytest.fixture
async def client(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
async def seed_cache(price_cache):
    """Put known prices into the cache."""
    await price_cache.update(PricePoint.from_prices("AAPL", 190.50, 189.25))
    await price_cache.update(PricePoint.from_prices("GOOGL", 175.00, 174.50))


# ---------- health ----------

async def test_health(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------- watchlist ----------

@patch("app.routes.watchlist.db.get_watchlist", new_callable=AsyncMock)
async def test_get_watchlist(mock_get, client):
    mock_get.return_value = ["AAPL", "GOOGL"]
    resp = await client.get("/api/watchlist")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 2
    tickers = {item["ticker"] for item in data}
    assert tickers == {"AAPL", "GOOGL"}


@patch("app.routes.watchlist.db.get_watchlist", new_callable=AsyncMock)
@patch("app.routes.watchlist.db.add_ticker", new_callable=AsyncMock)
async def test_add_ticker(mock_add, mock_get, client, mock_market_source):
    mock_get.return_value = ["AAPL", "TSLA"]
    resp = await client.post("/api/watchlist", json={"ticker": "tsla"})
    assert resp.status_code == 200
    mock_add.assert_called_once_with("TSLA")
    mock_market_source.add_ticker.assert_called_once_with("TSLA")


@patch("app.routes.watchlist.db.get_watchlist", new_callable=AsyncMock)
@patch("app.routes.watchlist.db.remove_ticker", new_callable=AsyncMock)
async def test_delete_ticker(mock_remove, mock_get, client, mock_market_source):
    mock_get.return_value = ["AAPL", "GOOGL"]
    resp = await client.delete("/api/watchlist/AAPL")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    mock_remove.assert_called_once_with("AAPL")
    mock_market_source.remove_ticker.assert_called_once_with("AAPL")


@patch("app.routes.watchlist.db.get_watchlist", new_callable=AsyncMock)
async def test_delete_ticker_not_found(mock_get, client):
    mock_get.return_value = ["AAPL"]
    resp = await client.delete("/api/watchlist/XYZ")
    assert resp.status_code == 404


# ---------- portfolio ----------

@patch("app.routes.portfolio.db.get_positions", new_callable=AsyncMock)
@patch("app.routes.portfolio.db.get_user", new_callable=AsyncMock)
async def test_get_portfolio(mock_user, mock_pos, client):
    mock_user.return_value = {"cash_balance": 10000.0}
    mock_pos.return_value = [
        {"ticker": "AAPL", "quantity": 10, "avg_cost": 185.0},
    ]
    resp = await client.get("/api/portfolio")
    assert resp.status_code == 200
    data = resp.json()
    assert "cash_balance" in data
    assert "positions" in data
    assert "total_value" in data
    assert "unrealized_pnl" in data
    assert data["cash_balance"] == 10000.0
    assert len(data["positions"]) == 1
    pos = data["positions"][0]
    assert pos["ticker"] == "AAPL"
    assert pos["current_price"] == 190.5


@patch("app.routes.portfolio.db.record_portfolio_snapshot", new_callable=AsyncMock)
@patch("app.routes.portfolio.db.get_positions", new_callable=AsyncMock)
@patch("app.routes.portfolio.db.get_user", new_callable=AsyncMock)
@patch("app.routes.portfolio.db.execute_trade", new_callable=AsyncMock)
async def test_trade_buy(mock_exec, mock_user, mock_pos, mock_snap, client):
    mock_user.return_value = {"cash_balance": 9048.0}
    mock_pos.return_value = [
        {"ticker": "AAPL", "quantity": 5, "avg_cost": 190.50},
    ]
    resp = await client.post(
        "/api/portfolio/trade",
        json={"ticker": "AAPL", "side": "buy", "quantity": 5},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["positions"][0]["quantity"] == 5
    mock_exec.assert_called_once()
    mock_snap.assert_called_once()


@patch("app.routes.portfolio.db.execute_trade", new_callable=AsyncMock)
async def test_trade_sell_insufficient(mock_exec, client):
    mock_exec.side_effect = ValueError("Insufficient shares")
    resp = await client.post(
        "/api/portfolio/trade",
        json={"ticker": "AAPL", "side": "sell", "quantity": 100},
    )
    assert resp.status_code == 400
    assert "Insufficient shares" in resp.json()["detail"]


@patch("app.routes.portfolio.db.get_portfolio_history", new_callable=AsyncMock)
async def test_portfolio_history(mock_snaps, client):
    mock_snaps.return_value = [
        {"total_value": 10000.0, "recorded_at": "2026-01-01T00:00:00"},
        {"total_value": 10050.0, "recorded_at": "2026-01-01T00:00:30"},
    ]
    resp = await client.get("/api/portfolio/history")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 2


# ---------- chat ----------

@patch("app.chat.process_chat", new_callable=AsyncMock)
async def test_chat(mock_handle, client):
    mock_handle.return_value = {
        "message": "Hello! I can help you trade.",
        "trades_executed": [],
        "watchlist_changes_executed": [],
    }
    resp = await client.post("/api/chat", json={"message": "hi"})
    assert resp.status_code == 200
    data = resp.json()
    assert "message" in data


async def test_chat_empty_message(client):
    resp = await client.post("/api/chat", json={"message": "  "})
    assert resp.status_code == 400
