"""SQLite database layer with async access via aiosqlite.

Lazy initialization: on first call, creates all tables if missing and seeds
default data. All DDL is embedded in Python — no external SQL files.
"""

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

# ---------------------------------------------------------------------------
# DB path resolution
# ---------------------------------------------------------------------------

_DEFAULT_DB_PATH = os.environ.get(
    "DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "db", "finally.db"),
)

_db_path: str = _DEFAULT_DB_PATH
_initialized: bool = False

DEFAULT_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]


def set_db_path(path: str) -> None:
    """Override the database path (useful for tests)."""
    global _db_path, _initialized
    _db_path = path
    _initialized = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users_profile (
    id          TEXT PRIMARY KEY,
    cash_balance REAL NOT NULL DEFAULT 10000.0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist (
    id       TEXT PRIMARY KEY,
    user_id  TEXT NOT NULL DEFAULT 'default',
    ticker   TEXT NOT NULL,
    added_at TEXT NOT NULL,
    UNIQUE(user_id, ticker)
);

CREATE TABLE IF NOT EXISTS positions (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL DEFAULT 'default',
    ticker     TEXT NOT NULL,
    quantity   REAL NOT NULL,
    avg_cost   REAL NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, ticker)
);

CREATE TABLE IF NOT EXISTS trades (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL DEFAULT 'default',
    ticker      TEXT NOT NULL,
    side        TEXT NOT NULL,
    quantity    REAL NOT NULL,
    price       REAL NOT NULL,
    executed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL DEFAULT 'default',
    total_value REAL NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL DEFAULT 'default',
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    actions    TEXT,
    created_at TEXT NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

async def _connect() -> aiosqlite.Connection:
    Path(_db_path).parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(_db_path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

async def init_db() -> None:
    """Create schema and seed default data if needed."""
    global _initialized
    db = await _connect()
    try:
        await db.executescript(_SCHEMA_SQL)

        # Seed default user if not present
        cursor = await db.execute("SELECT id FROM users_profile WHERE id = ?", ("default",))
        row = await cursor.fetchone()
        if row is None:
            await db.execute(
                "INSERT INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?)",
                ("default", 10000.0, _now()),
            )

        # Seed default watchlist
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM watchlist WHERE user_id = ?", ("default",)
        )
        count = (await cursor.fetchone())["cnt"]
        if count == 0:
            now = _now()
            await db.executemany(
                "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
                [(_uuid(), "default", t, now) for t in DEFAULT_TICKERS],
            )

        await db.commit()
        _initialized = True
    finally:
        await db.close()


async def _get_db() -> aiosqlite.Connection:
    """Return a connection, lazily initializing the schema on first call."""
    if not _initialized:
        await init_db()
    return await _connect()


# ---------------------------------------------------------------------------
# User helpers
# ---------------------------------------------------------------------------

async def get_user(user_id: str = "default") -> dict:
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT id, cash_balance, created_at FROM users_profile WHERE id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise ValueError(f"User '{user_id}' not found")
        return dict(row)
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Watchlist helpers
# ---------------------------------------------------------------------------

async def get_watchlist(user_id: str = "default") -> list[str]:
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT ticker FROM watchlist WHERE user_id = ? ORDER BY added_at",
            (user_id,),
        )
        rows = await cursor.fetchall()
        return [row["ticker"] for row in rows]
    finally:
        await db.close()


async def add_ticker(ticker: str, user_id: str = "default") -> None:
    db = await _get_db()
    try:
        await db.execute(
            "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
            (_uuid(), user_id, ticker.upper(), _now()),
        )
        await db.commit()
    except aiosqlite.IntegrityError:
        pass  # already in watchlist — idempotent
    finally:
        await db.close()


async def remove_ticker(ticker: str, user_id: str = "default") -> None:
    db = await _get_db()
    try:
        await db.execute(
            "DELETE FROM watchlist WHERE user_id = ? AND ticker = ?",
            (user_id, ticker.upper()),
        )
        await db.commit()
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Positions helpers
# ---------------------------------------------------------------------------

async def get_positions(user_id: str = "default") -> list[dict]:
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT id, user_id, ticker, quantity, avg_cost, updated_at "
            "FROM positions WHERE user_id = ? ORDER BY ticker",
            (user_id,),
        )
        return [dict(row) for row in await cursor.fetchall()]
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Trade execution
# ---------------------------------------------------------------------------

