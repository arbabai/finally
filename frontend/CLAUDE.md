# Frontend — Claude Reference

## Stack

- Next.js 16, TypeScript (strict mode), Tailwind CSS v4
- Static export (`output: 'export'`) — `npm run build` produces `out/` directory
- Charts: `lightweight-charts` (TradingView) and `recharts`
- Tests: Jest 29 + React Testing Library (12 tests)

---

## Directory Structure

```
frontend/
├── app/
│   ├── layout.tsx        # Root layout — dark theme, full-height body
│   ├── page.tsx          # Single-page app — composes all panels
│   └── globals.css       # Tailwind base + price flash animations
├── components/
│   ├── Header.tsx        # Portfolio value, cash balance, connection status
│   ├── Watchlist.tsx     # Ticker list with prices, sparklines, add/remove
│   ├── SparkLine.tsx     # Canvas-based mini sparkline chart
│   ├── MainChart.tsx     # Large canvas price chart for selected ticker
│   ├── TradeBar.tsx      # Ticker + qty inputs, BUY/SELL buttons
│   ├── PositionsTable.tsx # Table: ticker, qty, avg cost, price, P&L, %
│   ├── PortfolioHeatmap.tsx # SVG treemap sized by weight, colored by P&L
│   ├── PnLChart.tsx      # Canvas line chart of portfolio value over time
│   ├── ChatPanel.tsx     # AI chat sidebar with loading state, trade confirmations
│   └── StatusDot.tsx     # Green/yellow/red SSE connection indicator
├── hooks/
│   ├── useSSE.ts         # EventSource connection, price state, history accumulation
│   └── usePortfolio.ts   # Portfolio + history polling (every 5s)
├── types/
│   └── index.ts          # All shared TypeScript interfaces
└── __tests__/            # Jest + RTL unit tests
```

---

## Color Scheme (Tailwind config)

| Token | Value | Usage |
|---|---|---|
| `bg-primary` | `#0d1117` | Main background |
| `bg-panel` | `#1a1a2e` | Panel backgrounds |
| `border` | `#30363d` | All borders |
| `text-primary` | `#e6edf3` | Main text |
| `text-secondary` | `#8b949e` | Labels, secondary |
| `accent-yellow` | `#ecad0a` | App name, accents |
| `blue-primary` | `#209dd7` | Portfolio value, links |
| `purple` | `#753991` | Submit buttons |
| `green` | `#3fb950` | Profit, upticks, BUY |
| `red` | `#f85149` | Loss, downticks, SELL |

---

## Data Flow

```
SSE /api/stream/prices
  └── useSSE.ts
        └── prices: Record<string, TickerState>
              ├── Watchlist.tsx  (price display + flash + sparkline)
              └── MainChart.tsx  (accumulated price history)

GET /api/portfolio (every 5s)
  └── usePortfolio.ts
        └── portfolio: Portfolio
              ├── Header.tsx      (total value, cash)
              ├── PositionsTable.tsx
              └── PortfolioHeatmap.tsx

GET /api/portfolio/history (every 5s)
  └── usePortfolio.ts
        └── history: PortfolioSnapshot[]
              └── PnLChart.tsx

GET /api/watchlist (on mount + after changes)
  └── page.tsx fetchWatchlist()
        └── watchlist: string[]
              └── Watchlist.tsx  (renders ticker rows)
```

---

## Critical Implementation Notes

### SSE — Named Events
The backend sends **named** SSE events (`event: price`). You **must** use:
```ts
es.addEventListener('price', (event: MessageEvent) => { ... });
```
`es.onmessage` does **not** fire for named events — this was a bug that caused prices to never appear.

### SSE Field Names
The backend `to_sse_dict()` sends:
- `prev_price` (not `previous_price`)
- `direction`: `"up"` | `"down"` | `"flat"` (not `"unchanged"`)

### Portfolio Field Names
`GET /api/portfolio` returns `pct_change` (not `pnl_percent`) for the P&L percentage on positions. Calling `.toFixed()` on the missing field crashes the positions table.

### Price Flash Animation
Defined in `globals.css`:
```css
.price-flash-up   { animation: flash-up 500ms ease-out; }
.price-flash-down { animation: flash-down 500ms ease-out; }
```
`Watchlist.tsx` applies these classes on price change and removes them after 500ms via `setTimeout`.

### Static Export Constraints
- `output: 'export'` in `next.config.ts` — no server-side rendering
- All API calls use relative `/api/*` paths (same-origin, no CORS needed)
- Do not use `next/image` with external URLs — use `<img>` tags instead
- No `getServerSideProps` or `getStaticProps` with dynamic data

### Browser Compatibility
**Internet Explorer is not supported.** The `EventSource` API (SSE) is not available in IE. Use Chrome, Edge (Chromium), or Firefox.

---

## API Contract (what the frontend calls)

| Method | Path | Used by |
|---|---|---|
| GET | `/api/stream/prices` | `useSSE.ts` |
| GET | `/api/watchlist` | `page.tsx` |
| POST | `/api/watchlist` | `Watchlist.tsx` |
| DELETE | `/api/watchlist/{ticker}` | `Watchlist.tsx` |
| GET | `/api/portfolio` | `usePortfolio.ts` |
| POST | `/api/portfolio/trade` | `TradeBar.tsx` |
| GET | `/api/portfolio/history` | `usePortfolio.ts` |
| POST | `/api/chat` | `ChatPanel.tsx` |

---

## Running Locally (development)

```bash
cd frontend
npm install
npm run dev        # starts on http://localhost:3000
```

The dev server proxies `/api/*` to nothing by default — you need the backend running separately on port 8000. Add a proxy to `next.config.ts` if needed, or use the Docker container for the full integrated experience.

## Building

```bash
cd frontend
npm run build      # produces frontend/out/ (static export)
```

The Docker multi-stage build runs this automatically and copies `out/` to `/app/static/` in the container.
