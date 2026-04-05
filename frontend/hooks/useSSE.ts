"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import type { PriceUpdate, TickerState, ConnectionStatus } from "@/types";

const MAX_HISTORY_POINTS = 300;

export function useSSE() {
  const [prices, setPrices] = useState<Record<string, TickerState>>({});
  const [connectionStatus, setConnectionStatus] =
    useState<ConnectionStatus>("disconnected");
  const eventSourceRef = useRef<EventSource | null>(null);
  const pricesRef = useRef<Record<string, TickerState>>({});

  // Keep ref in sync so the SSE callback always sees latest state
  pricesRef.current = prices;

  const connect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const es = new EventSource("/api/stream/prices");
    eventSourceRef.current = es;

    es.onopen = () => {
      setConnectionStatus("connected");
    };

    // Backend sends named "price" events — must use addEventListener, not onmessage
    const handlePrice = (event: MessageEvent) => {
      try {
        const update: PriceUpdate = JSON.parse(event.data);
        setPrices((prev) => {
          const existing = prev[update.ticker];
          const now = Date.now();
          const newHistory = existing?.priceHistory
            ? [
                ...existing.priceHistory,
                { time: now, price: update.price },
              ].slice(-MAX_HISTORY_POINTS)
            : [{ time: now, price: update.price }];

          return {
            ...prev,
            [update.ticker]: {
              ticker: update.ticker,
              price: update.price,
              previousPrice: update.prev_price,
              direction: update.direction,
              firstPrice: existing?.firstPrice ?? update.price,
              priceHistory: newHistory,
              lastUpdate: now,
            },
          };
        });
      } catch {
        // Ignore malformed events
      }
    };

    es.addEventListener("price", handlePrice);

    es.onerror = () => {
      setConnectionStatus("reconnecting");
      // EventSource auto-reconnects; we just track state
    };
  }, []);

  useEffect(() => {
    connect();
    return () => {
      eventSourceRef.current?.close();
    };
  }, [connect]);

  return { prices, connectionStatus };
}
