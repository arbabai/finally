"""LLM chat integration — structured output via LiteLLM + OpenRouter (Cerebras).

Builds portfolio context, calls the LLM (or returns mock), auto-executes
trades and watchlist changes, and persists messages to the DB.
"""

import json
import os
from typing import Optional

from litellm import completion
from pydantic import BaseModel, Field

from . import database as db
from .market.cache import PriceCache
from .market.interface import MarketDataSource

# ---------------------------------------------------------------------------
# LiteLLM / OpenRouter constants (Cerebras inference)
# ---------------------------------------------------------------------------

MODEL = "openrouter/openai/gpt-oss-120b"
EXTRA_BODY = {"provider": {"order": ["cerebras"]}}

# ---------------------------------------------------------------------------
# Structured output schema
# ---------------------------------------------------------------------------


class TradeAction(BaseModel):
    ticker: str
    side: str  # "buy" or "sell"
    quantity: float


class WatchlistChange(BaseModel):
    ticker: str
    action: str  # "add" or "remove"


class ChatResponse(BaseModel):
    message: str
    trades: list[TradeAction] = Field(default_factory=list)
    watchlist_changes: list[WatchlistChange] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are FinAlly, an AI trading assistant inside a simulated trading workstation. \
You help users manage a virtual portfolio with fake money — there is zero real-world risk.

Your capabilities:
- Analyze portfolio composition, risk concentration, and P&L
- Suggest trades with concise reasoning
- Execute trades when the user asks or agrees (buy/sell at current market price)
- Manage the watchlist: add or remove tickers proactively when relevant

Guidelines:
- Be concise and data-driven. Lead with numbers, not filler.
- When executing trades, include them in the "trades" array of your response.
- When changing the watchlist, include changes in the "watchlist_changes" array.
- Always respond with valid JSON matching the required schema.
- If the user asks to buy/sell, execute immediately — this is simulated money.
- If a request is ambiguous, clarify before executing.\
"""

# ---------------------------------------------------------------------------
# Mock response (LLM_MOCK=true)
# ---------------------------------------------------------------------------

MOCK_RESPONSE = ChatResponse(
    message="I'm your AI trading assistant. How can I help you today?",
    trades=[],
    watchlist_changes=[],
)


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------


async def build_portfolio_context(cache: PriceCache, user_id: str = "default") -> str:
    """Build a formatted string summarising the user's portfolio state."""
    user = await db.get_user(user_id)
    cash = user["cash_balance"]

    positions = await db.get_positions(user_id)
    watchlist_tickers = await db.get_watchlist(user_id)

    # Enrich positions with live prices
    position_lines: list[str] = []
    total_position_value = 0.0
    for pos in positions:
        ticker = pos["ticker"]
        pp = await cache.get(ticker)
        current_price = pp.price if pp else pos["avg_cost"]  # fallback to avg cost
        qty = pos["quantity"]
        market_value = qty * current_price
        cost_basis = qty * pos["avg_cost"]
        unrealized_pnl = market_value - cost_basis
        pnl_pct = (unrealized_pnl / cost_basis * 100) if cost_basis else 0.0
        total_position_value += market_value
        position_lines.append(
            f"  {ticker}: {qty:.2f} shares @ avg ${pos['avg_cost']:.2f}, "
            f"current ${current_price:.2f}, "
            f"P&L ${unrealized_pnl:+.2f} ({pnl_pct:+.1f}%)"
        )

    total_value = cash + total_position_value

    # Watchlist with prices
    watchlist_lines: list[str] = []
    for ticker in watchlist_tickers:
        pp = await cache.get(ticker)
        if pp:
            watchlist_lines.append(f"  {ticker}: ${pp.price:.2f}")
        else:
            watchlist_lines.append(f"  {ticker}: (no price)")

    parts = [
        f"Cash: ${cash:,.2f}",
        f"Total portfolio value: ${total_value:,.2f}",
    ]
    if position_lines:
        parts.append("Positions:\n" + "\n".join(position_lines))
    else:
        parts.append("Positions: none")
    parts.append("Watchlist:\n" + "\n".join(watchlist_lines) if watchlist_lines else "Watchlist: empty")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main chat processing
