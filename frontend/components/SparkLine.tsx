"use client";

import { useRef, useEffect } from "react";

interface SparkLineProps {
  data: { time: number; price: number }[];
  width?: number;
  height?: number;
  color?: string;
}

export default function SparkLine({
  data,
  width = 80,
  height = 24,
  color,
}: SparkLineProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || data.length < 2) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    ctx.scale(dpr, dpr);

    ctx.clearRect(0, 0, width, height);

    const prices = data.map((d) => d.price);
    const min = Math.min(...prices);
    const max = Math.max(...prices);
    const range = max - min || 1;

    // Determine color based on first vs last price
    const lineColor =
      color ??
      (prices[prices.length - 1] >= prices[0] ? "#3fb950" : "#f85149");

    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 1.2;
    ctx.lineJoin = "round";
    ctx.beginPath();

    const padding = 2;
    const drawWidth = width - padding * 2;
    const drawHeight = height - padding * 2;

    for (let i = 0; i < prices.length; i++) {
      const x = padding + (i / (prices.length - 1)) * drawWidth;
      const y = padding + drawHeight - ((prices[i] - min) / range) * drawHeight;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }, [data, width, height, color]);

  return (
    <canvas
      ref={canvasRef}
      style={{ width, height }}
      className="block"
    />
  );
}
