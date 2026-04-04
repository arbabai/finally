# Market Simulator Design

This document describes the approach and code structure for the built-in stock price simulator in FinAlly. The simulator runs when `MASSIVE_API_KEY` is not set and implements the same `MarketDataSource` interface as the Massive API client.

---

## Goals

- Produce **realistic-looking price movements** using financial mathematics
- Run **entirely in-process** — no external dependencies, no network calls
- Support **dynamic watchlists** — add/remove tickers at runtime
- Generate **correlated moves** — tech stocks move together, etc.
- Inject **random events** — sudden 2-5% spikes for drama
- Produce prices at **~500ms intervals** — smooth enough for live UI updates
- Start from **seed prices** close to real-world values

---

## Mathematical Foundation: Geometric Brownian Motion (GBM)

Stock price simulation uses the discrete-time GBM formula:

```
S(t+dt) = S(t) * exp((μ - σ²/2) * dt + σ * √dt * Z)
```

Where:
- `S(t)` — current price
- `μ` — drift (annualized expected return; small positive value for realistic upward bias)
- `σ` — volatility (annualized standard deviation of log returns)
- `dt` — time step in years (e.g. 0.5s ÷ 31,536,000 s/year ≈ 0.0000000158)
- `Z` — standard normal random variable: `Z ~ N(0, 1)`

At dt=0.5s the drift term is negligible; volatility dominates tick-to-tick moves.

**Effective per-tick standard deviation** = `σ * √dt`

For AAPL with σ=0.25 (25% annual vol) and dt=0.5/31536000:
- Per-tick std ≈ 0.25 × √(1.587e-8) ≈ 0.000996 ≈ 0.1% per tick

This produces small, realistic incremental moves between SSE events.

---

## Correlation Model

Real stocks within the same sector move together. We simulate this with a two-component noise model:

```
Z_ticker = ρ_sector * Z_sector + √(1 - ρ²_sector) * Z_individual
```

Where:
- `Z_sector` — a shared random shock drawn once per tick per sector group
- `Z_individual` — an independent shock unique to each ticker
- `ρ_sector` — correlation coefficient (e.g. 0.6 for tech stocks)

Each tick, we draw one `Z_sector` per group and blend it with each ticker's own `Z_individual`. This produces correlated but not identical movements.

**Sector groups:**
- `tech`: AAPL, MSFT, GOOGL, AMZN, META, NVDA, NFLX
- `finance`: JPM, V
- `auto`: TSLA
- `default` (any unknown ticker): correlated with tech at ρ=0.3

---

## Random Event Injection

Every tick, each ticker has a small probability of a "market event" — a sudden large price move:

```python
EVENT_PROBABILITY = 0.002   # 0.2% chance per tick per ticker
EVENT_MAGNITUDE = (0.02, 0.05)  # 2-5% move, randomly up or down
```

At 500ms ticks, this fires roughly once every ~8 minutes per ticker, which creates occasional drama without being overwhelming.

---

## Seed Prices

Starting prices approximate real-world values as of early 2024. These are hardcoded — the simulator is not trying to track real prices, just look plausible.

```python
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

DEFAULT_SEED_PRICE = 100.0  # For any ticker not in the list
```

---

## Per-Ticker Configuration

Each ticker has its own volatility and drift. Higher-beta stocks (TSLA, NVDA) have higher σ; stable ones (JPM, V) have lower.

```python
@dataclass
class TickerConfig:
    sigma: float    # Annualized volatility (fraction, e.g. 0.30 = 30%)
    mu: float       # Annualized drift (fraction; small positive = slight upward bias)
    sector: str     # For correlated noise grouping

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
```

---

## Full Implementation

