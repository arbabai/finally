"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import type { TickerState, WatchlistItem } from "@/types";
import SparkLine from "./SparkLine";

function formatPrice(price: number): string {
  return price.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatPercent(value: number): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

interface WatchlistProps {
  watchlist: string[];
  prices: Record<string, TickerState>;
  selectedTicker: string | null;
  onSelectTicker: (ticker: string) => void;
  onWatchlistChange: () => void;
}

export default function Watchlist({
  watchlist,
  prices,
  selectedTicker,
  onSelectTicker,
  onWatchlistChange,
}: WatchlistProps) {
  const [newTicker, setNewTicker] = useState("");
  const [adding, setAdding] = useState(false);
  // Track which tickers are currently flashing
  const [flashMap, setFlashMap] = useState<Record<string, "up" | "down">>({});
  const prevPricesRef = useRef<Record<string, number>>({});

  // Detect price changes and trigger flash
  useEffect(() => {
    const newFlashes: Record<string, "up" | "down"> = {};
    for (const ticker of watchlist) {
      const ts = prices[ticker];
      if (!ts) continue;
      const prevPrice = prevPricesRef.current[ticker];
      if (prevPrice !== undefined && ts.price !== prevPrice) {
        newFlashes[ticker] = ts.price > prevPrice ? "up" : "down";
      }
      prevPricesRef.current[ticker] = ts.price;
    }
    if (Object.keys(newFlashes).length > 0) {
      setFlashMap((prev) => ({ ...prev, ...newFlashes }));
      // Clear flashes after animation
      const timeout = setTimeout(() => {
        setFlashMap((prev) => {
          const next = { ...prev };
          for (const t of Object.keys(newFlashes)) {
            delete next[t];
          }
          return next;
        });
      }, 500);
      return () => clearTimeout(timeout);
    }
  }, [prices, watchlist]);

  const addTicker = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      const ticker = newTicker.trim().toUpperCase();
      if (!ticker) return;
      setAdding(true);
      try {
        const res = await fetch("/api/watchlist", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ticker }),
        });
        if (res.ok) {
          setNewTicker("");
          onWatchlistChange();
        }
      } catch {
        // Ignore
      } finally {
        setAdding(false);
      }
    },
    [newTicker, onWatchlistChange]
  );

  const removeTicker = useCallback(
    async (ticker: string) => {
      try {
        const res = await fetch(`/api/watchlist/${ticker}`, {
          method: "DELETE",
        });
        if (res.ok) {
          onWatchlistChange();
        }
      } catch {
        // Ignore
      }
    },
    [onWatchlistChange]
  );

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-2 border-b border-border">
        <h2 className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
          Watchlist
        </h2>
      </div>
      <div className="flex-1 overflow-y-auto">
        {watchlist.map((ticker) => {
          const ts = prices[ticker];
          const sessionChange =
            ts && ts.firstPrice
              ? ((ts.price - ts.firstPrice) / ts.firstPrice) * 100
              : null;
          const isSelected = ticker === selectedTicker;
          const flash = flashMap[ticker];

          return (
            <div
              key={ticker}
              onClick={() => onSelectTicker(ticker)}
              className={`flex items-center justify-between px-3 py-2 sm:py-1.5 cursor-pointer border-b border-border/50 hover:bg-bg-primary/50 transition-colors ${
                isSelected ? "bg-bg-primary" : ""
              } ${flash === "up" ? "price-flash-up" : flash === "down" ? "price-flash-down" : ""}`}
            >
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold text-text-primary">
                  {ticker}
                </div>
                {sessionChange !== null && (
                  <div
                    className={`text-xs ${
                      sessionChange >= 0 ? "text-green" : "text-red"
                    }`}
                  >
                    {formatPercent(sessionChange)}
                  </div>
                )}
              </div>
              <div className="flex items-center gap-2">
                {ts && ts.priceHistory.length > 1 && (
                  <SparkLine data={ts.priceHistory} />
                )}
                <div className="text-right min-w-[70px]">
                  <div
                    className={`text-sm font-mono ${
                      ts?.direction === "up"
                        ? "text-green"
                        : ts?.direction === "down"
                        ? "text-red"
                        : "text-text-primary"
                    }`}
                  >
                    {ts ? formatPrice(ts.price) : "---"}
                  </div>
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    removeTicker(ticker);
                  }}
                  className="text-text-secondary hover:text-red text-xs px-1 opacity-0 group-hover:opacity-100 hover:opacity-100 transition-opacity"
                  title="Remove"
                  style={{ opacity: 1 }}
                >
                  x
                </button>
              </div>
            </div>
          );
        })}
      </div>
      <form
        onSubmit={addTicker}
        className="flex gap-1 p-2 border-t border-border"
      >
        <input
          type="text"
          value={newTicker}
          onChange={(e) => setNewTicker(e.target.value)}
          placeholder="Add ticker..."
          className="flex-1 bg-bg-primary border border-border rounded px-2 py-1 text-xs text-text-primary placeholder:text-text-secondary focus:outline-none focus:border-blue-primary"
        />
        <button
          type="submit"
          disabled={adding}
          className="bg-purple text-white text-xs px-2 py-1 rounded hover:opacity-80 disabled:opacity-50"
        >
          Add
        </button>
      </form>
    </div>
  );
}
