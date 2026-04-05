"use client";

import { useState, useEffect, useCallback } from "react";
import type { Portfolio, PortfolioSnapshot } from "@/types";

export function usePortfolio() {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [history, setHistory] = useState<PortfolioSnapshot[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchPortfolio = useCallback(async () => {
    try {
      const res = await fetch("/api/portfolio");
      if (res.ok) {
        const data: Portfolio = await res.json();
        setPortfolio(data);
      }
    } catch {
      // Network error — will retry on next poll
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchHistory = useCallback(async () => {
    try {
      const res = await fetch("/api/portfolio/history");
      if (res.ok) {
        const data: PortfolioSnapshot[] = await res.json();
        setHistory(data);
      }
    } catch {
      // Ignore
    }
  }, []);

  useEffect(() => {
    fetchPortfolio();
    fetchHistory();
    const interval = setInterval(() => {
      fetchPortfolio();
      fetchHistory();
    }, 5000);
    return () => clearInterval(interval);
  }, [fetchPortfolio, fetchHistory]);

  return { portfolio, history, loading, refresh: fetchPortfolio };
}
