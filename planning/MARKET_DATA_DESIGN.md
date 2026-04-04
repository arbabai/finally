# Market Data Backend — Implementation Design

This document is the authoritative implementation guide for all market data functionality in FinAlly. It synthesises the three source documents (`MARKET_INTERFACE.md`, `MARKET_SIMULATOR.md`, `MASSIVE_API.md`) into a single reference with full code for every module.

---

## 1. Architecture Overview

```
┌────────────────────────────────────────────────────────────────┐
│  FastAPI app (lifespan)                                        │
│                                                                │
│  ┌──────────────────────────────────┐                          │
│  │  MarketDataSource (ABC)          │  Chosen at startup via   │
│  │  ┌─────────────┐ ┌────────────┐ │  MASSIVE_API_KEY env var │
│  │  │MassiveClient│ │MarketSimul.│ │                          │
│  │  └──────┬──────┘ └─────┬──────┘ │                          │
│  └─────────┼──────────────┼────────┘                          │
│            └──────┬───────┘                                    │
│                   ▼                                            │
│            PriceCache                                          │
│            {ticker → PricePoint}          asyncio.Queue fan-out│
│                   │                                            │
│                   ▼                                            │
│            GET /api/stream/prices  ←── SSE clients            │
└────────────────────────────────────────────────────────────────┘
```

**Key invariants:**
- One background `asyncio.Task` runs `source.start(cache)` for the lifetime of the app.
- All downstream code (SSE, portfolio, chat) reads only from `PriceCache` — never from the source directly.
- `add_ticker` / `remove_ticker` are synchronous and safe to call while the loop is running.

---

## 2. File Structure

```
backend/
└── app/
    └── market/
        ├── __init__.py          # Re-exports: PriceCache, PricePoint, create_market_source
        ├── models.py            # PricePoint dataclass
        ├── interface.py         # MarketDataSource ABC
        ├── cache.py             # PriceCache — shared in-memory state
        ├── simulator.py         # GBM-based simulator
        ├── massive_client.py    # Massive (Polygon.io) REST API client
        └── factory.py           # create_market_source() — env-driven selection
```

---

## 3. Data Model

```python
# backend/app/market/models.py
from dataclasses import dataclass
from typing import Literal
import time


@dataclass
class PricePoint:
    ticker: str
    price: float
    prev_price: float          # Price from the immediately preceding update
    timestamp: float           # Unix epoch seconds (float)
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
        """Serialised form sent over the SSE stream."""
        return {
            "ticker": self.ticker,
            "price": round(self.price, 4),
            "prev_price": round(self.prev_price, 4),
            "timestamp": self.timestamp,
            "direction": self.change_direction,
        }
```

---

## 4. Abstract Interface

```python
# backend/app/market/interface.py
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .cache import PriceCache


class MarketDataSource(ABC):
    """
    Unified interface for market data providers.

    Concrete implementations: MassiveClient, MarketSimulator.

    Contract:
    - start(cache) blocks indefinitely, writing PricePoints to cache.
    - stop() causes start() to return cleanly.
    - add_ticker / remove_ticker are synchronous, safe to call while running.
    - No exception may escape start() — all errors are caught and logged.
    """

    @abstractmethod
    async def start(self, cache: "PriceCache") -> None:
        """Run the price-update loop. Call as an asyncio.Task."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Signal the loop to stop. Idempotent."""
        ...

    @abstractmethod
    def add_ticker(self, ticker: str) -> None:
        """Include ticker in subsequent updates. Normalises to uppercase."""
        ...

    @abstractmethod
    def remove_ticker(self, ticker: str) -> None:
        """Stop emitting updates for ticker. No-op if unknown."""
        ...

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Human-readable name for log messages."""
        ...
```

---

## 5. Price Cache

The cache is the single shared-state object between the market data background task and the SSE streaming endpoint. It uses an asyncio `Lock` for safe concurrent reads/writes and a fan-out queue list to push updates to each active SSE connection.

