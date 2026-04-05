"use client";

import { useState, useCallback, useEffect } from "react";
import Header from "@/components/Header";
import Watchlist from "@/components/Watchlist";
import MainChart from "@/components/MainChart";
import TradeBar from "@/components/TradeBar";
import PositionsTable from "@/components/PositionsTable";
import PortfolioHeatmap from "@/components/PortfolioHeatmap";
import PnLChart from "@/components/PnLChart";
import ChatPanel from "@/components/ChatPanel";
import { useSSE } from "@/hooks/useSSE";
import { usePortfolio } from "@/hooks/usePortfolio";

export default function Home() {
  const { prices, connectionStatus } = useSSE();
  const { portfolio, history, refresh: refreshPortfolio } = usePortfolio();
  const [watchlist, setWatchlist] = useState<string[]>([]);
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);

  const fetchWatchlist = useCallback(async () => {
    try {
      const res = await fetch("/api/watchlist");
      if (res.ok) {
        const data = await res.json();
        const tickers = data.map(
          (item: { ticker: string }) => item.ticker
        );
        setWatchlist(tickers);
        if (!selectedTicker && tickers.length > 0) {
          setSelectedTicker(tickers[0]);
        }
      }
    } catch (err) {
      console.error("Failed to fetch watchlist:", err);
    }
  }, [selectedTicker]);

  useEffect(() => {
    fetchWatchlist();
  }, [fetchWatchlist]);

  const handleTradeExecuted = useCallback(() => {
    refreshPortfolio();
  }, [refreshPortfolio]);

  const handleWatchlistChange = useCallback(() => {
    fetchWatchlist();
  }, [fetchWatchlist]);

  return (
    <div className="h-full flex flex-col">
      <Header
        totalValue={portfolio?.total_value ?? null}
        cashBalance={portfolio?.cash_balance ?? null}
        connectionStatus={connectionStatus}
      />
      <div className="flex-1 flex overflow-hidden">
        {/* Left: Watchlist */}
        <div className="w-64 border-r border-border bg-bg-panel flex-shrink-0 flex flex-col">
          <Watchlist
            watchlist={watchlist}
            prices={prices}
            selectedTicker={selectedTicker}
            onSelectTicker={setSelectedTicker}
            onWatchlistChange={handleWatchlistChange}
          />
        </div>

        {/* Center: Chart + Trade + Positions */}
        <div className="flex-1 flex flex-col min-w-0">
          <div className="flex-1 min-h-0">
            <MainChart
              tickerState={selectedTicker ? prices[selectedTicker] ?? null : null}
              ticker={selectedTicker}
            />
          </div>
          <TradeBar
            selectedTicker={selectedTicker}
            onTradeExecuted={handleTradeExecuted}
          />
          <div className="border-t border-border bg-bg-panel" style={{ maxHeight: "35%" }}>
            <div className="px-3 py-1.5 border-b border-border">
              <h2 className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
                Positions
              </h2>
            </div>
            <div className="overflow-y-auto" style={{ maxHeight: "calc(100% - 28px)" }}>
              <PositionsTable positions={portfolio?.positions ?? []} />
            </div>
          </div>
        </div>

        {/* Right: Portfolio + Chat */}
        <div className="w-80 border-l border-border bg-bg-panel flex-shrink-0 flex flex-col">
          {/* Portfolio Heatmap */}
          <div className="border-b border-border" style={{ height: "25%" }}>
            <div className="px-3 py-1.5 border-b border-border">
              <h2 className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
                Portfolio
              </h2>
            </div>
            <div className="p-1" style={{ height: "calc(100% - 28px)" }}>
              <PortfolioHeatmap positions={portfolio?.positions ?? []} />
            </div>
          </div>

          {/* P&L Chart */}
          <div className="border-b border-border" style={{ height: "20%" }}>
            <div className="px-3 py-1.5 border-b border-border">
              <h2 className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
                P&L
              </h2>
            </div>
            <div style={{ height: "calc(100% - 28px)" }}>
              <PnLChart history={history} />
            </div>
          </div>

          {/* Chat */}
          <div className="flex-1 min-h-0">
            <ChatPanel
              onTradeExecuted={handleTradeExecuted}
              onWatchlistChange={handleWatchlistChange}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
