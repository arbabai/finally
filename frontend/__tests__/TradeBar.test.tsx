import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import TradeBar from "@/components/TradeBar";

describe("TradeBar", () => {
  beforeEach(() => {
    global.fetch = jest.fn();
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("calls API with correct payload on BUY", async () => {
    const user = userEvent.setup();
    const onTradeExecuted = jest.fn();
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    });

    render(
      <TradeBar selectedTicker="AAPL" onTradeExecuted={onTradeExecuted} />
    );

    const qtyInput = screen.getByPlaceholderText("Qty");
    await user.type(qtyInput, "10");
    await user.click(screen.getByText("BUY"));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith("/api/portfolio/trade", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker: "AAPL", quantity: 10, side: "buy" }),
      });
    });

    await waitFor(() => {
      expect(onTradeExecuted).toHaveBeenCalled();
    });
  });

  it("shows error when trade fails", async () => {
    const user = userEvent.setup();
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: false,
      json: async () => ({ detail: "Insufficient cash" }),
    });

    render(<TradeBar selectedTicker="AAPL" onTradeExecuted={jest.fn()} />);

    await user.type(screen.getByPlaceholderText("Qty"), "999");
    await user.click(screen.getByText("BUY"));

    await waitFor(() => {
      expect(screen.getByText("Insufficient cash")).toBeInTheDocument();
    });
  });
});
