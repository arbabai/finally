"use client";

import type { Position } from "@/types";

function formatCurrency(value: number): string {
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  });
}

interface PositionsTableProps {
  positions: Position[];
}

export default function PositionsTable({ positions }: PositionsTableProps) {
  if (positions.length === 0) {
    return (
      <div className="px-3 py-4 text-center text-text-secondary text-xs">
        No positions yet. Execute a trade to get started.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto w-full">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-text-secondary border-b border-border">
            <th className="text-left px-3 py-1.5 font-medium">Ticker</th>
            <th className="text-right px-3 py-1.5 font-medium">Qty</th>
            <th className="text-right px-3 py-1.5 font-medium">Avg Cost</th>
            <th className="text-right px-3 py-1.5 font-medium">Price</th>
            <th className="text-right px-3 py-1.5 font-medium">P&L</th>
            <th className="text-right px-3 py-1.5 font-medium">%</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((pos) => (
            <tr
              key={pos.ticker}
              className="border-b border-border/30 hover:bg-bg-primary/50"
            >
              <td className="px-3 py-1.5 font-semibold text-text-primary">
                {pos.ticker}
              </td>
              <td className="text-right px-3 py-1.5 text-text-primary">
                {pos.quantity}
              </td>
              <td className="text-right px-3 py-1.5 text-text-secondary">
                {formatCurrency(pos.avg_cost)}
              </td>
              <td className="text-right px-3 py-1.5 text-text-primary">
                {formatCurrency(pos.current_price)}
              </td>
              <td
                className={`text-right px-3 py-1.5 ${
                  pos.unrealized_pnl >= 0 ? "text-green" : "text-red"
                }`}
              >
                {pos.unrealized_pnl >= 0 ? "+" : ""}
                {formatCurrency(pos.unrealized_pnl)}
              </td>
              <td
                className={`text-right px-3 py-1.5 ${
                  pos.pct_change >= 0 ? "text-green" : "text-red"
                }`}
              >
                {pos.pct_change >= 0 ? "+" : ""}
                {pos.pct_change.toFixed(2)}%
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