```python
# backend/app/market/cache.py
import asyncio
from typing import Optional
from .models import PricePoint


class PriceCache:
    """
    In-memory store for the latest PricePoint per ticker.

    Written by: MarketSimulator / MassiveClient (one background task).
    Read by:    SSE stream handlers (many concurrent readers).

    Subscribers receive a copy of every PricePoint via asyncio.Queue.
    Slow consumers that fall behind (QueueFull) silently drop updates —
    they will catch up on the next tick.
    """

    def __init__(self) -> None:
        self._data: dict[str, PricePoint] = {}
        self._lock = asyncio.Lock()
        self._subscribers: list[asyncio.Queue[PricePoint]] = []

    # ------------------------------------------------------------------ writes

    async def update(self, point: PricePoint) -> None:
        """Store latest price and fan-out to all SSE subscribers."""
        async with self._lock:
            self._data[point.ticker] = point
        for queue in self._subscribers:
            try:
                queue.put_nowait(point)
            except asyncio.QueueFull:
                pass  # slow consumer — drop this tick, it will catch up

    async def remove(self, ticker: str) -> None:
        """Evict a ticker (called when it is removed from the watchlist)."""
        async with self._lock:
            self._data.pop(ticker, None)

    # ------------------------------------------------------------------ reads

    async def get(self, ticker: str) -> Optional[PricePoint]:
        async with self._lock:
            return self._data.get(ticker)

    async def get_all(self) -> dict[str, PricePoint]:
        async with self._lock:
            return dict(self._data)

    # ----------------------------------------------------------- subscriptions

    def subscribe(self) -> asyncio.Queue[PricePoint]:
        """
        Register an SSE handler. Returns a queue that receives every update.
        Call unsubscribe() when the client disconnects.
        """
        queue: asyncio.Queue[PricePoint] = asyncio.Queue(maxsize=200)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[PricePoint]) -> None:
        """Deregister an SSE handler."""
        try:
            self._subscribers.remove(queue)
        except ValueError:
            pass
```

---

## 6. Market Simulator

### Mathematical Foundation

Stock prices are modelled with discrete-time Geometric Brownian Motion:

```
S(t + dt) = S(t) × exp( (μ − σ²/2) × dt  +  σ × √dt × Z )
```

| Symbol | Meaning |
|--------|---------|
| `S(t)` | Current price |
| `μ` | Annualized drift (e.g. 0.08 = 8% expected annual return) |
| `σ` | Annualized volatility (e.g. 0.25 = 25%) |
| `dt` | Time step in years (`0.5s ÷ 31,536,000 s/yr ≈ 1.587e-8`) |
| `Z` | Standard normal random variable |

At `dt = 0.5s` the drift term is ~0.000001 per tick; volatility drives all visible movement.  
For AAPL (σ=0.25): per-tick std ≈ 0.25 × √(1.587e-8) ≈ **0.10% per tick**.

### Correlated Noise

Stocks in the same sector share a common shock:

```
Z_ticker = ρ × Z_sector  +  √(1 − ρ²) × Z_individual
```

One `Z_sector` is drawn per sector group per tick. `ρ = 0.6` for named sectors.

Sector assignments:
- `tech`: AAPL, MSFT, GOOGL, AMZN, META, NVDA, NFLX
- `finance`: JPM, V
- `auto`: TSLA
- `default`: any unknown ticker (ρ = 0.3 against a shared "default" shock)

### Full Implementation

