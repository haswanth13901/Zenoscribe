import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TurnList } from "@/pages/recorder/ui/TurnList";

describe("TurnList", () => {
  it("shows the empty state when there are no turns and no partial", () => {
    render(<TurnList turns={[]} partial={null} />);
    expect(screen.getByText("Press Start and speak.")).toBeInTheDocument();
  });

  it("renders final turns with speaker label, text, and timestamp", () => {
    render(
      <TurnList turns={[{ speaker: "user-1", text: "hello there", start: 1.5 }]} partial={null} />,
    );
    expect(screen.getByText("Speaker 1")).toBeInTheDocument();
    expect(screen.getByText("S1")).toBeInTheDocument();
    expect(screen.getByText("hello there")).toBeInTheDocument();
    expect(screen.getByText("1.5s")).toBeInTheDocument();
  });

  it("does not render a timestamp when start is null", () => {
    render(<TurnList turns={[{ speaker: "user-1", text: "hi", start: null }]} partial={null} />);
    expect(screen.queryByText(/s$/)).not.toBeInTheDocument();
  });

  it("renders a trailing partial turn distinctly from final turns", () => {
    render(
      <TurnList
        turns={[{ speaker: "user-1", text: "final one", start: 0 }]}
        partial={{ speaker: "user-2", text: "still talking" }}
      />,
    );
    expect(screen.getByText("final one")).toBeInTheDocument();
    expect(screen.getByText("still talking")).toBeInTheDocument();
    expect(screen.getByText("Speaker 2")).toBeInTheDocument();
  });
});
