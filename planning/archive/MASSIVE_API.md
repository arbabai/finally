# Massive (formerly Polygon.io) API Documentation

> **Note:** Polygon.io rebranded as Massive.com on October 30, 2025. All existing API keys, accounts, and integrations continue to work. The base URL changed from `api.polygon.io` to `api.massive.com`, but `api.polygon.io` remains supported for an extended period.

---

## Authentication

All requests require an API key, passed as a query parameter:

```
GET https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers?apiKey=YOUR_KEY
```

Or as a Bearer token in the Authorization header:

```http
Authorization: Bearer YOUR_API_KEY
```

The query parameter approach is simpler and sufficient for server-side use.

---

## Rate Limits

| Plan | Calls per Minute | Notes |
|------|-----------------|-------|
| Free | 5 | End-of-day and historical data only |
| Starter / Paid | Unlimited | Stay under ~100 req/sec to avoid throttling |

On the free plan, real-time snapshot data is not available — only delayed/end-of-day data. A paid plan is required for live prices.

---

## Key Endpoints for This Project

### 1. Full Market Snapshot — Multiple Tickers

Retrieves the current snapshot (last trade, last quote, day bar, minute bar, prev-day bar) for a comma-separated list of tickers. This is the primary endpoint for polling live prices.

**Endpoint:**
```
GET /v2/snapshot/locale/us/markets/stocks/tickers
```

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `tickers` | string | Comma-separated list of ticker symbols (e.g. `AAPL,MSFT,GOOGL`). Leave empty to get all tickers. |
| `apiKey` | string | Your API key |

**Example Request:**
```
GET https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,MSFT,GOOGL&apiKey=YOUR_KEY
```

**Response Structure:**
```json
{
  "status": "OK",
  "request_id": "abc123",
  "count": 3,
  "tickers": [
    {
      "ticker": "AAPL",
      "todaysChange": 2.50,
      "todaysChangePerc": 1.32,
      "updated": 1712345678000000000,
      "day": {
        "o": 187.20,
        "h": 190.50,
        "l": 186.80,
        "c": 189.70,
        "v": 52341234,
        "vw": 188.95
      },
      "min": {
        "o": 189.60,
        "h": 189.80,
        "l": 189.40,
        "c": 189.70,
        "v": 234567,
        "vw": 189.65,
        "av": 48234567,
        "t": 1712345640000
      },
      "prevDay": {
        "o": 185.20,
        "h": 188.10,
        "l": 184.90,
        "c": 187.20,
        "v": 61234567,
        "vw": 186.75
      },
      "lastTrade": {
        "p": 189.70,
        "s": 100,
        "t": 1712345678123456789,
        "c": [14, 41],
        "i": "12345",
        "x": 4
      },
      "lastQuote": {
        "P": 189.75,
        "S": 2,
        "p": 189.70,
        "s": 3,
        "t": 1712345678000000000
      }
    }
  ]
}
```

**Field Glossary:**

| Path | Description |
|------|-------------|
| `tickers[].ticker` | Ticker symbol |
| `tickers[].todaysChange` | Absolute price change from previous close |
| `tickers[].todaysChangePerc` | Percentage price change from previous close |
| `tickers[].updated` | Last update timestamp (nanoseconds) |
| `tickers[].day.o/h/l/c` | Today's open/high/low/close |
| `tickers[].day.v` | Today's volume |
| `tickers[].day.vw` | Today's volume-weighted average price |
| `tickers[].min.o/h/l/c` | Current minute's OHLC |
| `tickers[].min.t` | Minute bar timestamp (milliseconds) |
| `tickers[].prevDay.c` | Previous day's close (baseline for change%) |
| `tickers[].lastTrade.p` | Last trade price |
| `tickers[].lastTrade.s` | Last trade size (shares) |
| `tickers[].lastTrade.t` | Last trade timestamp (nanoseconds) |
| `tickers[].lastQuote.p` | Bid price |
| `tickers[].lastQuote.P` | Ask price |

**The most reliable current price is `lastTrade.p`.** Fall back to `day.c` if `lastTrade` is absent (e.g., market closed).

---

### 2. Single Ticker Snapshot

Snapshot for a single ticker — same data as above but for one symbol.

**Endpoint:**
```
GET /v2/snapshot/locale/us/markets/stocks/tickers/{ticker}
```

**Example:**
```
GET https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers/AAPL?apiKey=YOUR_KEY
```

**Response:** Same structure but the `ticker` field is an object (not an array), at the top level.

---

### 3. Unified Snapshot (v3) — Alternative

The newer v3 endpoint supports cross-asset queries and up to 250 tickers via `ticker.any_of`.

**Endpoint:**
```
GET /v3/snapshot
```

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `ticker.any_of` | string | Comma-separated tickers, up to 250 |
| `type` | string | Asset class filter: `stocks`, `options`, `fx`, `crypto` |
| `limit` | integer | Max results per page (max 250) |
| `apiKey` | string | Your API key |

**Example:**
```
GET https://api.massive.com/v3/snapshot?ticker.any_of=AAPL,MSFT,TSLA&type=stocks&apiKey=YOUR_KEY
```