```python
# backend/app/market/simulator.py
import asyncio
import math
import random
import time
from dataclasses import dataclass

from .cache import PriceCache
from .interface import MarketDataSource
from .models import PricePoint

# ------------------------------------------------------------------ constants

TICK_INTERVAL: float = 0.5          # seconds between price updates
SECONDS_PER_YEAR: float = 365.25 * 24 * 3600
DT: float = TICK_INTERVAL / SECONDS_PER_YEAR   # ~1.587e-8 years per tick

SECTOR_CORRELATION: float = 0.6     # ρ for named sector groups
EVENT_PROBABILITY: float = 0.002    # 0.2% chance of a market event per ticker per tick
EVENT_MIN: float = 0.02             # minimum event move (2%)
EVENT_MAX: float = 0.05             # maximum event move (5%)

SEED_PRICES: dict[str, float] = {
    "AAPL":  190.0,
    "GOOGL": 175.0,
    "MSFT":  420.0,
    "AMZN":  185.0,
    "TSLA":  175.0,
    "NVDA":  880.0,
    "META":  500.0,
    "JPM":   200.0,
    "V":     275.0,
    "NFLX":  630.0,
}

DEFAULT_SEED_PRICE: float = 100.0


@dataclass
class TickerConfig:
    sigma: float    # annualized volatility
    mu: float       # annualized drift
    sector: str     # sector group for correlated noise


TICKER_CONFIGS: dict[str, TickerConfig] = {
    "AAPL":  TickerConfig(sigma=0.25, mu=0.08, sector="tech"),
    "GOOGL": TickerConfig(sigma=0.28, mu=0.07, sector="tech"),
    "MSFT":  TickerConfig(sigma=0.24, mu=0.09, sector="tech"),
    "AMZN":  TickerConfig(sigma=0.30, mu=0.08, sector="tech"),
    "TSLA":  TickerConfig(sigma=0.55, mu=0.05, sector="auto"),
    "NVDA":  TickerConfig(sigma=0.50, mu=0.12, sector="tech"),
    "META":  TickerConfig(sigma=0.35, mu=0.07, sector="tech"),
    "JPM":   TickerConfig(sigma=0.20, mu=0.06, sector="finance"),
    "V":     TickerConfig(sigma=0.18, mu=0.07, sector="finance"),
    "NFLX":  TickerConfig(sigma=0.38, mu=0.06, sector="tech"),
}

DEFAULT_CONFIG = TickerConfig(sigma=0.30, mu=0.07, sector="default")


# ------------------------------------------------------------------ state

@dataclass
class TickerState:
    ticker: str
    config: TickerConfig
    price: float        # current simulated price
    prev_price: float   # price from the last tick (used for direction flash)


# ------------------------------------------------------------------ simulator

class MarketSimulator(MarketDataSource):
    """
    GBM-based stock price simulator. Runs entirely in-process.
    Implements MarketDataSource — drop-in replacement for MassiveClient.
    """

    def __init__(self) -> None:
        self._states: dict[str, TickerState] = {}
        self._running: bool = False

    @property
    def source_name(self) -> str:
        return "Simulator"

    # -------------------------------------------------- watchlist management

    def add_ticker(self, ticker: str) -> None:
        ticker = ticker.upper()
        if ticker not in self._states:
            config = TICKER_CONFIGS.get(ticker, DEFAULT_CONFIG)
            seed = SEED_PRICES.get(ticker, DEFAULT_SEED_PRICE)
            self._states[ticker] = TickerState(
                ticker=ticker,
                config=config,
                price=seed,
                prev_price=seed,
            )

    def remove_ticker(self, ticker: str) -> None:
        self._states.pop(ticker.upper(), None)

    # -------------------------------------------------- lifecycle

    async def start(self, cache: PriceCache) -> None:
        self._running = True
        print(f"[Simulator] Starting — {len(self._states)} tickers")
        while self._running:
            tick_start = time.monotonic()

            # Snapshot state dict to avoid mutation-during-iteration issues
            states = dict(self._states)
            self._tick(states)

            for state in states.values():
                # Propagate updated prices back to the live dict
                if state.ticker in self._states:
                    self._states[state.ticker].price = state.price
                    self._states[state.ticker].prev_price = state.prev_price
                point = PricePoint.from_prices(
                    ticker=state.ticker,
                    price=state.price,
                    prev_price=state.prev_price,
                )
                await cache.update(point)

            elapsed = time.monotonic() - tick_start
            await asyncio.sleep(max(0.0, TICK_INTERVAL - elapsed))

    async def stop(self) -> None:
        self._running = False

    # -------------------------------------------------- core GBM step

    def _tick(self, states: dict[str, TickerState]) -> None:
        """Advance all tickers by one dt. Mutates states in-place."""
        # One sector shock per active sector group
        sectors = {s.config.sector for s in states.values()}
        sector_shocks: dict[str, float] = {
            sector: random.gauss(0, 1) for sector in sectors
        }

        for state in states.values():
            state.prev_price = state.price

            # Correlated noise: blend sector shock with individual shock
            z_sector = sector_shocks[state.config.sector]
            z_individual = random.gauss(0, 1)
            rho = SECTOR_CORRELATION
            z = rho * z_sector + math.sqrt(1.0 - rho ** 2) * z_individual

            # GBM step
            sigma = state.config.sigma
            mu = state.config.mu
            drift = (mu - 0.5 * sigma ** 2) * DT
            diffusion = sigma * math.sqrt(DT) * z
            state.price *= math.exp(drift + diffusion)

            # Random market event
            if random.random() < EVENT_PROBABILITY:
                magnitude = random.uniform(EVENT_MIN, EVENT_MAX)
                direction = random.choice((-1, 1))
                state.price *= (1.0 + direction * magnitude)

            # Price floor — GBM can't reach 0 mathematically, but guard anyway
            state.price = max(state.price, 0.01)
```

