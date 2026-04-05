# FinAlly — Architecture

## Overview

FinAlly runs as a **single Docker container on a single port (8000)**. FastAPI serves both the REST/SSE API and the pre-built Next.js static export. There is no reverse proxy, no CORS configuration, and no separate database server.

```
┌────────────────────────────────────────────────────────────────┐
│  Docker Container (port 8000)                                  │
│                                                                │
│  FastAPI (Python / uv)                                         │
│  ├── /api/health              Health check                     │
│  ├── /api/stream/prices       SSE — live price feed            │
│  ├── /api/watchlist           Watchlist CRUD                   │
│  ├── /api/portfolio           Portfolio + trades               │
│  ├── /api/chat                LLM chat                         │
│  └── /*                       Static file serving             │
│                                (Next.js export from /app/static)│
│                                                                │
│  Background tasks                                              │
│  ├── Market data task         GBM simulator (or Massive API)   │
│  └── Snapshot task            Portfolio value every 30s        │
│                                                                │
│  SQLite  /app/db/finally.db   (volume-mounted for persistence) │
└────────────────────────────────────────────────────────────────┘
         │ volume
    finally-data (Docker named volume)
```

---

## Component Map

```
finally/
├── frontend/              Next.js 16, TypeScript, Tailwind v4
│   ├── app/page.tsx       Single-page layout, orchestrates all panels
│   ├── hooks/useSSE.ts    EventSource → live price state
│   ├── hooks/usePortfolio.ts  Portfolio polling (5s interval)
│   └── components/        10 UI components (see Frontend section)
│
└── backend/               FastAPI, Python 3.12, uv
    ├── app/main.py        App + lifespan (startup/shutdown sequence)
    ├── app/database.py    Async SQLite (aiosqlite) — all CRUD
    ├── app/chat.py        LiteLLM → OpenRouter → gpt-oss-120b
    ├── app/market/        Pluggable price feed
    │   ├── interface.py   MarketDataSource ABC
    │   ├── cache.py       PriceCache (in-memory, asyncio.Queue fan-out)
    │   ├── simulator.py   GBM simulator
    │   ├── massive_client.py  Polygon.io REST polling
    │   └── factory.py     Selects implementation from env vars
    └── app/routes/        One file per route group
        ├── health.py
        ├── stream.py      SSE endpoint
        ├── watchlist.py
        ├── portfolio.py
        └── chat.py
```

---

## Request Lifecycle

### Page Load

```
Browser → GET / → FastAPI StaticFiles → frontend/out/index.html
Browser → GET /_next/static/* → JS/CSS bundles

React hydrates:
  page.tsx mounts
  ├── useSSE() → new EventSource('/api/stream/prices')
  ├── usePortfolio() → GET /api/portfolio + /api/portfolio/history
  └── fetchWatchlist() → GET /api/watchlist
```

### Live Price Feed (SSE)

```
EventSource connects to GET /api/stream/prices
  → FastAPI stream.py → _price_generator()
      → cache.subscribe() → asyncio.Queue
      loop:
        queue.get() → PricePoint
        filter to watchlist tickers
        yield {"event": "price", "data": JSON}
  → Browser EventSource.addEventListener('price', handler)
      → useSSE setPrices() → React re-render
          → Watchlist prices update
          → SparkLine data appended
          → MainChart data appended
          → Flash animation triggered (500ms CSS)
```

**Important:** The backend sends named SSE events (`event: price`). The browser `EventSource.onmessage` only handles unnamed events. The frontend uses `addEventListener('price', ...)` to receive them.

### Trade Execution

```
User fills TradeBar (ticker + qty) → clicks BUY
  → POST /api/portfolio/trade {ticker, quantity, side: "buy"}
      → portfolio.py
          → cache.get(ticker) → current price
          → database.execute_trade() → update positions + cash
          → database.record_portfolio_snapshot() → immediate snapshot
          → _build_portfolio_response() → return updated state
  → TradeBar calls onTradeExecuted()
  → usePortfolio.refresh() → GET /api/portfolio → UI updates
```

### AI Chat

