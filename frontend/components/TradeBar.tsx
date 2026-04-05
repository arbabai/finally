"use client";

import { useState, useCallback } from "react";

interface TradeBarProps {
  selectedTicker: string | null;
  onTradeExecuted: () => void;
}

export default function TradeBar({
  selectedTicker,
  onTradeExecuted,
}: TradeBarProps) {
  const [ticker, setTicker] = useState("");
  const [quantity, setQuantity] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const activeTicker = ticker || selectedTicker || "";

  const executeTrade = useCallback(
    async (side: "buy" | "sell") => {
      const t = activeTicker.trim().toUpperCase();
      const qty = parseFloat(quantity);
      if (!t || isNaN(qty) || qty <= 0) {
        setStatus("Enter a valid ticker and quantity");
        return;
      }

      setSubmitting(true);
      setStatus(null);
      try {
        const res = await fetch("/api/portfolio/trade", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ticker: t, quantity: qty, side }),
        });
        if (res.ok) {
          setStatus(
            `${side.toUpperCase()} ${qty} ${t} executed`
          );
          setQuantity("");
          onTradeExecuted();
        } else {
          const err = await res.json();
          setStatus(err.detail || "Trade failed");
        }
      } catch {
        setStatus("Network error");
      } finally {
        setSubmitting(false);
      }
    },
    [activeTicker, quantity, onTradeExecuted]
  );

  return (
    <div className="flex items-center gap-2 px-3 py-2 border-t border-border bg-bg-panel">
      <input
        type="text"
        value={ticker}
        onChange={(e) => setTicker(e.target.value.toUpperCase())}
        placeholder={selectedTicker || "TICKER"}
        className="w-20 bg-bg-primary border border-border rounded px-2 py-1 text-xs text-text-primary placeholder:text-text-secondary focus:outline-none focus:border-blue-primary"
      />
      <input
        type="number"
        value={quantity}
        onChange={(e) => setQuantity(e.target.value)}
        placeholder="Qty"
        min="0"
        step="any"
        className="w-20 bg-bg-primary border border-border rounded px-2 py-1 text-xs text-text-primary placeholder:text-text-secondary focus:outline-none focus:border-blue-primary"
      />
      <button
        onClick={() => executeTrade("buy")}
        disabled={submitting}
        className="bg-green text-bg-primary text-xs font-bold px-3 py-1 rounded hover:opacity-80 disabled:opacity-50"
      >
        BUY
      </button>
      <button
        onClick={() => executeTrade("sell")}
        disabled={submitting}
        className="bg-red text-white text-xs font-bold px-3 py-1 rounded hover:opacity-80 disabled:opacity-50"
      >
        SELL
      </button>
      {status && (
        <span className="text-xs text-text-secondary ml-2">{status}</span>
      )}
    </div>
  );
}
