"use client";

import { useRef, useEffect } from "react";
import type { TickerState } from "@/types";

interface MainChartProps {
  tickerState: TickerState | null;
  ticker: string | null;
}

function formatPrice(price: number): string {
  return price.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export default function MainChart({ tickerState, ticker }: MainChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !tickerState || tickerState.priceHistory.length < 2) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = rect.height;
    const padding = { top: 20, right: 60, bottom: 30, left: 10 };

    ctx.clearRect(0, 0, w, h);

    const data = tickerState.priceHistory;
    const prices = data.map((d) => d.price);
    const min = Math.min(...prices);
    const max = Math.max(...prices);
    const range = max - min || 1;

    const drawW = w - padding.left - padding.right;
    const drawH = h - padding.top - padding.bottom;

    const isUp = prices[prices.length - 1] >= prices[0];
    const lineColor = isUp ? "#3fb950" : "#f85149";

    // Grid lines
    ctx.strokeStyle = "#30363d";
    ctx.lineWidth = 0.5;
    const gridLines = 5;
    for (let i = 0; i <= gridLines; i++) {
      const y = padding.top + (i / gridLines) * drawH;
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(w - padding.right, y);
      ctx.stroke();

      // Price labels
      const priceVal = max - (i / gridLines) * range;
      ctx.fillStyle = "#8b949e";
      ctx.font = "10px monospace";
      ctx.textAlign = "left";
      ctx.fillText(formatPrice(priceVal), w - padding.right + 5, y + 3);
    }

    // Time labels
    const timeLabels = 5;
    ctx.fillStyle = "#8b949e";
    ctx.font = "10px monospace";
    ctx.textAlign = "center";
    for (let i = 0; i <= timeLabels; i++) {
      const idx = Math.floor((i / timeLabels) * (data.length - 1));
      const x = padding.left + (idx / (data.length - 1)) * drawW;
      const date = new Date(data[idx].time);
      const label = `${date.getHours().toString().padStart(2, "0")}:${date.getMinutes().toString().padStart(2, "0")}:${date.getSeconds().toString().padStart(2, "0")}`;
      ctx.fillText(label, x, h - 5);
    }

    // Gradient fill
    const gradient = ctx.createLinearGradient(0, padding.top, 0, h - padding.bottom);
    gradient.addColorStop(0, isUp ? "rgba(63,185,80,0.15)" : "rgba(248,81,73,0.15)");
    gradient.addColorStop(1, "rgba(0,0,0,0)");

    ctx.beginPath();
    for (let i = 0; i < data.length; i++) {
      const x = padding.left + (i / (data.length - 1)) * drawW;
      const y =
        padding.top + drawH - ((data[i].price - min) / range) * drawH;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    // Close for fill
    const lastX = padding.left + drawW;
    ctx.lineTo(lastX, h - padding.bottom);
    ctx.lineTo(padding.left, h - padding.bottom);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();

    // Line
    ctx.beginPath();
    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 1.5;
    ctx.lineJoin = "round";
    for (let i = 0; i < data.length; i++) {
      const x = padding.left + (i / (data.length - 1)) * drawW;
      const y =
        padding.top + drawH - ((data[i].price - min) / range) * drawH;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Current price dot
    const lastPrice = prices[prices.length - 1];
    const dotX = padding.left + drawW;
    const dotY =
      padding.top + drawH - ((lastPrice - min) / range) * drawH;
    ctx.beginPath();
    ctx.arc(dotX, dotY, 3, 0, Math.PI * 2);
    ctx.fillStyle = lineColor;
    ctx.fill();
  }, [tickerState]);

  if (!ticker) {
    return (
      <div className="flex items-center justify-center h-full text-text-secondary text-sm">
        Select a ticker from the watchlist
      </div>
    );
  }

  const currentPrice = tickerState?.price;
  const sessionChange =
    tickerState && tickerState.firstPrice
      ? ((tickerState.price - tickerState.firstPrice) / tickerState.firstPrice) * 100
      : null;

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 px-3 py-2 border-b border-border">
        <span className="text-sm font-bold text-text-primary">{ticker}</span>
        {currentPrice !== undefined && (
          <span
            className={`text-sm font-mono ${
              tickerState?.direction === "up"
                ? "text-green"
                : tickerState?.direction === "down"
                ? "text-red"
                : "text-text-primary"
            }`}
          >
            {formatPrice(currentPrice)}
          </span>
        )}
        {sessionChange !== null && (
          <span
            className={`text-xs ${
              sessionChange >= 0 ? "text-green" : "text-red"
            }`}
          >
            {sessionChange >= 0 ? "+" : ""}
            {sessionChange.toFixed(2)}%
          </span>
        )}
      </div>
      <div className="flex-1 relative">
        <canvas
          ref={canvasRef}
          className="absolute inset-0 w-full h-full"
        />
        {(!tickerState || tickerState.priceHistory.length < 2) && (
          <div className="absolute inset-0 flex items-center justify-center text-text-secondary text-xs">
            Waiting for price data...
          </div>
        )}
      </div>
    </div>
  );
}
