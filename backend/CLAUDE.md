# Backend — Claude Reference

## Stack

- Python 3.12+, FastAPI, uv (`pyproject.toml`)
- SQLite via `aiosqlite`, served at `db/finally.db` (volume-mounted in Docker)
- Dev dependencies: pytest, pytest-asyncio, pytest-mock, respx — install with `uv sync --extra dev`
- Run tests: `uv run pytest`

---

## What's Built

### `app/market/` — Market Data Layer (complete, 75/75 tests pass)

Pluggable price feed: simulator by default, Massive API if `MASSIVE_API_KEY` is set.

| Module | What it does |
|--------|-------------|
| `models.py` | `PricePoint` dataclass + `to_sse_dict()` |
| `interface.py` | `MarketDataSource` ABC |
| `cache.py` | `PriceCache` — shared store with asyncio.Queue fan-out for SSE |
| `simulator.py` | GBM simulator, 500 ms ticks, sector correlation, random events |
| `massive_client.py` | Polls `api.massive.com/v2/snapshot` every 15 s |
| `factory.py` | `create_market_source()` — reads `MASSIVE_API_KEY` env var |

Key contracts: `start(cache)` blocks until `stop()` is called; all exceptions are caught inside `start()`; `add_ticker`/`remove_ticker` are synchronous and safe to call at runtime.

---

## What's NOT Built Yet

Everything else. The backend entry point (`app/main.py`), database schema/init, and all API routes still need to be created per `PLAN.md`.

### Still to build (in order of dependency):

1. **Database layer** (`app/database.py` or `app/db/`)
   - SQLite init with lazy schema creation (DDL embedded in Python, no SQL files)
   - Tables: `users_profile`, `watchlist`, `positions`, `trades`, `portfolio_snapshots`, `chat_messages`
   - Seed data: default user ($10,000 cash), 10 default watchlist tickers
   - `get_watchlist_tickers()` needed by lifespan to seed the market source

2. **FastAPI app + lifespan** (`app/main.py`)
   - Lifespan: init DB → create market source → seed tickers → start background task
   - Mount static frontend files from `/app/static/`
   - Register all routers

3. **API routes**
   - `GET /api/stream/prices` — SSE, uses `cache.subscribe()` / `cache.unsubscribe()`
   - `GET /api/watchlist`, `POST /api/watchlist`, `DELETE /api/watchlist/{ticker}`
   - `GET /api/portfolio`, `POST /api/portfolio/trade`, `GET /api/portfolio/history`
   - `POST /api/chat` — LLM via LiteLLM → OpenRouter (`openrouter/openai/gpt-oss-120b`)
   - `GET /api/health`

4. **Background task** — portfolio snapshot recorder (every 30 s + after each trade)

5. **LLM integration** (`app/chat.py`)
   - LiteLLM + OpenRouter, structured output schema: `{message, trades[], watchlist_changes[]}`
   - Auto-executes trades/watchlist changes from LLM response
   - Mock mode when `LLM_MOCK=true`

---

## Environment Variables

```
OPENROUTER_API_KEY   # required for chat
MASSIVE_API_KEY      # optional; empty = use simulator
MASSIVE_POLL_INTERVAL # optional; default 15.0 s
LLM_MOCK             # set "true" for deterministic test responses
```

---

## Key Design Rules

- All DDL embedded in Python — no external SQL files
- All tables have `user_id TEXT` defaulting to `"default"` (single-user MVP)
- Market orders only — instant fill at current cache price, no order book
- Error responses use FastAPI's default `{"detail": "..."}` shape — no custom envelope
- The market source and cache live on `app.state` — pass via `request.app.state`