# ---------------------------------------------------------------------------


async def process_chat(
    message: str,
    cache: PriceCache,
    market_source: Optional[MarketDataSource] = None,
    user_id: str = "default",
) -> dict:
    """Process a user chat message through the LLM pipeline.

    1. Build portfolio context
    2. Load conversation history
    3. Call LLM (or return mock)
    4. Auto-execute trades and watchlist changes
    5. Persist messages
    6. Return result dict
    """
    # 1. Build context
    context = await build_portfolio_context(cache, user_id)

    # 2. Load history
    history_rows = await db.get_chat_messages(user_id, limit=20)
    history_messages = [
        {"role": row["role"], "content": row["content"]}
        for row in history_rows
    ]

    # 3. Call LLM or mock
    if os.environ.get("LLM_MOCK", "").lower() == "true":
        parsed = MOCK_RESPONSE
    else:
        parsed = await _call_llm(context, history_messages, message)

    # 4. Auto-execute trades
    trades_executed: list[dict] = []
    errors: list[str] = []

    for trade in parsed.trades:
        try:
            # Get current price from cache
            pp = await cache.get(trade.ticker.upper())
            if pp is None:
                errors.append(f"No price available for {trade.ticker}")
                continue
            result = await db.execute_trade(
                ticker=trade.ticker,
                side=trade.side,
                quantity=trade.quantity,
                price=pp.price,
                user_id=user_id,
            )
            result["status"] = "success"
            trades_executed.append(result)
        except ValueError as e:
            errors.append(str(e))
            trades_executed.append({
                "ticker": trade.ticker,
                "side": trade.side,
                "quantity": trade.quantity,
                "price": 0,
                "status": "error",
                "error": str(e),
            })

    # 5. Auto-execute watchlist changes
    watchlist_changes_executed: list[dict] = []

    for change in parsed.watchlist_changes:
        ticker = change.ticker.upper()
        try:
            if change.action == "add":
                await db.add_ticker(ticker, user_id)
                if market_source:
                    market_source.add_ticker(ticker)
                watchlist_changes_executed.append({"ticker": ticker, "action": "add", "status": "success"})
            elif change.action == "remove":
                await db.remove_ticker(ticker, user_id)
                if market_source:
                    market_source.remove_ticker(ticker)
                if cache:
                    await cache.remove(ticker)
                watchlist_changes_executed.append({"ticker": ticker, "action": "remove", "status": "success"})
        except Exception as e:
            errors.append(f"Watchlist change failed for {ticker}: {e}")
            watchlist_changes_executed.append({"ticker": ticker, "action": change.action, "status": "error", "error": str(e)})

    # 6. Persist messages
    await db.save_chat_message(role="user", content=message, user_id=user_id)

    actions = {
        "trades_executed": trades_executed,
        "watchlist_changes_executed": watchlist_changes_executed,
        "errors": errors,
    }
    await db.save_chat_message(
        role="assistant",
        content=parsed.message,
        actions=json.dumps(actions),
        user_id=user_id,
    )

    # 7. Return
    return {
        "message": parsed.message,
        "trades_executed": trades_executed,
        "watchlist_changes_executed": watchlist_changes_executed,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# LLM call (internal)
# ---------------------------------------------------------------------------


async def _call_llm(
    context: str,
    history: list[dict],
    user_message: str,
) -> ChatResponse:
    """Call the LLM via LiteLLM/OpenRouter and return a parsed ChatResponse."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"Current portfolio state:\n{context}"},
        *history,
        {"role": "user", "content": user_message},
    ]

    content = None
    try:
        response = completion(
            model=MODEL,
            messages=messages,
            response_format=ChatResponse,
            reasoning_effort="low",
            extra_body=EXTRA_BODY,
        )
        content = response.choices[0].message.content
        return ChatResponse.model_validate_json(content)
    except Exception:
        # Attempt raw JSON parse if structured output wrapper failed but content arrived
        if content:
            try:
                return ChatResponse.model_validate_json(content)
            except Exception:
                pass
        # Last resort: return a graceful fallback
        return ChatResponse(
            message="I encountered an issue processing your request. Please try again.",
            trades=[],
            watchlist_changes=[],
        )
