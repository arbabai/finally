// SSE price update from /api/stream/prices
export interface PriceUpdate {
  ticker: string;
  price: number;
  prev_price: number;
  timestamp: number;
  direction: "up" | "down" | "flat";
}

// Ticker state tracked on the frontend
export interface TickerState {
  ticker: string;
  price: number;
  previousPrice: number;
  direction: "up" | "down" | "flat";
  firstPrice: number | null; // first price received this session (for % change)
  priceHistory: { time: number; price: number }[]; // for sparklines and main chart
  lastUpdate: number;
}

// Watchlist item from GET /api/watchlist
export interface WatchlistItem {
  ticker: string;
  added_at: string;
}

// Portfolio from GET /api/portfolio
export interface Portfolio {
  cash_balance: number;
  total_value: number;
  positions: Position[];
}

export interface Position {
  ticker: string;
  quantity: number;
  avg_cost: number;
  current_price: number;
  unrealized_pnl: number;
  pct_change: number;
}

// Trade request for POST /api/portfolio/trade
export interface TradeRequest {
  ticker: string;
  quantity: number;
  side: "buy" | "sell";
}

// Portfolio history from GET /api/portfolio/history
export interface PortfolioSnapshot {
  total_value: number;
  recorded_at: string;
}

// Chat types
export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  actions?: ChatActions | null;
  created_at: string;
}

export interface ChatActions {
  trades_executed?: ExecutedTrade[];
  watchlist_changes_executed?: ExecutedWatchlistChange[];
}

export interface ExecutedTrade {
  ticker: string;
  side: "buy" | "sell";
  quantity: number;
  price: number;
  status: "success" | "error";
  error?: string;
}

export interface ExecutedWatchlistChange {
  ticker: string;
  action: "add" | "remove";
  status: "success" | "error";
  error?: string;
}

// Chat response from POST /api/chat
export interface ChatResponse {
  message: string;
  trades_executed?: ExecutedTrade[];
  watchlist_changes_executed?: ExecutedWatchlistChange[];
}

export type ConnectionStatus = "connected" | "reconnecting" | "disconnected";
