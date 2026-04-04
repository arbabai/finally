# Market Data Interface Design

This document defines the unified Python interface for market data in FinAlly. The backend selects between the Massive API client and the built-in simulator based on the `MASSIVE_API_KEY` environment variable. All downstream code is agnostic to the source.

---

## Architecture

```
┌────────────────────────────┐
│   MarketDataSource (ABC)   │  ← Abstract interface
└────────────┬───────────────┘
             │ implemented by
    ┌────────┴─────────┐
    │                  │
┌───▼──────────┐  ┌────▼───────────┐
│ MassiveClient│  │ MarketSimulator│
│ (real data)  │  │  (GBM-based)   │
└──────────────┘  └────────────────┘
             │
    ┌────────▼───────────────┐
    │   PriceCache           │  ← In-memory, shared state
    │   {ticker: PricePoint} │
    └────────────────────────┘
             │
    ┌────────▼───────────────┐
    │   SSE Stream           │  ← Reads cache, pushes to clients
    └────────────────────────┘
```

### Factory Selection

```python
# backend/app/market/factory.py
import os
from .interface import MarketDataSource
from .massive_client import MassiveClient
from .simulator import MarketSimulator

def create_market_source() -> MarketDataSource:
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if api_key:
        return MassiveClient(api_key=api_key)
    return MarketSimulator()
```

---

## Data Models

```python
# backend/app/market/models.py
from dataclasses import dataclass, field
from typing import Literal
import time

@dataclass
class PricePoint:
    ticker: str
    price: float
    prev_price: float          # Price from the previous update cycle
    timestamp: float           # Unix timestamp (seconds)
    change_direction: Literal["up", "down", "flat"]

    @classmethod
    def from_prices(cls, ticker: str, price: float, prev_price: float) -> "PricePoint":
        if price > prev_price:
            direction = "up"
        elif price < prev_price:
            direction = "down"
        else:
            direction = "flat"
        return cls(
            ticker=ticker,
            price=price,
            prev_price=prev_price,
            timestamp=time.time(),
            change_direction=direction,
        )

    def to_sse_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "price": self.price,
            "prev_price": self.prev_price,
            "timestamp": self.timestamp,
            "direction": self.change_direction,
        }
```

---

## Abstract Interface

```python
# backend/app/market/interface.py
from abc import ABC, abstractmethod

class MarketDataSource(ABC):
    """
    Abstract base class for market data providers.

    Concrete implementations (MassiveClient, MarketSimulator) must:
    - Implement start() to begin updating the shared price cache
    - Implement stop() to cleanly shut down
    - Implement add_ticker() / remove_ticker() for watchlist management
    - Write PricePoint objects to the shared PriceCache
    """

    @abstractmethod
    async def start(self, cache: "PriceCache") -> None:
        """
        Begin the background polling/simulation loop.
        Writes price updates to `cache` continuously.
        This method runs forever until stop() is called.
        """
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully stop the background task."""
        ...

    @abstractmethod
    def add_ticker(self, ticker: str) -> None:
        """
        Add a ticker to the active set.
        The source should begin including it in subsequent updates.
        Thread-safe — may be called from any coroutine.
        """
        ...

    @abstractmethod
    def remove_ticker(self, ticker: str) -> None:
        """
        Remove a ticker from the active set.
        Subsequent updates will not include it.
        Thread-safe — may be called from any coroutine.
        """
        ...

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Human-readable name for logging (e.g. 'MassiveAPI', 'Simulator')."""
        ...
```

---

## Price Cache

The cache is a simple in-memory store shared between the market data background task and the SSE streaming endpoint. Both the simulator and the Massive client write to it; SSE handlers read from it.

```python
# backend/app/market/cache.py
import asyncio
from typing import Optional
from .models import PricePoint

class PriceCache:
    """
    Thread-safe in-memory store for the latest price of each ticker.
    Written by the market data source, read by SSE stream handlers.
    """

    def __init__(self):
        self._data: dict[str, PricePoint] = {}
        self._lock = asyncio.Lock()
        # Subscribers: SSE handlers register here to receive push notifications
        self._subscribers: list[asyncio.Queue] = []

    async def update(self, point: PricePoint) -> None:
        """Update price for a ticker and notify all SSE subscribers."""
        async with self._lock:
            self._data[point.ticker] = point
        # Non-blocking fan-out to subscribers
        for queue in self._subscribers:
            try:
                queue.put_nowait(point)
            except asyncio.QueueFull:
                pass  # Slow consumer — skip this update

    async def get(self, ticker: str) -> Optional[PricePoint]:
        async with self._lock:
            return self._data.get(ticker)

    async def get_all(self) -> dict[str, PricePoint]:
        async with self._lock:
            return dict(self._data)

    async def remove(self, ticker: str) -> None:
        async with self._lock:
            self._data.pop(ticker, None)

    def subscribe(self) -> asyncio.Queue:
        """Register an SSE handler to receive price updates. Returns a Queue."""
        queue: asyncio.Queue[PricePoint] = asyncio.Queue(maxsize=100)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Deregister an SSE handler when the client disconnects."""
        try:
            self._subscribers.remove(queue)
        except ValueError:
            pass
```

---

## MassiveClient Implementation

