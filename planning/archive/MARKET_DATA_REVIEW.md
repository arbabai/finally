# Market Data Backend — Code Review

**Date:** 2026-04-04  
**Reviewer:** Claude Code (Sonnet 4.6)  
**Scope:** `backend/app/market/` and `backend/tests/market/`

---

## Test Results

```
75 collected | 74 passed | 1 FAILED
```

| Module | Tests | Result |
|--------|-------|--------|
| `test_models.py` | 10 | All pass |
| `test_cache.py` | 13 | All pass |
| `test_factory.py` | 9 | All pass |
| `test_simulator.py` | 23 | All pass |
| `test_massive_client.py` | 20 | **1 FAIL** |

### Setup note

Running `uv run pytest` without first running `uv sync --extra dev` produced a collection error (`ModuleNotFoundError: No module named 'respx'`). Dev dependencies must be installed explicitly. This is expected uv behaviour but should be documented in the project README.

---

## Failing Test

### `test_massive_client.py::test_start_tracks_prev_price`

**Error:**
```
AssertionError: assert 191.0 == 189.7
 +  where 191.0 = PricePoint(..., prev_price=191.0, ...).prev_price
```

**Root cause — timing bug in the test, not the implementation.**

The test sets `poll_interval=0.1` and sleeps for `0.35s`, expecting exactly 2 polls to have fired. At 0.1s intervals, 3–4 polls actually complete in that window:

| t=0.0 | Poll 1: price=189.70, `_prev_prices["AAPL"]=189.70` |
|-------|------------------------------------------------------|
| t=0.1 | Poll 2: price=191.00, `prev_price=189.70` ✓ |
| t=0.2 | Poll 3: price=191.00, `prev_price=191.00` ← overwrites cache |
| t=0.3 | Poll 4: price=191.00, `prev_price=191.00` |
| t=0.35 | `stop()` called |

After poll 3, `price == prev_price == 191.00`. The assertion `result.prev_price == 189.70` fails because the cache holds the result of the later polls, not poll 2.

**Fix:** Change `poll_interval=0.5` (so only 1 poll fires in 0.35 s) and add a second tick manually, or restructure using an event/counter to stop after exactly 2 calls.

```python
# Minimal fix — use a poll_interval long enough to guarantee only 1 poll
# before stopping, then assert on the FIRST poll result separately.
# Or control iteration count explicitly:

stop_after = 2

def response_factory(request):
    nonlocal call_count
    call_count += 1
    if call_count >= stop_after:
        asyncio.get_event_loop().call_soon(lambda: asyncio.ensure_future(client.stop()))
    price = 189.70 if call_count == 1 else 191.00
    return httpx.Response(200, json={...})
```

---

## Module-by-Module Review

### `models.py` — PricePoint

**Status: Correct and clean.**

- `from_prices()` factory method correctly derives `change_direction`.
- `to_sse_dict()` rounds prices to 4 decimal places — a sensible improvement over the design doc's unrounded version. Prevents floating-point noise in the SSE payload.
- `timestamp` uses `time.time()` at construction time, which is correct for event-time semantics.

No issues.

---

### `interface.py` — MarketDataSource ABC

**Status: Correct.**

Uses `from __future__ import annotations` with `TYPE_CHECKING` guard to avoid a circular import between `interface.py` and `cache.py`. This is the right pattern. Both concrete implementations satisfy all five abstract methods.

---

### `cache.py` — PriceCache

**Status: Correct. One minor observation.**

- Fan-out to subscribers happens **outside** the lock (lines 29–33). This is intentional and correct: `queue.put_nowait()` is non-blocking and requires no lock. Holding the lock during fan-out would unnecessarily serialise subscriber delivery.
- Queue `maxsize=200` matches the authoritative `MARKET_DATA_DESIGN.md` (the `MARKET_INTERFACE.md` draft had 100). Correct.
- `get_all()` returns a shallow copy of the dict — tests verify this. Mutating the returned dict does not affect the cache, which is the right contract.

**Minor observation:** There is no `clear()` method to purge all tickers at once (e.g., on a full portfolio reset). Not required for MVP; note for future extension.

---

### `simulator.py` — MarketSimulator

**Status: Correct. One spec deviation (low risk).**

**GBM implementation:** Mathematically correct. Ito correction (`μ − σ²/2`) is applied, sector correlation is properly composed using `ρZ_sector + √(1−ρ²)Z_individual`, and the price floor (`max(price, 0.01)`) guards against degenerate float states.

**State snapshot pattern in `start()`:**
```python
states = dict(self._states)          # snapshot
self._tick(states)                   # mutate snapshot
for state in states.values():
    if state.ticker in self._states: # guard removed tickers
        self._states[state.ticker].price = state.price
        ...
```
This is more careful than the design doc, which called `_tick(self._states)` directly. The snapshot approach correctly handles tickers removed while the tick is in progress. Good defensive coding.

**Spec deviation — no exception handling in `start()`:**

The interface contract states: *"No exception may escape `start()` — all errors are caught, logged, and the loop continues."* `MassiveClient.start()` wraps its loop body in `try/except`. `MarketSimulator.start()` does not:

```python
async def start(self, cache: PriceCache) -> None:
    self._running = True
    while self._running:
        ...
        self._tick(states)       # no try/except
        for state in states.values():
            await cache.update(point)  # no try/except
```

