from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

from app import database as db

router = APIRouter()

DEFAULT_WATCHLIST = [
    "AAPL", "GOOGL", "MSFT", "AMZN", "TSLA",
    "NVDA", "META", "JPM", "V", "NFLX",
]


class TradeRequest(BaseModel):
    ticker: str
    quantity: float
    side: str

    @field_validator("side")
    @classmethod
    def validate_side(cls, v: str) -> str:
        v = v.lower()
        if v not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        return v

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("quantity must be positive")
        return v


async def _build_portfolio_response(cache) -> dict:
    user = await db.get_user()
    positions_raw = await db.get_positions()
    cash = user["cash_balance"]
    positions = []
    total_positions_value = 0.0
    total_unrealized_pnl = 0.0

    for pos in positions_raw:
        point = await cache.get(pos["ticker"])
        current_price = point.price if point else pos["avg_cost"]
        unrealized_pnl = (current_price - pos["avg_cost"]) * pos["quantity"]
        pct_change = (
            ((current_price - pos["avg_cost"]) / pos["avg_cost"] * 100)
            if pos["avg_cost"]
            else 0.0
        )
        position_value = current_price * pos["quantity"]
        total_positions_value += position_value
        total_unrealized_pnl += unrealized_pnl
        positions.append(
            {
                "ticker": pos["ticker"],
                "quantity": pos["quantity"],
                "avg_cost": round(pos["avg_cost"], 4),
                "current_price": round(current_price, 4),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "pct_change": round(pct_change, 2),
            }
        )

    return {
        "cash_balance": round(cash, 2),
        "positions": positions,
        "total_value": round(cash + total_positions_value, 2),
        "unrealized_pnl": round(total_unrealized_pnl, 2),
    }


@router.get("/portfolio")
async def get_portfolio(request: Request):
    cache = request.app.state.cache
    return await _build_portfolio_response(cache)


@router.post("/portfolio/trade")
async def trade(request: Request, body: TradeRequest):
    cache = request.app.state.cache
    ticker = body.ticker.strip().upper()

    # Get current price from cache
    point = await cache.get(ticker)
    if not point:
        raise HTTPException(status_code=400, detail=f"No price available for {ticker}")

    try:
        await db.execute_trade(
            ticker=ticker,
            side=body.side,
            quantity=body.quantity,
            price=point.price,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Record snapshot immediately after trade
    portfolio_resp = await _build_portfolio_response(cache)
    await db.record_portfolio_snapshot(portfolio_resp["total_value"])

    return portfolio_resp


@router.get("/portfolio/history")
async def portfolio_history():
    snapshots = await db.get_portfolio_history()
    return snapshots


@router.post("/portfolio/reset")
async def reset_portfolio(request: Request):
    await db.reset_portfolio()
    # Re-seed watchlist
    market_source = request.app.state.market_source
    for ticker in DEFAULT_WATCHLIST:
        await db.add_ticker(ticker)
        market_source.add_ticker(ticker)
    cache = request.app.state.cache
    return await _build_portfolio_response(cache)
