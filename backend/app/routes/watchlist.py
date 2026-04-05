from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app import database as db

router = APIRouter()


class AddTickerRequest(BaseModel):
    ticker: str


async def _build_watchlist_response(cache) -> list[dict]:
    tickers = await db.get_watchlist()
    result = []
    for ticker in sorted(tickers):
        point = await cache.get(ticker)
        entry = {"ticker": ticker}
        if point:
            change_pct = (
                ((point.price - point.prev_price) / point.prev_price * 100)
                if point.prev_price
                else 0.0
            )
            entry.update(
                {
                    "price": round(point.price, 4),
                    "prev_price": round(point.prev_price, 4),
                    "change_pct": round(change_pct, 4),
                }
            )
        else:
            entry.update({"price": None, "prev_price": None, "change_pct": None})
        result.append(entry)
    return result


@router.get("/watchlist")
async def get_watchlist(request: Request):
    cache = request.app.state.cache
    return await _build_watchlist_response(cache)


@router.post("/watchlist")
async def add_ticker(request: Request, body: AddTickerRequest):
    ticker = body.ticker.strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="Ticker must not be empty")
    await db.add_ticker(ticker)
    market_source = request.app.state.market_source
    market_source.add_ticker(ticker)
    cache = request.app.state.cache
    return await _build_watchlist_response(cache)


@router.delete("/watchlist/{ticker}")
async def remove_ticker(request: Request, ticker: str):
    ticker = ticker.strip().upper()
    current = set(await db.get_watchlist())
    if ticker not in current:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} not in watchlist")
    await db.remove_ticker(ticker)
    market_source = request.app.state.market_source
    market_source.remove_ticker(ticker)
    cache = request.app.state.cache
    await cache.remove(ticker)
    return {"ok": True}
