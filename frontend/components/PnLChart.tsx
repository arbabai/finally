"use client";

import { useRef, useEffect } from "react";
import type { PortfolioSnapshot } from "@/types";

function formatCurrency(value: number): string {
  return "$" + value.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

interface PnLChartProps {
  history: PortfolioSnapshot[];
}

export default function PnLChart({ history }: PnLChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || history.length < 2) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = rect.height;
    const padding = { top: 10, right: 50, bottom: 20, left: 5 };

    ctx.clearRect(0, 0, w, h);

    const values = history.map((s) => s.total_value);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;

    const drawW = w - padding.left - padding.right;
    const drawH = h - padding.top - padding.bottom;

    const isUp = values[values.length - 1] >= values[0];
    const lineColor = isUp ? "#3fb950" : "#f85149";

    // Grid
    ctx.strokeStyle = "#30363d";
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= 3; i++) {
      const y = padding.top + (i / 3) * drawH;
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(w - padding.right, y);
      ctx.stroke();

      const val = max - (i / 3) * range;
      ctx.fillStyle = "#8b949e";
      ctx.font = "9px monospace";
      ctx.textAlign = "left";
      ctx.fillText(formatCurrency(val), w - padding.right + 3, y + 3);
    }

    // Gradient fill
    const gradient = ctx.createLinearGradient(0, padding.top, 0, h - padding.bottom);
    gradient.addColorStop(0, isUp ? "rgba(63,185,80,0.2)" : "rgba(248,81,73,0.2)");
    gradient.addColorStop(1, "rgba(0,0,0,0)");

    ctx.beginPath();
    for (let i = 0; i < values.length; i++) {
      const x = padding.left + (i / (values.length - 1)) * drawW;
      const y = padding.top + drawH - ((values[i] - min) / range) * drawH;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.lineTo(padding.left + drawW, h - padding.bottom);
    ctx.lineTo(padding.left, h - padding.bottom);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();

    // Line
    ctx.beginPath();
    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 1.5;
    ctx.lineJoin = "round";
    for (let i = 0; i < values.length; i++) {
      const x = padding.left + (i / (values.length - 1)) * drawW;
      const y = padding.top + drawH - ((values[i] - min) / range) * drawH;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }, [history]);

  return (
    <div className="relative w-full h-full" style={{ minHeight: 100 }}>
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full" />
      {history.length < 2 && (
        <div className="absolute inset-0 flex items-center justify-center text-text-secondary text-xs">
          Collecting portfolio data...
        </div>
      )}
    </div>
  );
}
