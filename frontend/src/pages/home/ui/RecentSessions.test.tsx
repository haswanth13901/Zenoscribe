import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Recording } from "@/entities/recording/model/types";
import { RecentSessions } from "@/pages/home/ui/RecentSessions";

const now = new Date(2026, 5, 15);

function rec(id: string, overrides: Partial<Recording> = {}): Recording {
  return {
    id,
    username: "ada",
    user_id: "u1",
    started_at: now.toISOString(),
    duration: 65,
    turn_count: 3,
    preview: `preview ${id}`,
    source: "transcribe",
    ...overrides,
  };
}

describe("RecentSessions", () => {
  it("shows a loading message while loading", () => {
    render(
      <RecentSessions
        recordings={undefined}
        isLoading
        isError={false}
        onRetry={vi.fn()}
        now={now}
      />,
    );
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("shows a distinct error message with a working retry button", async () => {
    const onRetry = vi.fn();
    render(
      <RecentSessions
        recordings={undefined}
        isLoading={false}
        isError
        onRetry={onRetry}
        now={now}
      />,
    );
    expect(screen.getByText(/couldn't load/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("shows the empty-state message when there are no recordings", () => {
    render(
      <RecentSessions
        recordings={[]}
        isLoading={false}
        isError={false}
        onRetry={vi.fn()}
        now={now}
      />,
    );
    expect(screen.getByText(/no recordings yet/i)).toBeInTheDocument();
  });

  it("renders at most 4 rows even with more recordings", () => {
    const recordings = Array.from({ length: 7 }, (_, i) => rec(String(i)));
    render(
      <RecentSessions
        recordings={recordings}
        isLoading={false}
        isError={false}
        onRetry={vi.fn()}
        now={now}
      />,
    );
    expect(screen.getAllByText(/turns$/)).toHaveLength(4);
  });

  it("falls back to a placeholder preview when empty", () => {
    const recordings = [rec("1", { preview: "" })];
    render(
      <RecentSessions
        recordings={recordings}
        isLoading={false}
        isError={false}
        onRetry={vi.fn()}
        now={now}
      />,
    );
    expect(screen.getByText("(no speech detected)")).toBeInTheDocument();
  });
});
