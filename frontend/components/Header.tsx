"use client";

import type { ConnectionStatus } from "@/types";
import StatusDot from "./StatusDot";

function formatCurrency(value: number): string {
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  });
}

interface HeaderProps {
  totalValue: number | null;
  cashBalance: number | null;
  connectionStatus: ConnectionStatus;
}

export default function Header({
  totalValue,
  cashBalance,
  connectionStatus,
}: HeaderProps) {
  return (
    <header className="flex items-center justify-between px-3 py-2 border-b border-border bg-bg-panel flex-shrink-0">
      {/* Brand */}
      <div className="flex items-center gap-2">
        <h1 className="text-base font-bold text-accent-yellow tracking-wide">
          FinAlly
        </h1>
        <span className="hidden sm:inline text-xs text-text-secondary">
          AI Trading Workstation
        </span>
      </div>

      {/* Stats */}
      <div className="flex items-center gap-3 sm:gap-6">
        <div className="text-right">
          <div className="text-[10px] sm:text-xs text-text-secondary">Portfolio</div>
          <div className="text-xs sm:text-sm font-semibold text-blue-primary">
            {totalValue !== null ? formatCurrency(totalValue) : "---"}
          </div>
        </div>
        <div className="text-right hidden sm:block">
          <div className="text-xs text-text-secondary">Cash</div>
          <div className="text-sm font-semibold text-green">
            {cashBalance !== null ? formatCurrency(cashBalance) : "---"}
          </div>
        </div>
        <StatusDot status={connectionStatus} />
      </div>
    </header>
  );
}
