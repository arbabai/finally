"use client";

import type { ConnectionStatus } from "@/types";

const statusColors: Record<ConnectionStatus, string> = {
  connected: "bg-green",
  reconnecting: "bg-accent-yellow",
  disconnected: "bg-red",
};

const statusLabels: Record<ConnectionStatus, string> = {
  connected: "Connected",
  reconnecting: "Reconnecting...",
  disconnected: "Disconnected",
};

export default function StatusDot({ status }: { status: ConnectionStatus }) {
  return (
    <div className="flex items-center gap-1.5" title={statusLabels[status]}>
      <span
        className={`inline-block w-2 h-2 rounded-full ${statusColors[status]}`}
      />
      <span className="text-xs text-text-secondary">{statusLabels[status]}</span>
    </div>
  );
}