```python
# backend/app/market/massive_client.py
import asyncio
import httpx
from .interface import MarketDataSource
from .cache import PriceCache
from .models import PricePoint

class MassiveClient(MarketDataSource):
    """
    Polls the Massive (Polygon.io) REST API for real stock prices.
    Uses the /v2/snapshot endpoint — one call retrieves all watched tickers.

    Poll interval is 15 seconds by default (4 calls/min — safe for free tier).
    Paid plans can reduce this to 2-5 seconds.
    """

    BASE_URL = "https://api.massive.com"

    def __init__(self, api_key: str, poll_interval: float = 15.0):
        self._api_key = api_key
        self._poll_interval = poll_interval
        self._tickers: set[str] = set()
        self._lock = asyncio.Lock()
        self._running = False
        self._task: asyncio.Task | None = None

    @property
    def source_name(self) -> str:
        return "MassiveAPI"

    def add_ticker(self, ticker: str) -> None:
        self._tickers.add(ticker.upper())

    def remove_ticker(self, ticker: str) -> None:
        self._tickers.discard(ticker.upper())

    async def start(self, cache: PriceCache) -> None:
        self._running = True
        print(f"[MassiveAPI] Starting poller (interval={self._poll_interval}s)")
        async with httpx.AsyncClient(timeout=10.0) as client:
            while self._running:
                tickers = list(self._tickers)
                if tickers:
                    try:
                        prices = await self._fetch_prices(client, tickers)
                        for ticker, (price, prev_price) in prices.items():
                            point = PricePoint.from_prices(ticker, price, prev_price)
                            await cache.update(point)
                    except httpx.HTTPStatusError as e:
                        print(f"[MassiveAPI] HTTP error {e.response.status_code}: {e}")
                    except Exception as e:
                        print(f"[MassiveAPI] Poll error: {e}")
                await asyncio.sleep(self._poll_interval)

    async def stop(self) -> None:
        self._running = False

    async def _fetch_prices(
        self,
        client: httpx.AsyncClient,
        tickers: list[str],
    ) -> dict[str, tuple[float, float]]:
        """
        Fetch latest prices. Returns {ticker: (current_price, prev_close)}.
        """
        resp = await client.get(
            f"{self.BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers",
            params={"tickers": ",".join(tickers), "apiKey": self._api_key},
        )
        resp.raise_for_status()
        data = resp.json()

        result: dict[str, tuple[float, float]] = {}
        for snapshot in data.get("tickers", []):
            ticker = snapshot["ticker"]
            # Current price: prefer lastTrade.p (real-time), fall back to day.c
            last_trade = snapshot.get("lastTrade", {})
            price = last_trade.get("p") or snapshot.get("day", {}).get("c")
            # Previous price: previous day's close
            prev_price = snapshot.get("prevDay", {}).get("c") or price
            if price is not None:
                result[ticker] = (float(price), float(prev_price))

        return result
```

---

## Application Lifecycle

The market data source is started as a FastAPI lifespan event and injected as app state:

```python
# backend/app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from .market.factory import create_market_source
from .market.cache import PriceCache
from .database import get_watchlist_tickers  # reads DB on startup

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    cache = PriceCache()
    source = create_market_source()

    # Seed tickers from the persisted watchlist
    for ticker in await get_watchlist_tickers():
        source.add_ticker(ticker)

    # Start market data background task
    import asyncio
    task = asyncio.create_task(source.start(cache))

    app.state.cache = cache
    app.state.market_source = source

    yield  # Application runs here

    # --- Shutdown ---
    await source.stop()
    task.cancel()

app = FastAPI(lifespan=lifespan)
```

---

## SSE Streaming Endpoint

The SSE endpoint reads from the price cache via subscriptions:

```python
# backend/app/routes/stream.py
import asyncio
import json
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from ..market.cache import PriceCache

router = APIRouter()

@router.get("/api/stream/prices")
async def stream_prices(request: Request):
    cache: PriceCache = request.app.state.cache

    async def event_generator():
        queue = cache.subscribe()
        try:
            # Send current state immediately on connect
            all_prices = await cache.get_all()
            for point in all_prices.values():
                yield f"data: {json.dumps(point.to_sse_dict())}\n\n"

            # Stream subsequent updates
            while not await request.is_disconnected():
                try:
                    point = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(point.to_sse_dict())}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat to keep connection alive
                    yield ": heartbeat\n\n"
        finally:
            cache.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
```

---

## Watchlist Integration

When the watchlist changes via API, the market source is notified:

```python
# backend/app/routes/watchlist.py
from fastapi import APIRouter, Request

router = APIRouter()

@router.post("/api/watchlist")
async def add_ticker(body: dict, request: Request):
    ticker = body["ticker"].strip().upper()
    # ... save to DB ...
    request.app.state.market_source.add_ticker(ticker)
    return {"ticker": ticker}

@router.delete("/api/watchlist/{ticker}")
async def remove_ticker(ticker: str, request: Request):
    ticker = ticker.upper()
    # ... remove from DB ...
    request.app.state.market_source.remove_ticker(ticker)
    await request.app.state.cache.remove(ticker)
    return {"ticker": ticker}
```

---

## File Structure

```
backend/
└── app/
    └── market/
        ├── __init__.py
        ├── interface.py        # MarketDataSource ABC
        ├── models.py           # PricePoint dataclass
        ├── cache.py            # PriceCache (shared state)
        ├── simulator.py        # GBM-based simulator
        ├── massive_client.py   # Massive REST API client
        └── factory.py          # create_market_source()
```

---

## Behavioral Contract

Both implementations must satisfy these invariants:

1. **`start()` blocks until `stop()` is called.** It is always run as an `asyncio.Task`.
2. **`add_ticker()` / `remove_ticker()` are synchronous and thread-safe.** They may be called while `start()` is running.
3. **Unknown tickers are silently ignored** — the Massive API omits them; the simulator starts generating prices for any ticker it receives.
4. **Updates are written to `PriceCache`** via `cache.update()` — never returned directly.
5. **`stop()` may be called multiple times** without error.
6. **No exceptions escape `start()`** — all errors are caught, logged, and the loop continues.
