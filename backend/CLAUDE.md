# Backend — Claude Reference

## Stack

- Python 3.12+, FastAPI, uv (`pyproject.toml`)
- SQLite via `aiosqlite`, served at `db/finally.db` (volume-mounted in Docker)
- Dev dependencies: pytest, pytest-asyncio, pytest-mock, respx — install with `uv sync --extra dev`
- Run tests: `uv run pytest` (125 tests, all passing)

---

## Directory Structure

```
backend/
├── app/
│   ├── main.py           # FastAPI app, lifespan, router registration
│   ├── database.py       # SQLite layer — schema, init, all async CRUD helpers
│   ├── chat.py           # LLM integration (LiteLLM → OpenRouter / mock mode)
│   ├── market/
│   │   ├── interface.py  # MarketDataSource ABC
│   │   ├── models.py     # PricePoint dataclass + to_sse_dict()
│   │   ├── cache.py      # PriceCache — in-memory store with asyncio.Queue fan-out
│   │   ├── simulator.py  # GBM simulator, 500ms ticks, sector correlation
│   │   ├── massive_client.py  # Polygon.io REST polling (optional)
│   │   └── factory.py    # create_market_source() — reads MASSIVE_API_KEY env var
│   └── routes/
│       ├── health.py     # GET /api/health
│       ├── stream.py     # GET /api/stream/prices (SSE)
│       ├── watchlist.py  # GET/POST /api/watchlist, DELETE /api/watchlist/{ticker}
│       ├── portfolio.py  # GET/POST /api/portfolio, GET /api/portfolio/history, POST /api/portfolio/reset, POST /api/portfolio/trade
│       └── chat.py       # POST /api/chat
└── tests/
    ├── market/           # 75 tests — simulator, cache, models, Massive client, factory
    ├── test_database.py  # 19 tests — schema, seed, CRUD, trade validation
    ├── test_routes.py    # 11 tests — all API endpoints via httpx AsyncClient
    └── test_chat.py      # 20 tests — LLM parsing, mock mode, auto-execution
```

---

## What's Built

### `app/database.py` — SQLite Layer

Async SQLite access via `aiosqlite`. Lazy init: on startup `init_db()` creates all tables (DDL embedded in Python, no SQL files) and seeds default data if missing.

**DB path**: read from `DB_PATH` env var, defaults to `db/finally.db` relative to the project root. In Docker this must be set to `/app/db/finally.db` (already set in the Dockerfile via `ENV DB_PATH`).

**Tables**: `users_profile`, `watchlist`, `positions`, `trades`, `portfolio_snapshots`, `chat_messages` — all with `user_id TEXT DEFAULT 'default'`.

**Seed data**: default user ($10,000 cash), 10 watchlist tickers: AAPL, GOOGL, MSFT, AMZN, TSLA, NVDA, META, JPM, V, NFLX.

**Key helpers**:
| Function | Description |
|---|---|
| `init_db()` | Create schema + seed if needed |
| `get_user(user_id)` | Returns `{id, cash_balance, created_at}` |
| `get_watchlist(user_id)` | Returns list of ticker strings |
| `add_ticker(ticker, user_id)` | Idempotent insert |
| `remove_ticker(ticker, user_id)` | Delete from watchlist |
| `get_positions(user_id)` | Returns list of position dicts |
| `execute_trade(ticker, side, quantity, price, user_id)` | Updates positions + cash, inserts trade. Raises `ValueError` on insufficient cash/shares |
| `get_portfolio_history(user_id)` | Returns all portfolio snapshot dicts |
| `record_portfolio_snapshot(total_value, user_id)` | Insert snapshot |
| `get_chat_messages(user_id, limit)` | Returns last N messages |
| `save_chat_message(role, content, actions, user_id)` | Persist message + executed actions (JSON) |
| `reset_portfolio(user_id)` | Restore $10k cash, clear positions/trades/snapshots/messages |
| `set_db_path(path)` | Override DB path for test isolation |

### `app/main.py` — FastAPI App + Lifespan

Lifespan sequence on startup:
1. `init_db()` — create schema + seed
2. `create_market_source()` — simulator or Massive client based on `MASSIVE_API_KEY`
3. Load watchlist tickers from DB → `market_source.add_ticker()` for each
4. Create `PriceCache` instance
5. Store `market_source` and `cache` on `app.state`
6. Start market data background task (`market_source.start(cache)`)
7. Start portfolio snapshot task (every 30 seconds)

