"use client";

import { useMemo } from "react";
import type { Position } from "@/types";

interface PortfolioHeatmapProps {
  positions: Position[];
}

function getColor(pnlPercent: number): string {
  if (pnlPercent > 5) return "#238636";
  if (pnlPercent > 2) return "#2ea043";
  if (pnlPercent > 0) return "#3fb950";
  if (pnlPercent > -2) return "#f85149";
  if (pnlPercent > -5) return "#da3633";
  return "#b62324";
}

interface TreemapCell {
  ticker: string;
  weight: number;
  pnlPercent: number;
  value: number;
}

function layoutTreemap(
  cells: TreemapCell[],
  width: number,
  height: number
): { cell: TreemapCell; x: number; y: number; w: number; h: number }[] {
  // Simple slice-and-dice treemap
  const total = cells.reduce((sum, c) => sum + c.weight, 0);
  if (total === 0) return [];

  const result: { cell: TreemapCell; x: number; y: number; w: number; h: number }[] = [];
  let x = 0;
  let y = 0;
  let remainingW = width;
  let remainingH = height;
  const horizontal = width >= height;

  for (let i = 0; i < cells.length; i++) {
    const fraction = cells[i].weight / total;
    const remaining = cells.slice(i).reduce((s, c) => s + c.weight, 0) / total;

    if (horizontal) {
      const w = (fraction / remaining) * remainingW;
      result.push({ cell: cells[i], x, y, w, h: remainingH });
      x += w;
      remainingW -= w;
    } else {
      const h = (fraction / remaining) * remainingH;
      result.push({ cell: cells[i], x, y, w: remainingW, h });
      y += h;
      remainingH -= h;
    }
  }

  return result;
}

export default function PortfolioHeatmap({ positions }: PortfolioHeatmapProps) {
  const cells = useMemo(() => {
    return positions
      .map((pos) => ({
        ticker: pos.ticker,
        weight: pos.quantity * pos.current_price,
        pnlPercent: pos.pct_change,
        value: pos.quantity * pos.current_price,
      }))
      .sort((a, b) => b.weight - a.weight);
  }, [positions]);

  if (cells.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-text-secondary text-xs">
        No positions to display
      </div>
    );
  }

  const layout = layoutTreemap(cells, 100, 100);

  return (
    <div className="relative w-full h-full" style={{ minHeight: 120 }}>
      <svg viewBox="0 0 100 100" className="w-full h-full" preserveAspectRatio="none">
        {layout.map(({ cell, x, y, w, h }) => (
          <g key={cell.ticker}>
            <rect
              x={x}
              y={y}
              width={Math.max(w - 0.5, 0)}
              height={Math.max(h - 0.5, 0)}
              fill={getColor(cell.pnlPercent)}
              rx={1}
            />
            {w > 12 && h > 8 && (
              <>
                <text
                  x={x + w / 2}
                  y={y + h / 2 - 2}
                  textAnchor="middle"
                  dominantBaseline="middle"
                  fill="white"
                  fontSize={Math.min(w / 5, h / 3, 5)}
                  fontWeight="bold"
                  fontFamily="monospace"
                >
                  {cell.ticker}
                </text>
                <text
                  x={x + w / 2}
                  y={y + h / 2 + 4}
                  textAnchor="middle"
                  dominantBaseline="middle"
                  fill="rgba(255,255,255,0.8)"
                  fontSize={Math.min(w / 6, h / 4, 3.5)}
                  fontFamily="monospace"
                >
                  {cell.pnlPercent >= 0 ? "+" : ""}
                  {cell.pnlPercent.toFixed(1)}%
                </text>
              </>
            )}
          </g>
        ))}
      </svg>
    </div>
  );
}