```
User types message → ChatPanel → POST /api/chat {message}
  → chat route → app/chat.py process_chat()
      1. build_portfolio_context(cache) → cash + positions + watchlist with live prices
      2. database.get_chat_messages(limit=20) → conversation history
      3. LiteLLM completion (or mock if LLM_MOCK=true)
      4. Parse structured JSON response:
         {message, trades[], watchlist_changes[]}
      5. Auto-execute trades → database.execute_trade()
      6. Auto-execute watchlist changes → add/remove ticker in DB + market_source
      7. database.save_chat_message() → persist both messages
      8. Return {message, trades_executed, watchlist_changes_executed, errors}
  → ChatPanel renders response + inline trade/watchlist confirmations
```

---

## Market Data Architecture

### Two Implementations, One Interface

```python
class MarketDataSource(ABC):
    def add_ticker(self, ticker: str) -> None: ...
    def remove_ticker(self, ticker: str) -> None: ...
    async def start(self, cache: PriceCache) -> None: ...  # blocks until stop()
    async def stop(self) -> None: ...
```

`factory.py` reads `MASSIVE_API_KEY`:
- Present and non-empty → `MassiveClient` (Polygon.io REST polling)
- Absent or empty → `MarketSimulator` (GBM, default)

### Simulator

Geometric Brownian Motion with:
- Per-ticker seed prices (AAPL ~$190, NVDA ~$880, etc.)
- Per-ticker volatility (σ) and drift (μ) config
- Sector correlation (ρ=0.6) — tech stocks move together
- Random market events (0.2% probability, 2–5% move)
- 500ms tick interval

### PriceCache

In-memory store that decouples the market source from SSE consumers:

```
MarketSimulator.start(cache)
  every 500ms → cache.update(PricePoint)
                  → _prices[ticker] = point          (latest price)
                  → for q in _subscribers: q.put(point)  (fan-out)

SSE _price_generator()
  → cache.subscribe() → queue
  → queue.get() → yields to EventSource
  → cache.unsubscribe(queue) on disconnect
```

**Critical constraint**: PriceCache is in-memory. The FastAPI app **must** run as a single process (single uvicorn worker). Multiple workers would have independent caches — SSE events would only reach clients connected to the same worker that's also receiving the market data.

---

## Database Schema

SQLite with WAL journal mode. All tables include `user_id TEXT DEFAULT 'default'` for future multi-user support.

```sql
users_profile        -- cash balance per user
watchlist            -- tickers being watched (UNIQUE user_id+ticker)
positions            -- current holdings (UNIQUE user_id+ticker)
trades               -- append-only trade log
portfolio_snapshots  -- total value over time (every 30s + after each trade)
chat_messages        -- conversation history with actions JSON
```

**Lazy initialization**: `init_db()` is called in the lifespan on startup. It uses `CREATE TABLE IF NOT EXISTS` and only seeds data if the watchlist is empty — safe to call on every startup, including with an existing database.

**DB path**: Configured via `DB_PATH` env var. In Docker this is `/app/db/finally.db` (set by `ENV DB_PATH` in the Dockerfile). The volume mount at `/app/db` persists the file across container restarts. The path calculation in `database.py` defaults correctly for local development (running from `backend/` directory).

---

## Docker Build

Multi-stage Dockerfile:

```
Stage 1: node:20-slim  (frontend builder)
  WORKDIR /app/frontend
  COPY frontend/
  RUN npm ci && npm run build
  → produces frontend/out/ (static HTML/JS/CSS)

Stage 2: python:3.12-slim  (runtime)
  Install uv
  COPY backend/pyproject.toml + uv.lock → uv sync --no-dev --frozen
  COPY backend/ → /app/
  COPY --from=frontend-builder /app/frontend/out → /app/static/
  ENV DB_PATH=/app/db/finally.db
  EXPOSE 8000
  CMD uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Key notes:
- Single worker (no `--workers N`) — required for in-memory PriceCache correctness
- `.dockerignore` keeps build context small (~400KB vs 649MB without it)
- The `db/` directory in the project root maps to `/app/db` in the container via Docker volume

---

## SSE Protocol Details

Endpoint: `GET /api/stream/prices`

The server uses `sse_starlette.sse.EventSourceResponse` and yields named events:

```
event: price
data: {"ticker": "AAPL", "price": 190.05, "prev_price": 190.02, "timestamp": 1712345678.0, "direction": "up"}

