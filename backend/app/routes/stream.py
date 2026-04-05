import asyncio
import json

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from app import database as db

router = APIRouter()


async def _price_generator(request: Request):
    cache = request.app.state.cache
    queue = cache.subscribe()
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                point = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            # Only send updates for tickers in the user's current watchlist
            watchlist_tickers = set(await db.get_watchlist())
            if point.ticker in watchlist_tickers:
                yield {
                    "event": "price",
                    "data": json.dumps(point.to_sse_dict()),
                }
    finally:
        cache.unsubscribe(queue)


@router.get("/stream/prices")
async def stream_prices(request: Request):
    return EventSourceResponse(_price_generator(request))