### Expected Simulation Quality (AAPL, 500 ms ticks)

| Metric | Expected range |
|--------|---------------|
| Per-tick price change | ±0.05% – 0.15% |
| Random event frequency | ~1 per 8 min per ticker |
| Random event magnitude | 2% – 5% |
| Price drift over 8 hours | Within ±3% of seed (typical) |

---

## 7. Massive API Client

Uses the Massive (Polygon.io) v2 snapshot endpoint to poll real stock prices. One HTTP request fetches all watched tickers simultaneously.

### API Basics

```
GET https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers
    ?tickers=AAPL,MSFT,GOOGL
    &apiKey=YOUR_KEY
```

**Price extraction priority:**
1. `tickers[].lastTrade.p` — real-time last trade price (market hours)
2. `tickers[].day.c` — today's close (fallback for after-hours / missing data)

**Poll interval:** 15 s by default (4 calls/min; free tier allows 5/min).

### Full Implementation

```python
# backend/app/market/massive_client.py
import asyncio
import httpx

from .cache import PriceCache
from .interface import MarketDataSource
from .models import PricePoint

BASE_URL = "https://api.massive.com"


class MassiveClient(MarketDataSource):
    """
    Polls the Massive REST API for live stock prices.
    One request per poll interval fetches all watched tickers.

    Default poll_interval=15.0 s is safe for the free tier (5 req/min limit).
    Paid plans can set poll_interval=2.0 or lower.
    """

    def __init__(self, api_key: str, poll_interval: float = 15.0) -> None:
        self._api_key = api_key
        self._poll_interval = poll_interval
        self._tickers: set[str] = set()
        self._running: bool = False
        # Track previous prices across polls for change_direction
        self._prev_prices: dict[str, float] = {}

    @property
    def source_name(self) -> str:
        return "MassiveAPI"

    # -------------------------------------------------- watchlist management

    def add_ticker(self, ticker: str) -> None:
        self._tickers.add(ticker.upper())

    def remove_ticker(self, ticker: str) -> None:
        ticker = ticker.upper()
        self._tickers.discard(ticker)
        self._prev_prices.pop(ticker, None)

    # -------------------------------------------------- lifecycle

    async def start(self, cache: PriceCache) -> None:
        self._running = True
        print(f"[MassiveAPI] Starting poller — interval={self._poll_interval}s")
        async with httpx.AsyncClient(timeout=10.0) as client:
            while self._running:
                tickers = list(self._tickers)
                if tickers:
                    try:
                        prices = await self._fetch_prices(client, tickers)
                        for ticker, price in prices.items():
                            prev = self._prev_prices.get(ticker, price)
                            point = PricePoint.from_prices(ticker, price, prev)
                            await cache.update(point)
                            self._prev_prices[ticker] = price
                    except httpx.HTTPStatusError as e:
                        status = e.response.status_code
                        if status == 403:
                            print("[MassiveAPI] Invalid API key — check MASSIVE_API_KEY")
                        elif status == 429:
                            print("[MassiveAPI] Rate limited — consider increasing poll_interval")
                        else:
                            print(f"[MassiveAPI] HTTP {status}: {e}")
                    except httpx.TimeoutException:
                        print("[MassiveAPI] Request timed out — will retry")
                    except Exception as e:
                        print(f"[MassiveAPI] Unexpected error: {e}")
                await asyncio.sleep(self._poll_interval)

    async def stop(self) -> None:
        self._running = False

    # -------------------------------------------------- HTTP fetch

    async def _fetch_prices(
        self,
        client: httpx.AsyncClient,
        tickers: list[str],
    ) -> dict[str, float]:
        """
        Fetch current prices for the given tickers.
        Returns {ticker: price}. Tickers with no data are omitted.
        """
        resp = await client.get(
            f"{BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers",
            params={
                "tickers": ",".join(tickers),
                "apiKey": self._api_key,
            },
        )
        resp.raise_for_status()
        data = resp.json()

        prices: dict[str, float] = {}
        for snapshot in data.get("tickers", []):
            ticker = snapshot.get("ticker")
            if not ticker:
                continue
            # Prefer lastTrade.p (real-time); fall back to day.c
            last_trade = snapshot.get("lastTrade") or {}
            price = last_trade.get("p") or (snapshot.get("day") or {}).get("c")
            if price is not None:
                prices[ticker] = float(price)

        return prices
```

