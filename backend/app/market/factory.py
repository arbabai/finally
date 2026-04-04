import os
from .interface import MarketDataSource
from .massive_client import MassiveClient
from .simulator import MarketSimulator


def create_market_source() -> MarketDataSource:
    """
    Select and instantiate the appropriate MarketDataSource.

    Rules:
    - MASSIVE_API_KEY set and non-empty → MassiveClient (real data)
    - MASSIVE_API_KEY absent or empty   → MarketSimulator (default)
    """
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if api_key:
        poll_interval = float(os.environ.get("MASSIVE_POLL_INTERVAL", "15.0"))
        print(f"[Market] Using Massive API (poll_interval={poll_interval}s)")
        return MassiveClient(api_key=api_key, poll_interval=poll_interval)
    print("[Market] Using built-in simulator (no MASSIVE_API_KEY)")
    return MarketSimulator()
