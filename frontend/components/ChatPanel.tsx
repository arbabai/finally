"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import type {
  ChatMessage,
  ChatResponse,
  ExecutedTrade,
  ExecutedWatchlistChange,
} from "@/types";

interface ChatPanelProps {
  onTradeExecuted: () => void;
  onWatchlistChange: () => void;
}

function TradeConfirmation({ trade }: { trade: ExecutedTrade }) {
  const isSuccess = trade.status === "success";
  return (
    <div
      className={`text-xs px-2 py-1 rounded my-1 ${
        isSuccess
          ? "bg-green/10 text-green border border-green/20"
          : "bg-red/10 text-red border border-red/20"
      }`}
    >
      {isSuccess
        ? `${trade.side.toUpperCase()} ${trade.quantity} ${trade.ticker} @ $${trade.price.toFixed(2)}`
        : `Failed: ${trade.error}`}
    </div>
  );
}

function WatchlistChangeConfirmation({
  change,
}: {
  change: ExecutedWatchlistChange;
}) {
  const isSuccess = change.status === "success";
  return (
    <div
      className={`text-xs px-2 py-1 rounded my-1 ${
        isSuccess
          ? "bg-blue-primary/10 text-blue-primary border border-blue-primary/20"
          : "bg-red/10 text-red border border-red/20"
      }`}
    >
      {isSuccess
        ? `Watchlist: ${change.action} ${change.ticker}`
        : `Failed: ${change.error}`}
    </div>
  );
}

export default function ChatPanel({
  onTradeExecuted,
  onWatchlistChange,
}: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const sendMessage = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      const text = input.trim();
      if (!text || loading) return;

      const userMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "user",
        content: text,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMsg]);
      setInput("");
      setLoading(true);

      try {
        const res = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: text }),
        });

        if (res.ok) {
          const data: ChatResponse = await res.json();
          const assistantMsg: ChatMessage = {
            id: crypto.randomUUID(),
            role: "assistant",
            content: data.message,
            actions: {
              trades_executed: data.trades_executed,
              watchlist_changes_executed: data.watchlist_changes_executed,
            },
            created_at: new Date().toISOString(),
          };
          setMessages((prev) => [...prev, assistantMsg]);

          if (data.trades_executed?.length) {
            onTradeExecuted();
          }
          if (data.watchlist_changes_executed?.length) {
            onWatchlistChange();
          }
        } else {
          const err = await res.json().catch(() => ({ detail: "Unknown error" }));
          setMessages((prev) => [
            ...prev,
            {
              id: crypto.randomUUID(),
              role: "assistant",
              content: `Error: ${err.detail || "Something went wrong"}`,
              created_at: new Date().toISOString(),
            },
          ]);
        }
      } catch {
        setMessages((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            role: "assistant",
            content: "Error: Could not connect to the server.",
            created_at: new Date().toISOString(),
          },
        ]);
      } finally {
        setLoading(false);
      }
    },
    [input, loading, onTradeExecuted, onWatchlistChange]
  );

  if (collapsed) {
    return (
      <button
        onClick={() => setCollapsed(false)}
        className="bg-purple text-white text-xs px-3 py-2 rounded-l hover:opacity-80 fixed right-0 top-1/2 -translate-y-1/2 z-10"
        style={{ writingMode: "vertical-lr" }}
      >
        AI Chat
      </button>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-2 border-b border-border">
        <h2 className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
          AI Assistant
        </h2>
        <button
          onClick={() => setCollapsed(true)}
          className="text-text-secondary hover:text-text-primary text-xs"
          title="Collapse"
        >
          &raquo;
        </button>
      </div>
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-3 py-2 space-y-3"
      >
        {messages.length === 0 && (
          <div className="text-text-secondary text-xs text-center py-4">
            Ask me about your portfolio, request trades, or get market analysis.
          </div>
        )}
        {messages.map((msg) => (
          <div key={msg.id}>
            <div
              className={`text-xs ${
                msg.role === "user" ? "text-blue-primary" : "text-text-primary"
              }`}
            >
              <span className="font-semibold">
                {msg.role === "user" ? "You" : "FinAlly"}:
              </span>{" "}
              <span className="whitespace-pre-wrap">{msg.content}</span>
            </div>
            {msg.actions?.trades_executed?.map((trade, i) => (
              <TradeConfirmation key={i} trade={trade} />
            ))}
            {msg.actions?.watchlist_changes_executed?.map((change, i) => (
              <WatchlistChangeConfirmation key={i} change={change} />
            ))}
          </div>
        ))}
        {loading && (
          <div className="flex items-center gap-2 text-xs text-text-secondary">
            <span className="inline-block w-3 h-3 border-2 border-purple border-t-transparent rounded-full animate-spin" />
            Thinking...
          </div>
        )}
      </div>
      <form
        onSubmit={sendMessage}
        className="flex gap-1 p-2 border-t border-border"
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask FinAlly..."
          disabled={loading}
          className="flex-1 bg-bg-primary border border-border rounded px-2 py-1.5 text-xs text-text-primary placeholder:text-text-secondary focus:outline-none focus:border-purple disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="bg-purple text-white text-xs px-3 py-1.5 rounded hover:opacity-80 disabled:opacity-50"
        >
          Send
        </button>
      </form>
    </div>
  );
}
