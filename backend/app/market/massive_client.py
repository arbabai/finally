import asyncio
import httpx

from .cache import PriceCache
from .interface import MarketDataSource
from .models import PricePoint

BASE_URL = "https://api.massive.com"


class MassiveClient(MarketDataSource):
    """
    Polls the Massive REST API for live stock prices.
    One request per poll interval fetches all watched tickers.

    Default poll_interval=15.0 s is safe for the free tier (5 req/min limit).
    Paid plans can set poll_interval=2.0 or lower.
    """

    def __init__(self, api_key: str, poll_interval: float = 15.0) -> None:
        self._api_key = api_key
        self._poll_interval = poll_interval
        self._tickers: set[str] = set()
        self._running: bool = False
        # Track previous prices across polls for change_direction
        self._prev_prices: dict[str, float] = {}

    @property
    def source_name(self) -> str:
        return "MassiveAPI"

    # -------------------------------------------------- watchlist management

    def add_ticker(self, ticker: str) -> None:
        self._tickers.add(ticker.upper())

    def remove_ticker(self, ticker: str) -> None:
        ticker = ticker.upper()
        self._tickers.discard(ticker)
        self._prev_prices.pop(ticker, None)

    # -------------------------------------------------- lifecycle

    async def start(self, cache: PriceCache) -> None:
        self._running = True
        print(f"[MassiveAPI] Starting poller — interval={self._poll_interval}s")
        async with httpx.AsyncClient(timeout=10.0) as client:
            while self._running:
                tickers = list(self._tickers)
                if tickers:
                    try:
                        prices = await self._fetch_prices(client, tickers)
                        for ticker, price in prices.items():
                            prev = self._prev_prices.get(ticker, price)
                            point = PricePoint.from_prices(ticker, price, prev)
                            await cache.update(point)
                            self._prev_prices[ticker] = price
                    except httpx.HTTPStatusError as e:
                        status = e.response.status_code
                        if status == 403:
                            print("[MassiveAPI] Invalid API key — check MASSIVE_API_KEY")
                        elif status == 429:
                            print("[MassiveAPI] Rate limited — consider increasing poll_interval")
                        else:
                            print(f"[MassiveAPI] HTTP {status}: {e}")
                    except httpx.TimeoutException:
                        print("[MassiveAPI] Request timed out — will retry")
                    except Exception as e:
                        print(f"[MassiveAPI] Unexpected error: {e}")
                await asyncio.sleep(self._poll_interval)

    async def stop(self) -> None:
        self._running = False

    # -------------------------------------------------- HTTP fetch

    async def _fetch_prices(
        self,
        client: httpx.AsyncClient,
        tickers: list[str],
    ) -> dict[str, float]:
        """
        Fetch current prices for the given tickers.
        Returns {ticker: price}. Tickers with no data are omitted.
        """
        resp = await client.get(
            f"{BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers",
            params={
                "tickers": ",".join(tickers),
                "apiKey": self._api_key,
            },
        )
        resp.raise_for_status()
        data = resp.json()

        prices: dict[str, float] = {}
        for snapshot in data.get("tickers", []):
            ticker = snapshot.get("ticker")
            if not ticker:
                continue
            # Prefer lastTrade.p (real-time); fall back to day.c
            last_trade = snapshot.get("lastTrade") or {}
            price = last_trade.get("p") or (snapshot.get("day") or {}).get("c")
            if price is not None:
                prices[ticker] = float(price)

        return prices