event: price
data: {"ticker": "MSFT", "price": 420.11, "prev_price": 420.08, "timestamp": 1712345678.0, "direction": "up"}
```

Field reference:
| Field | Type | Notes |
|---|---|---|
| `ticker` | string | Uppercase symbol |
| `price` | float | Rounded to 4dp |
| `prev_price` | float | Previous tick price |
| `timestamp` | float | Unix epoch seconds |
| `direction` | string | `"up"`, `"down"`, or `"flat"` |

The stream filters to only tickers in the user's current watchlist — adding or removing a ticker takes effect within one tick cycle.

**Browser consumption**:
```typescript
const es = new EventSource('/api/stream/prices');
es.addEventListener('price', (event: MessageEvent) => {
  const update = JSON.parse(event.data);
  // update.ticker, update.price, update.prev_price, update.direction
});
```

---

## LLM Integration

Model: `openrouter/openai/gpt-oss-120b` via LiteLLM routed through OpenRouter to Cerebras inference.

Structured output schema enforced via Pydantic + LiteLLM `response_format`:

```json
{
  "message": "Your conversational reply",
  "trades": [
    {"ticker": "AAPL", "side": "buy", "quantity": 10}
  ],
  "watchlist_changes": [
    {"ticker": "PYPL", "action": "add"}
  ]
}
```

Context injected into every request:
- Current cash balance
- All open positions with unrealized P&L and current prices from cache
- All watchlist tickers with current prices
- Total portfolio value
- Last 20 messages (10 user/assistant turns)

Trades and watchlist changes from the LLM response are auto-executed immediately — no confirmation dialog. Errors (e.g. insufficient cash) are returned to the LLM in the `errors` field so it can inform the user.

**Mock mode**: `LLM_MOCK=true` returns a hardcoded response. Used by E2E tests and development without an API key.

---

## Portfolio Snapshot Task

Runs as an `asyncio` background task in the same process as the server:

```python
async def _snapshot_loop(cache: PriceCache):
    while True:
        await asyncio.sleep(30)
        # sum cash + (quantity × current_price) for all positions
        total = cash + sum(price * qty for each position)
        await db.record_portfolio_snapshot(total)
```

Additionally, a snapshot is recorded **immediately after each trade** via `portfolio.py`. This gives the P&L chart meaningful data points right after activity, not just on the 30-second clock.

---

## Testing

### Unit Tests (backend, 125 total)

| Suite | Tests | What's covered |
|---|---|---|
| `tests/market/` | 75 | Simulator GBM math, cache fan-out, Massive client parsing, factory selection, models |
| `tests/test_database.py` | 19 | Schema creation, seed data, CRUD, trade validation (insufficient cash/shares), reset |
| `tests/test_routes.py` | 11 | All API endpoints via `httpx.AsyncClient`, mocked app state |
| `tests/test_chat.py` | 20 | Structured output parsing, mock mode, auto-execution, malformed responses |

### Unit Tests (frontend, 12 total)

Jest + React Testing Library covering: StatusDot, Header, PositionsTable, TradeBar, ChatPanel.

### E2E Tests (Playwright, 7 scenarios)

Located in `test/`. Run against the full Docker container with `LLM_MOCK=true`:

1. Fresh start — 10 tickers visible, $10k balance, prices streaming
2. SSE resilience — connection status shows "Connected"
3. Add and remove ticker
4. Buy shares — cash decreases, position appears
5. Sell shares — cash increases, position updates
6. Portfolio visualisation — heatmap and P&L chart render
7. AI chat (mocked) — message sent, response received

---

## Known Limitations and Future Work

| Limitation | Notes |
|---|---|
| Single user | `user_id = "default"` hardcoded; schema is multi-user ready |
| No HTTPS | HTTP/2 requires TLS; not needed for local development |
| No IE support | `EventSource` unavailable in IE; use Chrome/Edge/Firefox |
| Portfolio history | No time-range filtering — returns all rows (fine for demo scale) |
| SSE reconnect | `EventSource` auto-reconnects; no explicit reconnect UI beyond status dot |
| No order types | Market orders only — no limit, stop, or partial fills |
| Watchlist validation | Any non-empty string accepted; unknown tickers get simulated prices |
