import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ChatPanel from "@/components/ChatPanel";

describe("ChatPanel", () => {
  beforeEach(() => {
    global.fetch = jest.fn();
    // Mock crypto.randomUUID
    Object.defineProperty(global, "crypto", {
      value: { randomUUID: () => "test-uuid-" + Math.random() },
      configurable: true,
    });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("shows empty state message", () => {
    render(
      <ChatPanel onTradeExecuted={jest.fn()} onWatchlistChange={jest.fn()} />
    );
    expect(
      screen.getByText(/ask me about your portfolio/i)
    ).toBeInTheDocument();
  });

  it("shows loading spinner during API call", async () => {
    const user = userEvent.setup();
    // Never-resolving fetch to keep loading state
    (global.fetch as jest.Mock).mockReturnValueOnce(new Promise(() => {}));

    render(
      <ChatPanel onTradeExecuted={jest.fn()} onWatchlistChange={jest.fn()} />
    );

    await user.type(screen.getByPlaceholderText("Ask FinAlly..."), "Hello");
    await user.click(screen.getByText("Send"));

    await waitFor(() => {
      expect(screen.getByText("Thinking...")).toBeInTheDocument();
    });
  });

  it("displays assistant response after send", async () => {
    const user = userEvent.setup();
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        message: "Your portfolio looks great!",
        trades_executed: [],
        watchlist_changes_executed: [],
      }),
    });

    render(
      <ChatPanel onTradeExecuted={jest.fn()} onWatchlistChange={jest.fn()} />
    );

    await user.type(screen.getByPlaceholderText("Ask FinAlly..."), "How is my portfolio?");
    await user.click(screen.getByText("Send"));

    await waitFor(() => {
      expect(
        screen.getByText("Your portfolio looks great!")
      ).toBeInTheDocument();
    });
  });
});
