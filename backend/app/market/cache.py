import asyncio
from typing import Optional
from .models import PricePoint


class PriceCache:
    """
    In-memory store for the latest PricePoint per ticker.

    Written by: MarketSimulator / MassiveClient (one background task).
    Read by:    SSE stream handlers (many concurrent readers).

    Subscribers receive a copy of every PricePoint via asyncio.Queue.
    Slow consumers that fall behind (QueueFull) silently drop updates —
    they will catch up on the next tick.
    """

    def __init__(self) -> None:
        self._data: dict[str, PricePoint] = {}
        self._lock = asyncio.Lock()
        self._subscribers: list[asyncio.Queue[PricePoint]] = []

    # ------------------------------------------------------------------ writes

    async def update(self, point: PricePoint) -> None:
        """Store latest price and fan-out to all SSE subscribers."""
        async with self._lock:
            self._data[point.ticker] = point
        for queue in self._subscribers:
            try:
                queue.put_nowait(point)
            except asyncio.QueueFull:
                pass  # slow consumer — drop this tick, it will catch up

    async def remove(self, ticker: str) -> None:
        """Evict a ticker (called when it is removed from the watchlist)."""
        async with self._lock:
            self._data.pop(ticker, None)

    # ------------------------------------------------------------------ reads

    async def get(self, ticker: str) -> Optional[PricePoint]:
        async with self._lock:
            return self._data.get(ticker)

    async def get_all(self) -> dict[str, PricePoint]:
        async with self._lock:
            return dict(self._data)

    # ----------------------------------------------------------- subscriptions

    def subscribe(self) -> asyncio.Queue[PricePoint]:
        """
        Register an SSE handler. Returns a queue that receives every update.
        Call unsubscribe() when the client disconnects.
        """
        queue: asyncio.Queue[PricePoint] = asyncio.Queue(maxsize=200)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[PricePoint]) -> None:
        """Deregister an SSE handler."""
        try:
            self._subscribers.remove(queue)
        except ValueError:
            pass
