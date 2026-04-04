# FinAlly — AI Trading Workstation

A Bloomberg-inspired AI-powered trading workstation with live-streaming market data, a simulated portfolio, and an LLM chat assistant that can analyze positions and execute trades on your behalf.

## Features

- **Live price streaming** via SSE — prices flash green/red on tick changes with sparkline mini-charts
- **Simulated portfolio** — start with $10,000 virtual cash, execute market orders instantly
- **Portfolio visualizations** — treemap heatmap (P&L by position weight) and portfolio value history chart
- **AI chat assistant** — ask questions, get analysis, and let the AI execute trades and manage your watchlist via natural language
- **No login required** — open the app and start trading immediately

## Quick Start

```bash
# Copy and fill in your API key
cp .env.example .env

# Build and run
docker run -v finally-data:/app/db -p 8000:8000 --env-file .env finally
```

Open [http://localhost:8000](http://localhost:8000).

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | Yes | OpenRouter API key for AI chat |
| `MASSIVE_API_KEY` | No | Polygon.io key for real market data (uses simulator if omitted) |
| `LLM_MOCK` | No | Set `true` for deterministic mock LLM responses (testing) |

## Architecture

Single Docker container, single port (8000):

- **Frontend**: Next.js (TypeScript), built as a static export, served by FastAPI
- **Backend**: FastAPI (Python/uv) — REST API, SSE streaming, LLM integration
- **Database**: SQLite at `db/finally.db`, volume-mounted for persistence
- **Market data**: Built-in GBM simulator by default; Polygon.io REST polling if `MASSIVE_API_KEY` is set
- **AI**: LiteLLM → OpenRouter (Cerebras inference) with structured JSON outputs

## Development

**Backend:**
```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

## Testing

```bash
# Backend unit tests
cd backend && uv run pytest

# E2E tests (requires Docker)
cd test && docker compose -f docker-compose.test.yml up --abort-on-container-exit
```