In practice, GBM math cannot raise and `cache.update()` is unlikely to fail. But it is a contract violation. Adding a try/except around the loop body (with a `print(f"[Simulator] Error: {e}")` log) would bring it into compliance at zero runtime cost.

---

### `massive_client.py` — MassiveClient

**Status: Correct. One behavioural note on shutdown timing.**

**Error handling:** All three exception classes (`HTTPStatusError`, `TimeoutException`, generic `Exception`) are handled with distinct log messages. The 403/429 cases get actionable guidance. This matches the spec.

**`prev_price` tracking:** Uses `_prev_prices` dict to carry prices between polls, seeding the first poll's `prev_price` to `price` (so the first event is always `direction="flat"`). This is correct — there is no meaningful "previous" price before the first poll.

**`remove_ticker()` clears `_prev_prices`:** Correct — avoids stale prev_price being used if the ticker is re-added later.

**Shutdown timing note:**
`stop()` sets `_running = False`, but the loop only checks this flag at the top of the `while` loop — after `asyncio.sleep(self._poll_interval)` completes. For the default 15-second interval, this means the task stays alive for up to 15 seconds after `stop()` is called.

This is acceptable because the FastAPI lifespan handler calls `task.cancel()` immediately after `stop()`:
```python
await source.stop()
task.cancel()        # ← cancels the sleep, terminates immediately
```
The `asyncio.CancelledError` is caught. Shutdown is fast in practice. However, if `stop()` were used standalone (without `task.cancel()`), the caller would wait up to one poll interval. This is worth noting but is not a bug given the current integration pattern.

**`_lock` and `_task` attributes from design doc are absent:** Correctly omitted. The `asyncio.Lock` on `_tickers` is unnecessary (single-threaded asyncio event loop); `_task` is managed by the caller, not the client.

---

### `factory.py` — create_market_source

**Status: Correct. One addition beyond spec.**

Supports `MASSIVE_POLL_INTERVAL` environment variable, allowing poll interval override without code changes. This is a useful operational feature not present in the design docs. No issues.

---

## Test Coverage Assessment

| Area | Coverage | Notes |
|------|----------|-------|
| `PricePoint` directions | Full | All three cases tested |
| `PricePoint.to_sse_dict()` | Full | Keys, values, rounding |
| `PriceCache` reads/writes | Full | get, get_all, remove, overwrite |
| `PriceCache` subscriptions | Full | subscribe, unsubscribe, fan-out, slow consumer |
| `MarketSimulator` watchlist | Full | add, remove, idempotency, case normalisation |
| `MarketSimulator` GBM | Good | prev_price chain, price floor, multi-sector |
| `MarketSimulator` lifecycle | Full | start, stop, dynamic add/remove during run |
| `MassiveClient` watchlist | Full | add, remove, prev_price cleanup |
| `MassiveClient` HTTP parsing | Full | lastTrade priority, day.c fallback, missing fields |
| `MassiveClient` error handling | Full | 403, 429, timeout, empty watchlist |
| `MassiveClient` prev_price tracking | **Partial** | Test exists but has timing bug (see above) |
| Factory selection | Full | All env var combinations |

**Notable gaps (not blocking for MVP):**
- No test for the simulator's correlated noise property (e.g., asserting that tech stocks move in the same direction more than 50% of the time with ρ=0.6). This would be a statistical/simulation-quality test, appropriate for a later milestone.
- No test for `MassiveClient` handling of `200 status: "ERROR"` API-level response (the API can return HTTP 200 with an error payload — the current code would treat it as success and find no tickers in the empty array, which is actually correct behaviour, but it's not explicitly tested).

---

## Summary of Issues

| Severity | Issue | Location |
|----------|-------|----------|
| **Bug** | Test timing: `test_start_tracks_prev_price` fails due to too many polls completing within the sleep window | `test_massive_client.py:209` |
| **Minor** | `MarketSimulator.start()` lacks exception handling around loop body — contract violation (low real-world risk) | `simulator.py:106` |
| **Note** | Dev dependencies require explicit `uv sync --extra dev` — not obvious from project root README | `pyproject.toml` |
| **Note** | `MassiveClient` shutdown latency up to `poll_interval` seconds when `stop()` is called without `task.cancel()` | `massive_client.py:44` |

---

## Conclusion

The Market Data backend is well-implemented and closely follows the `MARKET_DATA_DESIGN.md` specification. The architecture is clean: a clear ABC with two drop-in implementations, a shared `PriceCache` with proper subscriber fan-out, and a simple env-driven factory. 74 of 75 tests pass.

The single test failure is a timing bug in the test itself, not the production code — the `MassiveClient.start()` logic for tracking `prev_price` across polls is correct.

The two substantive items to address before the next development phase are:

1. **Fix `test_start_tracks_prev_price`** — adjust poll_interval or sleep duration so exactly 2 polls fire, making the assertion deterministic.
2. **Add try/except to `MarketSimulator.start()`** — wrap the loop body to satisfy the interface contract and prevent any future extension from inadvertently breaking the simulator loop.

Everything else is ready to integrate with the rest of the backend (SSE streaming, watchlist routes, lifespan manager).
