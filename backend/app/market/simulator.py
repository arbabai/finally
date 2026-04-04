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
