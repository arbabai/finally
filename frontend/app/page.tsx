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

type MobileTab = "watchlist" | "chart" | "portfolio" | "chat";

export default function Home() {
  const { prices, connectionStatus } = useSSE();
  const { portfolio, history, refresh: refreshPortfolio } = usePortfolio();
  const [watchlist, setWatchlist] = useState<string[]>([]);
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [mobileTab, setMobileTab] = useState<MobileTab>("watchlist");

  const fetchWatchlist = useCallback(async () => {
    try {
      const res = await fetch("/api/watchlist");
      if (res.ok) {
        const data = await res.json();
        const tickers = data.map((item: { ticker: string }) => item.ticker);
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

  const handleSelectTicker = useCallback((ticker: string) => {
    setSelectedTicker(ticker);
    setMobileTab("chart"); // auto-switch to chart tab on mobile when ticker selected
  }, []);

  // ── Shared panel components ──────────────────────────────────────────────

  const watchlistPanel = (
    <Watchlist
      watchlist={watchlist}
      prices={prices}
      selectedTicker={selectedTicker}
      onSelectTicker={handleSelectTicker}
      onWatchlistChange={handleWatchlistChange}
    />
  );

  const chartPanel = (
    <div className="flex flex-col h-full">
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
      <div className="border-t border-border bg-bg-panel overflow-y-auto" style={{ maxHeight: "40%" }}>
        <div className="px-3 py-1.5 border-b border-border sticky top-0 bg-bg-panel z-10">
          <h2 className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
            Positions
          </h2>
        </div>
        <PositionsTable positions={portfolio?.positions ?? []} />
      </div>
    </div>
  );

  const portfolioPanel = (
    <div className="flex flex-col h-full">
      <div className="border-b border-border" style={{ height: "45%" }}>
        <div className="px-3 py-1.5 border-b border-border">
          <h2 className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
            Portfolio Heatmap
          </h2>
        </div>
        <div className="p-1" style={{ height: "calc(100% - 28px)" }}>
          <PortfolioHeatmap positions={portfolio?.positions ?? []} />
        </div>
      </div>
      <div className="flex-1 min-h-0">
        <div className="px-3 py-1.5 border-b border-border">
          <h2 className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
            P&L History
          </h2>
        </div>
        <div style={{ height: "calc(100% - 28px)" }}>
          <PnLChart history={history} />
        </div>
      </div>
    </div>
  );

  const chatPanel = (
    <ChatPanel
      onTradeExecuted={handleTradeExecuted}
      onWatchlistChange={handleWatchlistChange}
    />
  );

  // ── Mobile tab icon helpers ──────────────────────────────────────────────

  const tabBtn = (tab: MobileTab, label: string, icon: string) => (
    <button
      onClick={() => setMobileTab(tab)}
      className={`flex flex-col items-center justify-center gap-0.5 flex-1 py-2 text-[10px] transition-colors ${
        mobileTab === tab
          ? "text-accent-yellow border-t-2 border-accent-yellow"
          : "text-text-secondary border-t-2 border-transparent"
      }`}
    >
      <span className="text-base leading-none">{icon}</span>
      {label}
    </button>
  );

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <div className="h-full flex flex-col">
      <Header
        totalValue={portfolio?.total_value ?? null}
        cashBalance={portfolio?.cash_balance ?? null}
        connectionStatus={connectionStatus}
      />

      {/* ── DESKTOP: 3-column layout (hidden on mobile) ── */}
      <div className="hidden lg:flex flex-1 overflow-hidden">
        {/* Left: Watchlist */}
        <div className="w-64 border-r border-border bg-bg-panel flex-shrink-0 flex flex-col">
          {watchlistPanel}
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

        {/* Right: Portfolio + P&L + Chat */}
        <div className="w-80 border-l border-border bg-bg-panel flex-shrink-0 flex flex-col">
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
          <div className="flex-1 min-h-0">
            {chatPanel}
          </div>
        </div>
      </div>

      {/* ── MOBILE: tab content + bottom nav (shown on mobile only) ── */}
      <div className="flex lg:hidden flex-1 flex-col overflow-hidden">
        {/* Tab content area */}
        <div className="flex-1 overflow-y-auto overflow-x-hidden">
          {mobileTab === "watchlist" && (
            <div className="h-full">{watchlistPanel}</div>
          )}
          {mobileTab === "chart" && (
            <div style={{ minHeight: "100%" }}>{chartPanel}</div>
          )}
          {mobileTab === "portfolio" && (
            <div style={{ minHeight: "100%" }}>{portfolioPanel}</div>
          )}
          {mobileTab === "chat" && (
            <div className="h-full">{chatPanel}</div>
          )}
        </div>

        {/* Bottom tab bar */}
        <div className="flex-shrink-0 flex border-t border-border bg-bg-panel">
          {tabBtn("watchlist", "Watchlist", "📊")}
          {tabBtn("chart", "Chart", "📈")}
          {tabBtn("portfolio", "Portfolio", "💼")}
          {tabBtn("chat", "AI Chat", "🤖")}
        </div>
      </div>
    </div>
  );
}
