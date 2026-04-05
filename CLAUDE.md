# FinAlly Project — Claude Reference

FinAlly (Finance Ally) is an AI-powered trading workstation: live streaming market data, simulated portfolio, and an LLM chat assistant that can analyze positions and execute trades via natural language.

All project documentation lives in `planning/`. The original specification is `planning/PLAN.md`. Architecture overview is `planning/ARCHITECTURE.md`.

---

## Project Status

**Complete and working.** All components built, tested, and integrated.

| Component | Status | Tests |
|---|---|---|
| Market data (simulator + Massive) | ✅ Complete | 75/75 |
| Database layer (SQLite) | ✅ Complete | 19/19 |
| FastAPI backend + all routes | ✅ Complete | 11/11 |
| LLM integration (chat) | ✅ Complete | 20/20 |
| Next.js frontend | ✅ Complete | 12/12 |
| Docker + scripts | ✅ Complete | — |
| E2E Playwright tests | ✅ Complete | 7/7 |
| **Total** | | **125 backend + 12 frontend** |

---

## Directory Structure

```
finally/
├── frontend/                 # Next.js TypeScript app (static export)
│   ├── CLAUDE.md             # Frontend-specific agent reference
│   └── ...
├── backend/                  # FastAPI uv project
│   ├── CLAUDE.md             # Backend-specific agent reference
│   ├── app/
│   │   ├── main.py           # App entry point + lifespan
│   │   ├── database.py       # SQLite layer
│   │   ├── chat.py           # LLM integration
│   │   ├── market/           # Price feed (simulator + Massive)
│   │   └── routes/           # API route handlers
│   └── tests/                # 125 pytest tests
├── planning/
│   ├── PLAN.md               # Original full specification
│   ├── ARCHITECTURE.md       # Architecture deep-dive
│   └── MARKET_DATA_SUMMARY.md
├── test/                     # E2E Playwright tests
│   ├── docker-compose.test.yml
│   └── tests/e2e.spec.ts
├── scripts/
│   ├── start_mac.sh / stop_mac.sh
│   └── start_windows.ps1 / stop_windows.ps1
├── db/                       # SQLite volume mount target (runtime only)
├── Dockerfile                # Multi-stage: Node → Python
├── docker-compose.yml
├── .env.example
└── .gitignore
```

---

## Quick Start

```bash
cp .env.example .env
# Add your OPENROUTER_API_KEY to .env

# Mac/Linux
./scripts/start_mac.sh

# Windows
.\scripts\start_windows.ps1

# Or directly:
docker build -t finally .
docker run -d --name finally -p 8000:8000 -v finally-data:/app/db --env-file .env finally
```

Open [http://localhost:8000](http://localhost:8000).

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENROUTER_API_KEY` | Yes | — | OpenRouter API key for AI chat |
| `MASSIVE_API_KEY` | No | — | Polygon.io key for real market data; omit to use simulator |
| `LLM_MOCK` | No | `false` | Set `true` for deterministic mock LLM (E2E tests) |
| `DB_PATH` | No | computed | SQLite file path; auto-set to `/app/db/finally.db` in Docker |

---

## Key Architecture Decisions

### Single process, single port
FastAPI serves both the API and the Next.js static export on port 8000. No reverse proxy, no CORS.

### Must run as single uvicorn worker
`PriceCache` and `market_source` are in-memory. Multiple workers would have independent caches, breaking SSE price streaming. Do **not** add `--workers N`.

### SSE named events
The backend sends `event: price` named events. The frontend uses `EventSource.addEventListener('price', handler)` — **not** `onmessage`.

### SQLite + WAL mode
Single-user, no auth, no need for a database server. WAL journal mode for concurrent reads.

### Market orders only
No order book, no partial fills, no limit orders. Instant fill at current cache price.

---

## Known Limitations

- **No IE/legacy browser support** — `EventSource` (SSE) requires a modern browser (Chrome, Edge, Firefox)
- **Single user** — `user_id = "default"` is hardcoded; schema supports multi-user via `user_id` column on all tables
- **No HTTPS** — HTTP/2 requires TLS; for local dev HTTP/1.1 is fine
- **Portfolio history** — no time-range filtering; returns all rows

---

## Development

```bash
# Backend only (API, no frontend)
cd backend
uv sync --extra dev
DB_PATH=../db/finally.db uv run uvicorn app.main:app --reload --port 8000

# Frontend only (no backend)
cd frontend
npm install && npm run dev   # http://localhost:3000

# Backend tests
cd backend && uv run pytest

# E2E tests (requires Docker)
cd test
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit
```

---

## Consulting Specific Docs

- Full original spec → `planning/PLAN.md`
- Architecture deep-dive → `planning/ARCHITECTURE.md`
- Backend internals → `backend/CLAUDE.md`
- Frontend internals → `frontend/CLAUDE.md`
- Market data details → `planning/MARKET_DATA_SUMMARY.md`