### Massive API Response Reference

```json
{
  "status": "OK",
  "tickers": [
    {
      "ticker": "AAPL",
      "lastTrade": { "p": 189.70, "s": 100, "t": 1712345678123456789 },
      "day":       { "o": 187.20, "h": 190.50, "l": 186.80, "c": 189.70, "v": 52341234 },
      "prevDay":   { "c": 187.20 }
    }
  ]
}
```

### Error Handling Reference

| HTTP status | Meaning | Action taken |
|-------------|---------|--------------|
| 200 `status: "OK"` | Success | Parse `tickers` array |
| 200 `status: "ERROR"` | API-level error | Logged; loop continues |
| 400 | Bad ticker format | Logged; loop continues |
| 403 | Invalid API key | Logged; loop continues (fatal misconfiguration) |
| 429 | Rate limit exceeded | Logged; loop sleeps and retries |
| 5xx | Massive server error | Logged; loop retries on next interval |
| Timeout | Network issue | Logged; loop retries on next interval |

---

## 8. Factory — Environment-Driven Selection

```python
# backend/app/market/factory.py
import os
from .interface import MarketDataSource
from .massive_client import MassiveClient
from .simulator import MarketSimulator


def create_market_source() -> MarketDataSource:
    """
    Select and instantiate the appropriate MarketDataSource.

    Rules:
    - MASSIVE_API_KEY set and non-empty → MassiveClient (real data)
    - MASSIVE_API_KEY absent or empty   → MarketSimulator (default)
    """
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if api_key:
        poll_interval = float(os.environ.get("MASSIVE_POLL_INTERVAL", "15.0"))
        print(f"[Market] Using Massive API (poll_interval={poll_interval}s)")
        return MassiveClient(api_key=api_key, poll_interval=poll_interval)
    print("[Market] Using built-in simulator (no MASSIVE_API_KEY)")
    return MarketSimulator()
```

---

## 9. FastAPI Integration

### App Lifespan

```python
# backend/app/main.py  (relevant section)
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from .market.factory import create_market_source
from .market.cache import PriceCache
from .database import get_watchlist_tickers   # returns list[str] from DB


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────
    cache = PriceCache()
    source = create_market_source()

    # Seed tickers from the persisted watchlist (DB is already initialised)
    for ticker in await get_watchlist_tickers():
        source.add_ticker(ticker)

    # Run market data loop as a fire-and-forget background task
    task = asyncio.create_task(source.start(cache))

    app.state.cache = cache
    app.state.market_source = source

    yield   # ── Application serves requests here ──────────────────────

    # ── Shutdown ─────────────────────────────────────────────────────
    await source.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(lifespan=lifespan)
```

### SSE Streaming Endpoint