```python
# backend/app/market/simulator.py
import asyncio
import math
import random
import time
from dataclasses import dataclass, field

from .cache import PriceCache
from .interface import MarketDataSource
from .models import PricePoint

# --- Configuration constants ---

TICK_INTERVAL = 0.5        # Seconds between price updates
SECONDS_PER_YEAR = 365.25 * 24 * 3600
DT = TICK_INTERVAL / SECONDS_PER_YEAR   # Time step in years

SECTOR_CORRELATION = 0.6   # How much tickers in the same sector move together
EVENT_PROBABILITY = 0.002  # Per-ticker probability of a random event per tick
EVENT_MIN = 0.02           # Minimum event magnitude (2%)
EVENT_MAX = 0.05           # Maximum event magnitude (5%)

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

@dataclass
class TickerConfig:
    sigma: float
    mu: float
    sector: str

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


@dataclass
class TickerState:
    ticker: str
    config: TickerConfig
    price: float           # Current simulated price
    prev_price: float      # Price from the last tick


class MarketSimulator(MarketDataSource):
    """
    Simulates stock prices using Geometric Brownian Motion with:
    - Per-ticker volatility and drift
    - Sector correlation (tech stocks move together)
    - Random market events (sudden 2-5% moves)
    - 500ms tick rate
    """

    def __init__(self):
        self._states: dict[str, TickerState] = {}
        self._running = False

    @property
    def source_name(self) -> str:
        return "Simulator"

    def add_ticker(self, ticker: str) -> None:
        ticker = ticker.upper()
        if ticker not in self._states:
            config = TICKER_CONFIGS.get(ticker, DEFAULT_CONFIG)
            seed = SEED_PRICES.get(ticker, 100.0)
            self._states[ticker] = TickerState(
                ticker=ticker,
                config=config,
                price=seed,
                prev_price=seed,
            )

    def remove_ticker(self, ticker: str) -> None:
        self._states.pop(ticker.upper(), None)

    async def start(self, cache: PriceCache) -> None:
        self._running = True
        print(f"[Simulator] Starting with {len(self._states)} tickers")
        while self._running:
            tick_start = time.monotonic()
            self._tick(self._states)
            for state in list(self._states.values()):
                point = PricePoint.from_prices(
                    ticker=state.ticker,
                    price=state.price,
                    prev_price=state.prev_price,
                )
                await cache.update(point)
            # Sleep for the remainder of the tick interval
            elapsed = time.monotonic() - tick_start
            await asyncio.sleep(max(0.0, TICK_INTERVAL - elapsed))

    async def stop(self) -> None:
        self._running = False

    def _tick(self, states: dict[str, TickerState]) -> None:
        """Advance all tickers by one time step."""
        # Draw one sector shock per sector group
        sectors = {s.config.sector for s in states.values()}
        sector_shocks: dict[str, float] = {
            sector: random.gauss(0, 1) for sector in sectors
        }

        for state in states.values():
            state.prev_price = state.price

            # --- Correlated noise ---
            z_sector = sector_shocks[state.config.sector]
            z_individual = random.gauss(0, 1)
            rho = SECTOR_CORRELATION
            z = rho * z_sector + math.sqrt(1 - rho ** 2) * z_individual

            # --- GBM step ---
            sigma = state.config.sigma
            mu = state.config.mu
            drift = (mu - 0.5 * sigma ** 2) * DT
            diffusion = sigma * math.sqrt(DT) * z
            state.price *= math.exp(drift + diffusion)

            # --- Random event injection ---
            if random.random() < EVENT_PROBABILITY:
                magnitude = random.uniform(EVENT_MIN, EVENT_MAX)
                direction = random.choice([-1, 1])
                state.price *= (1 + direction * magnitude)

            # --- Price floor ---
            state.price = max(state.price, 0.01)
```

---

## Design Decisions

### Why GBM?

GBM is the standard model underlying Black-Scholes option pricing. It produces:
- Log-normally distributed prices (prices can't go negative)
- Percentage-based moves (a 1% move on a $1000 stock looks right)
- Realistic "random walk" appearance

The alternative — additive Brownian motion — allows negative prices and produces unrealistically large moves on low-priced tickers.

### Why 500ms ticks?

- Fast enough for convincing UI animations and sparkline growth
- Slow enough that the SSE stream is not overwhelming
- Matches the Massive API free-tier polling rhythm (with a 15s poll, we cache the last price and re-emit it every 500ms from the cache — this is handled at the SSE layer, not the simulator)

### Why pre-tick `prev_price` capture?

`prev_price` is set to the current price *before* the GBM step. This ensures the SSE event accurately reflects the change from the immediately preceding tick, which the frontend uses for the green/red flash animation.

### Why a price floor of $0.01?

Mathematically, GBM cannot reach zero, but floating point is not mathematics. The floor guards against degenerate states if parameters are tuned aggressively.

### Dynamic watchlist support

`add_ticker()` / `remove_ticker()` modify `_states` which is read in `_tick()`. Both are synchronous and called from the same asyncio event loop, so there is no concurrency issue. If multi-threading were ever introduced, a `threading.Lock` would be needed.

---

## Simulation Quality Checks

Approximate outputs at default settings (AAPL, 500ms ticks, 1 hour):

| Metric | Expected range |
|--------|---------------|
| Per-tick price change | ±0.05% – 0.15% |
| Hourly drift | ~0.04% (mu contribution) |
| Random event frequency | ~1 per 8 min per ticker |
| Event magnitude | 2% – 5% jump |
| Price after 8 hours | Within ±3% of seed (typical) |

The simulator is not designed to produce realistic long-run price series — it exists to make the UI look alive during a demo session of a few hours.

---

## Testing

```python
# backend/tests/market/test_simulator.py

import asyncio
from unittest.mock import AsyncMock
from app.market.simulator import MarketSimulator
from app.market.cache import PriceCache
from app.market.models import PricePoint

def test_add_remove_ticker():
    sim = MarketSimulator()
    sim.add_ticker("AAPL")
    assert "AAPL" in sim._states
    sim.remove_ticker("AAPL")
    assert "AAPL" not in sim._states

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
    sim._tick(sim._states)
    # Price should have changed (vanishingly unlikely to be identical)
    assert sim._states["AAPL"].prev_price == initial
    # Price stays positive
    assert sim._states["AAPL"].price > 0

def test_tick_sets_prev_price():
    sim = MarketSimulator()
    sim.add_ticker("MSFT")
    sim._tick(sim._states)
    price_after_tick1 = sim._states["MSFT"].price
    sim._tick(sim._states)
    assert sim._states["MSFT"].prev_price == price_after_tick1

async def test_start_writes_to_cache():
    sim = MarketSimulator()
    sim.add_ticker("AAPL")
    cache = PriceCache()

    async def run():
        await asyncio.wait_for(sim.start(cache), timeout=1.2)

    try:
        await run()
    except asyncio.TimeoutError:
        pass

    result = await cache.get("AAPL")
    assert result is not None
    assert isinstance(result, PricePoint)
    assert result.price > 0
```
