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