```python
# backend/app/routes/stream.py
import asyncio
import json
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from ..market.cache import PriceCache

router = APIRouter()

HEARTBEAT_INTERVAL = 30.0  # seconds — keeps connection alive through proxies


@router.get("/api/stream/prices")
async def stream_prices(request: Request):
    cache: PriceCache = request.app.state.cache

    async def event_generator():
        queue = cache.subscribe()
        try:
            # On connect: immediately send the current snapshot so the UI
            # populates instantly rather than waiting for the next tick.
            all_prices = await cache.get_all()
            for point in all_prices.values():
                yield f"data: {json.dumps(point.to_sse_dict())}\n\n"

            # Stream subsequent updates
            while not await request.is_disconnected():
                try:
                    point = await asyncio.wait_for(
                        queue.get(), timeout=HEARTBEAT_INTERVAL
                    )
                    yield f"data: {json.dumps(point.to_sse_dict())}\n\n"
                except asyncio.TimeoutError:
                    # SSE comment — invisible to JS EventSource, keeps TCP alive
                    yield ": heartbeat\n\n"
        finally:
            cache.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering
        },
    )
```

**SSE event payload (JSON):**
```json
{
  "ticker": "AAPL",
  "price": 190.23,
  "prev_price": 190.15,
  "timestamp": 1712345678.123,
  "direction": "up"
}
```

### Watchlist Routes — Market Source Integration

```python
# backend/app/routes/watchlist.py  (relevant section)
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

router = APIRouter()


class AddTickerBody(BaseModel):
    ticker: str


@router.post("/api/watchlist")
async def add_to_watchlist(body: AddTickerBody, request: Request):
    ticker = body.ticker.strip().upper()
    if not ticker:
        raise HTTPException(status_code=422, detail="ticker must not be empty")

    # 1. Persist to DB (raises 409 if already present)
    # await db_add_ticker(ticker)

    # 2. Tell the market source to start tracking it
    request.app.state.market_source.add_ticker(ticker)

    return {"ticker": ticker}


@router.delete("/api/watchlist/{ticker}")
async def remove_from_watchlist(ticker: str, request: Request):
    ticker = ticker.upper()

    # 1. Remove from DB
    # await db_remove_ticker(ticker)

    # 2. Stop tracking and evict from cache
    request.app.state.market_source.remove_ticker(ticker)
    await request.app.state.cache.remove(ticker)

    return {"ticker": ticker}
```

---

## 10. Package `__init__.py`

```python
# backend/app/market/__init__.py
from .cache import PriceCache
from .models import PricePoint
from .factory import create_market_source

__all__ = ["PriceCache", "PricePoint", "create_market_source"]
```

---

## 11. Unit Tests