**Response:**
```json
{
  "status": "OK",
  "request_id": "xyz789",
  "results": [
    {
      "ticker": "AAPL",
      "type": "stocks",
      "name": "Apple Inc.",
      "market_status": "open",
      "session": {
        "change": 2.50,
        "change_percent": 1.32,
        "close": 189.70,
        "open": 187.20,
        "high": 190.50,
        "low": 186.80,
        "volume": 52341234,
        "previous_close": 187.20
      },
      "last_trade": {
        "price": 189.70,
        "size": 100,
        "timestamp": "2024-04-05T15:30:00Z"
      },
      "last_quote": {
        "bid": 189.70,
        "bid_size": 3,
        "ask": 189.75,
        "ask_size": 2,
        "timestamp": "2024-04-05T15:30:00Z"
      },
      "last_minute": {
        "open": 189.60,
        "high": 189.80,
        "low": 189.40,
        "close": 189.70,
        "volume": 234567
      }
    }
  ],
  "next_url": "https://api.massive.com/v3/snapshot?cursor=abc..."
}
```

**Note:** v3 uses cleaner field names (`price` vs `p`, `change_percent` vs `todaysChangePerc`). For this project, **use the v2 endpoint** — it's simpler, does not paginate for small watchlists, and is more widely documented.

---

## Python Code Examples

### Setup

```python
import httpx  # or requests
import os

API_BASE = "https://api.massive.com"
API_KEY = os.environ["MASSIVE_API_KEY"]
```

### Fetch prices for a list of tickers

```python
async def fetch_prices(tickers: list[str]) -> dict[str, float]:
    """Returns {ticker: price} for all tickers that have trade data."""
    ticker_param = ",".join(tickers)
    url = f"{API_BASE}/v2/snapshot/locale/us/markets/stocks/tickers"
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params={
            "tickers": ticker_param,
            "apiKey": API_KEY,
        }, timeout=10.0)
        response.raise_for_status()
    
    data = response.json()
    prices: dict[str, float] = {}
    
    for snapshot in data.get("tickers", []):
        ticker = snapshot["ticker"]
        # lastTrade.p is the most current price during market hours
        last_trade = snapshot.get("lastTrade", {})
        price = last_trade.get("p")
        # Fall back to day close if no last trade
        if price is None:
            price = snapshot.get("day", {}).get("c")
        if price is not None:
            prices[ticker] = price
    
    return prices
```

### Synchronous version (for simple polling)

```python
import requests

def fetch_prices_sync(tickers: list[str], api_key: str) -> dict[str, float]:
    ticker_param = ",".join(tickers)
    resp = requests.get(
        f"{API_BASE}/v2/snapshot/locale/us/markets/stocks/tickers",
        params={"tickers": ticker_param, "apiKey": api_key},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    
    prices = {}
    for snapshot in data.get("tickers", []):
        last_trade = snapshot.get("lastTrade", {})
        price = last_trade.get("p") or snapshot.get("day", {}).get("c")
        if price:
            prices[snapshot["ticker"]] = price
    return prices
```

### Polling loop (for background task)

```python
import asyncio

async def poll_prices_loop(
    get_tickers_fn,        # callable returning current watchlist
    on_prices_fn,          # callback: dict[str, float] -> None
    interval_seconds=15,   # 15s = 4 calls/min, safe for free tier (5/min limit)
):
    while True:
        tickers = get_tickers_fn()
        if tickers:
            try:
                prices = await fetch_prices(tickers)
                await on_prices_fn(prices)
            except Exception as e:
                print(f"[MassiveAPI] Poll error: {e}")
        await asyncio.sleep(interval_seconds)
```

---

## Error Handling

| HTTP Status | Meaning | Action |
|-------------|---------|--------|
| 200 with `status: "OK"` | Success | Parse `tickers` array |
| 200 with `status: "ERROR"` | API-level error | Log `error` field, retry |
| 400 | Bad request (e.g. invalid ticker format) | Log and skip |
| 403 | Invalid or missing API key | Fatal — check configuration |
| 429 | Rate limit exceeded | Exponential backoff, increase poll interval |
| 5xx | Massive server error | Retry with backoff |

```python
import httpx

async def safe_fetch_prices(tickers: list[str]) -> dict[str, float]:
    try:
        return await fetch_prices(tickers)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            print("[MassiveAPI] Rate limited — backing off")
        elif e.response.status_code == 403:
            print("[MassiveAPI] Invalid API key — check MASSIVE_API_KEY")
        return {}
    except httpx.TimeoutException:
        print("[MassiveAPI] Request timed out")
        return {}
```

---

## Important Behaviors

- **Empty `tickers` parameter** → returns snapshots for ALL traded symbols (thousands). Always pass explicit ticker list.
- **Unknown tickers** → silently omitted from the `tickers` array in the response. No error is raised.
- **Market closed** → `lastTrade.p` reflects the last trade from the most recent session. `day.c` is the official close.
- **Snapshot data resets** at 3:30am EST daily and populates as early as 4am EST.
- **Timestamps** in `lastTrade.t` and `updated` are in nanoseconds. `min.t` is in milliseconds.

---

## Official Resources

- [Massive API Docs](https://massive.com/docs)
- [Stocks REST API Overview](https://massive.com/docs/rest/stocks/overview)
- [Full Market Snapshot](https://massive.com/docs/rest/stocks/snapshots/full-market-snapshot)
- [Single Ticker Snapshot](https://massive.com/docs/rest/stocks/snapshots/single-ticker-snapshot)
- [Unified Snapshot (v3)](https://massive.com/docs/rest/stocks/snapshots/unified-snapshot)
- [Python Client Library](https://github.com/massive-com/client-python)
- [Rate Limit FAQ](https://massive.com/knowledge-base/article/what-is-the-request-limit-for-massives-restful-apis)
