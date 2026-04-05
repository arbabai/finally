import { render, screen } from "@testing-library/react";
import StatusDot from "@/components/StatusDot";

describe("StatusDot", () => {
  it("renders connected state", () => {
    render(<StatusDot status="connected" />);
    expect(screen.getByText("Connected")).toBeInTheDocument();
  });

  it("renders reconnecting state", () => {
    render(<StatusDot status="reconnecting" />);
    expect(screen.getByText("Reconnecting...")).toBeInTheDocument();
  });

  it("renders disconnected state", () => {
    render(<StatusDot status="disconnected" />);
    expect(screen.getByText("Disconnected")).toBeInTheDocument();
  });
});