```python
# backend/tests/market/test_simulator.py
import asyncio
import pytest
from app.market.simulator import MarketSimulator
from app.market.cache import PriceCache
from app.market.models import PricePoint


def test_add_remove_ticker():
    sim = MarketSimulator()
    sim.add_ticker("AAPL")
    assert "AAPL" in sim._states
    sim.remove_ticker("AAPL")
    assert "AAPL" not in sim._states


def test_add_ticker_normalises_case():
    sim = MarketSimulator()
    sim.add_ticker("aapl")
    assert "AAPL" in sim._states


def test_seed_price_used():
    sim = MarketSimulator()
    sim.add_ticker("AAPL")
    assert sim._states["AAPL"].price == 190.0


def test_unknown_ticker_gets_default_seed():
    sim = MarketSimulator()
    sim.add_ticker("ZZZZ")
    assert sim._states["ZZZZ"].price == 100.0


def test_tick_changes_price():
    sim = MarketSimulator()
    sim.add_ticker("AAPL")
    initial = sim._states["AAPL"].price
    states = dict(sim._states)
    sim._tick(states)
    assert states["AAPL"].prev_price == initial
    assert states["AAPL"].price > 0


def test_tick_sets_prev_price_chain():
    """prev_price on tick N equals price on tick N-1."""
    sim = MarketSimulator()
    sim.add_ticker("MSFT")
    states = dict(sim._states)
    sim._tick(states)
    price_after_tick1 = states["MSFT"].price
    sim._tick(states)
    assert states["MSFT"].prev_price == price_after_tick1


def test_price_floor():
    """Price must always stay above zero."""
    sim = MarketSimulator()
    sim.add_ticker("AAPL")
    states = dict(sim._states)
    # Run many ticks — price must never go negative
    for _ in range(1000):
        sim._tick(states)
    assert states["AAPL"].price >= 0.01


@pytest.mark.asyncio
async def test_start_writes_to_cache():
    sim = MarketSimulator()
    sim.add_ticker("AAPL")
    cache = PriceCache()

    async def run():
        await asyncio.wait_for(sim.start(cache), timeout=1.2)

    try:
        await run()
    except asyncio.TimeoutError:
        pass  # expected — stop() was not called

    result = await cache.get("AAPL")
    assert result is not None
    assert isinstance(result, PricePoint)
    assert result.price > 0


# backend/tests/market/test_cache.py
import asyncio
import pytest
from app.market.cache import PriceCache
from app.market.models import PricePoint


@pytest.mark.asyncio
async def test_update_and_get():
    cache = PriceCache()
    point = PricePoint.from_prices("AAPL", 190.0, 189.5)
    await cache.update(point)
    result = await cache.get("AAPL")
    assert result is not None
    assert result.price == 190.0


@pytest.mark.asyncio
async def test_remove():
    cache = PriceCache()
    await cache.update(PricePoint.from_prices("AAPL", 190.0, 189.5))
    await cache.remove("AAPL")
    assert await cache.get("AAPL") is None


@pytest.mark.asyncio
async def test_subscriber_receives_update():
    cache = PriceCache()
    queue = cache.subscribe()
    point = PricePoint.from_prices("TSLA", 175.0, 174.0)
    await cache.update(point)
    received = queue.get_nowait()
    assert received.ticker == "TSLA"
    cache.unsubscribe(queue)


@pytest.mark.asyncio
async def test_slow_subscriber_drops_update():
    """A full queue should not block the update path."""
    cache = PriceCache()
    queue = cache.subscribe()
    # Fill the queue to capacity
    for i in range(200):
        await cache.update(PricePoint.from_prices("AAPL", 190.0 + i, 190.0 + i - 1))
    # One more update must not raise
    await cache.update(PricePoint.from_prices("AAPL", 999.0, 998.0))


# backend/tests/market/test_models.py
from app.market.models import PricePoint


def test_direction_up():
    p = PricePoint.from_prices("X", 101.0, 100.0)
    assert p.change_direction == "up"


def test_direction_down():
    p = PricePoint.from_prices("X", 99.0, 100.0)
    assert p.change_direction == "down"


def test_direction_flat():
    p = PricePoint.from_prices("X", 100.0, 100.0)
    assert p.change_direction == "flat"


def test_to_sse_dict_keys():
    p = PricePoint.from_prices("AAPL", 190.0, 189.5)
    d = p.to_sse_dict()
    assert set(d.keys()) == {"ticker", "price", "prev_price", "timestamp", "direction"}
```

---

## 12. Behavioural Contract Summary

Both `MassiveClient` and `MarketSimulator` must satisfy these invariants — the rest of the backend depends on them:

| # | Rule |
|---|------|
| 1 | `start(cache)` **blocks** until `stop()` is called. Always run as `asyncio.create_task`. |
| 2 | `stop()` is **idempotent** — safe to call multiple times. |
| 3 | `add_ticker` / `remove_ticker` are **synchronous** and safe to call while `start()` is running. |
| 4 | All ticker symbols are stored and compared **uppercase**. |
| 5 | Unknown tickers are **silently accepted** — the simulator starts generating prices; Massive API omits them from the response without error. |
| 6 | All price updates are delivered to `cache` via `await cache.update(point)`. The source never returns data directly. |
| 7 | **No exception escapes `start()`**. All errors are caught, logged with a `[SourceName]` prefix, and the loop continues. |
| 8 | After `remove_ticker`, the source emits **no further updates** for that ticker, and the caller is responsible for calling `await cache.remove(ticker)`. |
