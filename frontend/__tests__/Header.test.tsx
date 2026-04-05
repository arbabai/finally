import { render, screen } from "@testing-library/react";
import Header from "@/components/Header";

describe("Header", () => {
  it("renders portfolio value and cash balance", () => {
    render(
      <Header
        totalValue={15000}
        cashBalance={5000}
        connectionStatus="connected"
      />
    );
    expect(screen.getByText("FinAlly")).toBeInTheDocument();
    expect(screen.getByText("$15,000.00")).toBeInTheDocument();
    expect(screen.getByText("$5,000.00")).toBeInTheDocument();
    expect(screen.getByText("Connected")).toBeInTheDocument();
  });

  it("renders placeholder when no data", () => {
    render(
      <Header
        totalValue={null}
        cashBalance={null}
        connectionStatus="disconnected"
      />
    );
    const dashes = screen.getAllByText("---");
    expect(dashes.length).toBe(2);
    expect(screen.getByText("Disconnected")).toBeInTheDocument();
  });
});
