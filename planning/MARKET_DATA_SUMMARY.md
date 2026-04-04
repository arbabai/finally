# Market Data Backend — What Was Built

## Status: Complete and tested (75/75 tests pass)

---

## What Was Implemented

The entire `backend/app/market/` package: a pluggable market data layer that can run either a built-in simulator or the Massive (Polygon.io) REST API, selected at startup via environment variable.

### Modules

| File | Purpose |
|------|---------|
| `models.py` | `PricePoint` dataclass — the single data type flowing through the system |
| `interface.py` | `MarketDataSource` ABC — the contract both implementations satisfy |
| `cache.py` | `PriceCache` — shared in-memory store with SSE subscriber fan-out |
| `simulator.py` | `MarketSimulator` — GBM-based price simulation, no external dependencies |
| `massive_client.py` | `MassiveClient` — polls `api.massive.com` REST API |
| `factory.py` | `create_market_source()` — env-driven selection of which implementation to use |
| `__init__.py` | Re-exports `PriceCache`, `PricePoint`, `create_market_source` |

### How It Works

```
MASSIVE_API_KEY set? ──yes──▶ MassiveClient (polls every 15 s)
        │
        no
        ▼
  MarketSimulator (GBM ticks every 500 ms)
        │
        ▼ cache.update(PricePoint)
    PriceCache  ──fan-out──▶  asyncio.Queue  ──▶  SSE /api/stream/prices
```

- One `asyncio.Task` runs `source.start(cache)` for the app lifetime (managed by FastAPI lifespan).
- All downstream code (SSE, portfolio, chat) reads only from `PriceCache` — never from the source directly.
- `add_ticker` / `remove_ticker` are synchronous and safe to call while the loop is running.

### Simulator Details

- Discrete-time Geometric Brownian Motion: `S(t+dt) = S(t) × exp((μ − σ²/2)dt + σ√dt × Z)`
- Per-ticker volatility (σ) and drift (μ) — higher-beta tickers (TSLA σ=0.55, NVDA σ=0.50) move more
- Sector correlation: tech stocks share a common shock with ρ=0.6
- Random market events: 0.2% chance per tick per ticker of a 2–5% jump
- Seed prices approximate real-world 2024 values (AAPL $190, NVDA $880, etc.)
- Default seed price $100 for any unknown ticker

### Default Tickers (seeded from DB on startup)

AAPL, GOOGL, MSFT, AMZN, TSLA, NVDA, META, JPM, V, NFLX

---

## Tests

75 unit tests across 5 files in `backend/tests/market/`:

| File | Count | Coverage |
|------|-------|----------|
| `test_models.py` | 10 | PricePoint construction, directions, SSE serialisation |
| `test_cache.py` | 13 | reads, writes, remove, subscribe/unsubscribe, slow consumer |
| `test_factory.py` | 9 | all env var combinations, poll interval override |
| `test_simulator.py` | 23 | watchlist management, GBM correctness, lifecycle |
| `test_massive_client.py` | 20 | HTTP parsing, error handling, prev_price tracking |

Run with: `uv run pytest tests/market/ -v` (requires `uv sync --extra dev` first)

---

## Issues Found and Fixed (post-review)

| Issue | Fix |
|-------|-----|
| `MarketSimulator.start()` had no exception handling — violated interface contract | Wrapped loop body in `try/except Exception` with `[Simulator]` log |
| `test_start_tracks_prev_price` was timing-dependent (too many polls in sleep window) | Replaced sleep-based approach with `asyncio.Event` signalled after exactly 2 polls |

---

## Integration Points for Next Phases

The market data layer is fully self-contained. Other backend modules interact with it via:

```python
# FastAPI lifespan (backend/app/main.py — not yet built)
source = create_market_source()
source.add_ticker(ticker)
task = asyncio.create_task(source.start(cache))
app.state.cache = cache
app.state.market_source = source

# Watchlist routes — when user adds/removes tickers
request.app.state.market_source.add_ticker(ticker)
request.app.state.market_source.remove_ticker(ticker)
await request.app.state.cache.remove(ticker)

# SSE streaming route — subscribe to live updates
queue = cache.subscribe()       # before streaming
cache.unsubscribe(queue)        # on disconnect

# Any route needing current prices
price_point = await cache.get("AAPL")
all_prices  = await cache.get_all()
```

Reference docs in `planning/archive/` for deeper detail on the design decisions.