async def execute_trade(
    ticker: str,
    side: str,
    quantity: float,
    price: float,
    user_id: str = "default",
) -> dict:
    """Execute a market order. Returns the trade record dict.

    Raises ValueError on insufficient cash (buy) or insufficient shares (sell).
    """
    if side not in ("buy", "sell"):
        raise ValueError(f"Invalid side '{side}'; must be 'buy' or 'sell'")
    if quantity <= 0:
        raise ValueError("Quantity must be positive")
    if price <= 0:
        raise ValueError("Price must be positive")

    ticker = ticker.upper()
    db = await _get_db()
    try:
        # Fetch user cash
        cursor = await db.execute(
            "SELECT cash_balance FROM users_profile WHERE id = ?", (user_id,)
        )
        user_row = await cursor.fetchone()
        if user_row is None:
            raise ValueError(f"User '{user_id}' not found")
        cash = user_row["cash_balance"]

        # Fetch existing position
        cursor = await db.execute(
            "SELECT id, quantity, avg_cost FROM positions WHERE user_id = ? AND ticker = ?",
            (user_id, ticker),
        )
        pos = await cursor.fetchone()

        if side == "buy":
            cost = quantity * price
            if cost > cash:
                raise ValueError(
                    f"Insufficient cash: need ${cost:.2f} but only have ${cash:.2f}"
                )
            new_cash = cash - cost

            if pos is not None:
                # Update existing position with weighted avg cost
                old_qty = pos["quantity"]
                old_cost = pos["avg_cost"]
                new_qty = old_qty + quantity
                new_avg = ((old_qty * old_cost) + (quantity * price)) / new_qty
                await db.execute(
                    "UPDATE positions SET quantity = ?, avg_cost = ?, updated_at = ? "
                    "WHERE id = ?",
                    (new_qty, new_avg, _now(), pos["id"]),
                )
            else:
                await db.execute(
                    "INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (_uuid(), user_id, ticker, quantity, price, _now()),
                )

        else:  # sell
            if pos is None or pos["quantity"] < quantity:
                available = pos["quantity"] if pos else 0
                raise ValueError(
                    f"Insufficient shares: want to sell {quantity} {ticker} "
                    f"but only hold {available}"
                )
            new_cash = cash + (quantity * price)
            new_qty = pos["quantity"] - quantity

            if new_qty == 0:
                await db.execute("DELETE FROM positions WHERE id = ?", (pos["id"],))
            else:
                await db.execute(
                    "UPDATE positions SET quantity = ?, updated_at = ? WHERE id = ?",
                    (new_qty, _now(), pos["id"]),
                )

        # Update cash
        await db.execute(
            "UPDATE users_profile SET cash_balance = ? WHERE id = ?",
            (new_cash, user_id),
        )

        # Record trade
        trade_id = _uuid()
        executed_at = _now()
        await db.execute(
            "INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (trade_id, user_id, ticker, side, quantity, price, executed_at),
        )

        await db.commit()
        return {
            "id": trade_id,
            "user_id": user_id,
            "ticker": ticker,
            "side": side,
            "quantity": quantity,
            "price": price,
            "executed_at": executed_at,
        }
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Trade history
# ---------------------------------------------------------------------------

async def get_trade_history(user_id: str = "default") -> list[dict]:
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT id, user_id, ticker, side, quantity, price, executed_at "
            "FROM trades WHERE user_id = ? ORDER BY executed_at",
            (user_id,),
        )
        return [dict(row) for row in await cursor.fetchall()]
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Portfolio snapshots
# ---------------------------------------------------------------------------

async def record_portfolio_snapshot(total_value: float, user_id: str = "default") -> None:
    db = await _get_db()
    try:
        await db.execute(
            "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) "
            "VALUES (?, ?, ?, ?)",
            (_uuid(), user_id, total_value, _now()),
        )
        await db.commit()
    finally:
        await db.close()


async def get_portfolio_history(user_id: str = "default") -> list[dict]:
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT id, user_id, total_value, recorded_at "
            "FROM portfolio_snapshots WHERE user_id = ? ORDER BY recorded_at",
            (user_id,),
        )
        return [dict(row) for row in await cursor.fetchall()]
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Chat messages
# ---------------------------------------------------------------------------

async def get_chat_messages(user_id: str = "default", limit: int = 20) -> list[dict]:
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT id, user_id, role, content, actions, created_at "
            "FROM chat_messages WHERE user_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        )
        rows = [dict(row) for row in await cursor.fetchall()]
        rows.reverse()  # return in chronological order
        return rows
    finally:
        await db.close()


async def save_chat_message(
    role: str,
    content: str,
    actions: str | None = None,
    user_id: str = "default",
) -> dict:
    db = await _get_db()
    try:
        msg_id = _uuid()
        created_at = _now()
        await db.execute(
            "INSERT INTO chat_messages (id, user_id, role, content, actions, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (msg_id, user_id, role, content, actions, created_at),
        )
        await db.commit()
        return {
            "id": msg_id,
            "user_id": user_id,
            "role": role,
            "content": content,
            "actions": actions,
            "created_at": created_at,
        }
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

async def reset_portfolio(user_id: str = "default") -> None:
    """Reset portfolio to initial state: $10k cash, no positions/trades/snapshots/chat."""
    db = await _get_db()
    try:
        await db.execute(
            "UPDATE users_profile SET cash_balance = 10000.0 WHERE id = ?", (user_id,)
        )
        await db.execute("DELETE FROM positions WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM trades WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM portfolio_snapshots WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM chat_messages WHERE user_id = ?", (user_id,))
        await db.commit()
    finally:
        await db.close()
