import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Recording } from "@/entities/recording/model/types";
import { MonthlyStats } from "@/pages/home/ui/MonthlyStats";

const now = new Date(2026, 5, 15);

function rec(overrides: Partial<Recording>): Recording {
  return {
    id: "1",
    username: "ada",
    user_id: "u1",
    started_at: now.toISOString(),
    duration: 0,
    turn_count: 0,
    preview: "",
    source: "transcribe",
    ...overrides,
  };
}

describe("MonthlyStats", () => {
  it("shows a neutral placeholder on error instead of stale/blank numbers", () => {
    render(<MonthlyStats recordings={undefined} isError now={now} />);
    expect(screen.getAllByText("—")).toHaveLength(2);
  });

  it("shows zero-state for an empty list", () => {
    render(<MonthlyStats recordings={[]} isError={false} now={now} />);
    expect(screen.getByText("0h 0m")).toBeInTheDocument();
    expect(screen.getByText("0")).toBeInTheDocument();
  });

  it("computes hours/minutes and total session count", () => {
    const recordings = [rec({ duration: 3600 }), rec({ duration: 1800 })];
    render(<MonthlyStats recordings={recordings} isError={false} now={now} />);
    expect(screen.getByText("1h 30m")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });
});
