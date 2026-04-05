import { render, screen } from "@testing-library/react";
import PositionsTable from "@/components/PositionsTable";
import type { Position } from "@/types";

describe("PositionsTable", () => {
  it("shows empty state when no positions", () => {
    render(<PositionsTable positions={[]} />);
    expect(screen.getByText(/no positions yet/i)).toBeInTheDocument();
  });

  it("renders positions correctly", () => {
    const positions: Position[] = [
      {
        ticker: "AAPL",
        quantity: 10,
        avg_cost: 150,
        current_price: 160,
        unrealized_pnl: 100,
        pnl_percent: 6.67,
      },
      {
        ticker: "GOOGL",
        quantity: 5,
        avg_cost: 180,
        current_price: 170,
        unrealized_pnl: -50,
        pnl_percent: -5.56,
      },
    ];
    render(<PositionsTable positions={positions} />);
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("GOOGL")).toBeInTheDocument();
    expect(screen.getByText("+6.67%")).toBeInTheDocument();
    expect(screen.getByText("-5.56%")).toBeInTheDocument();
  });
});
