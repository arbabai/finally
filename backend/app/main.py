import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import database as db
from app.market.factory import create_market_source
from app.market.cache import PriceCache
from app.routes import health, stream, watchlist, portfolio, chat


async def _snapshot_loop(cache: PriceCache):
    """Record portfolio value every 30 seconds."""
    while True:
        await asyncio.sleep(30)
        try:
            user = await db.get_user()
            cash = user["cash_balance"]
            total = cash
            for pos in await db.get_positions():
                point = await cache.get(pos["ticker"])
                price = point.price if point else pos["avg_cost"]
                total += price * pos["quantity"]
            await db.record_portfolio_snapshot(total)
        except Exception as e:
            print(f"[Snapshot] Error recording snapshot: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Initialize database
    await db.init_db()

    # 2. Create market source
    market_source = create_market_source()

    # 3. Load watchlist tickers and register them
    tickers = await db.get_watchlist()
    for ticker in tickers:
        market_source.add_ticker(ticker)

    # 4. Create price cache
    cache = PriceCache()

    # 5. Store on app.state
    app.state.market_source = market_source
    app.state.cache = cache

    # 6. Start background tasks
    market_task = asyncio.create_task(market_source.start(cache))
    snapshot_task = asyncio.create_task(_snapshot_loop(cache))

    yield

    # Shutdown
    await market_source.stop()
    snapshot_task.cancel()
    try:
        await snapshot_task
    except asyncio.CancelledError:
        pass
    try:
        await market_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="FinAlly", lifespan=lifespan)

# Register API routers
app.include_router(health.router, prefix="/api")
app.include_router(stream.router, prefix="/api")
app.include_router(watchlist.router, prefix="/api")
app.include_router(portfolio.router, prefix="/api")
app.include_router(chat.router, prefix="/api")

# Mount static files (Next.js export) — must be last so /api routes take priority
static_dir = Path("/app/static")
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