Static files: mounts `StaticFiles` from `/app/static` (Next.js export) at `/` if the directory exists. API routes always take priority.

**Important**: Must run as a single worker process. `PriceCache` and `market_source` are in-memory — multiple workers would have independent caches, breaking SSE consistency.

### `app/market/` — Market Data Layer (75 tests)

Pluggable price feed behind `MarketDataSource` ABC. Factory selects implementation at startup.

**Simulator** (default): GBM with sector correlation, random events, 500ms ticks. No external dependencies.

**Massive client**: Polls `api.massive.com/v2/snapshot` on a configurable interval (default 15s).

**PriceCache**: In-memory store. `update(point)` writes latest price and fans out to all subscribed SSE queues. `subscribe()` returns an `asyncio.Queue`; `unsubscribe(queue)` removes it.

**SSE event format** (what `to_sse_dict()` returns):
```json
{"ticker": "AAPL", "price": 190.05, "prev_price": 190.02, "timestamp": 1234567890.0, "direction": "up"}
```
Note: `direction` is `"up"`, `"down"`, or `"flat"` (not `"unchanged"`).

### `app/routes/stream.py` — SSE Endpoint

`GET /api/stream/prices` — uses `sse_starlette.sse.EventSourceResponse`.

Sends **named events**: `event: price` with JSON data. The frontend must use `EventSource.addEventListener('price', handler)` — **not** `onmessage` — to receive these.

Filters to only tickers in the user's current watchlist. Unsubscribes from cache on client disconnect.

### `app/routes/portfolio.py` — Portfolio Routes

`GET /api/portfolio` response shape:
```json
{
  "cash_balance": 10000.0,
  "total_value": 10000.0,
  "unrealized_pnl": 0.0,
  "positions": [
    {
      "ticker": "AAPL",
      "quantity": 10.0,
      "avg_cost": 190.03,
      "current_price": 190.05,
      "unrealized_pnl": 0.20,
      "pct_change": 0.01
    }
  ]
}
```
Note: the P&L percentage field is `pct_change` (not `pnl_percent`).

`POST /api/portfolio/trade` body: `{ticker, quantity, side}`. Records a portfolio snapshot immediately after execution.

### `app/chat.py` — LLM Integration

Model: `openrouter/openai/gpt-oss-120b` via LiteLLM + OpenRouter with Cerebras inference.

Structured output schema:
```json
{
  "message": "string",
  "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 10}],
  "watchlist_changes": [{"ticker": "PYPL", "action": "add"}]
}
```

`process_chat(message, cache, market_source, user_id)`:
1. Builds portfolio context (cash, positions with live P&L, watchlist with prices)
2. Loads last 20 messages (10 turns) from DB
3. Calls LLM (or returns mock if `LLM_MOCK=true`)
4. Auto-executes trades and watchlist changes
5. Persists messages with `actions` JSON field
6. Returns `{message, trades_executed, watchlist_changes_executed, errors}`

**Mock mode**: `LLM_MOCK=true` (case-insensitive) returns a deterministic response without calling the API.

---

## Environment Variables

```
OPENROUTER_API_KEY      # Required for chat (LLM calls)
MASSIVE_API_KEY         # Optional — empty/absent = use simulator
MASSIVE_POLL_INTERVAL   # Optional — default 15.0s
LLM_MOCK                # Set "true" for deterministic mock responses (E2E tests)
DB_PATH                 # Optional — default computed relative to database.py; set to /app/db/finally.db in Docker
```

---

## Key Design Rules

- All DDL embedded in Python — no external SQL files
- All tables have `user_id TEXT DEFAULT 'default'` (single-user MVP, multi-user ready)
- Market orders only — instant fill at current cache price
- Error responses use FastAPI default `{"detail": "..."}` — no custom envelope
- Market source and cache live on `app.state` — access via `request.app.state`
- **Single worker only** — do not run with `--workers N > 1`
- SSE sends named `price` events — frontend must use `addEventListener('price', ...)`
- Portfolio `pct_change` field (not `pnl_percent`) for P&L percentage

---

## Running Locally (without Docker)

```bash
cd backend
uv sync --extra dev          # install all deps including dev
$env:DB_PATH = "../db/finally.db"   # PowerShell
# DB_PATH=../db/finally.db          # bash
uv run uvicorn app.main:app --reload --port 8000
```

Note: static frontend files are not served locally — only API routes work. Run `npm run dev` in `frontend/` separately for the full UI.
