import { describe, expect, it } from "vitest";
import { extractApiError } from "@/shared/lib/apiError";

describe("extractApiError", () => {
  it("returns the fallback for an undefined error", () => {
    expect(extractApiError(undefined)).toEqual({ message: "Request failed." });
    expect(extractApiError(undefined, "custom fallback")).toEqual({ message: "custom fallback" });
  });

  it("extracts status + detail from a JSON HTTP error response", () => {
    const error = { status: 400, data: { detail: "Cannot deactivate yourself" } } as const;
    expect(extractApiError(error)).toEqual({ status: 400, message: "Cannot deactivate yourself" });
  });

  it("falls back to the fallback message when the HTTP error has no detail", () => {
    const error = { status: 500, data: undefined } as const;
    expect(extractApiError(error, "boom")).toEqual({ status: 500, message: "boom" });
  });

  it("extracts the error string from a network-level failure (FETCH_ERROR)", () => {
    const error = { status: "FETCH_ERROR", error: "Failed to fetch" } as const;
    expect(extractApiError(error)).toEqual({ message: "Failed to fetch" });
  });

  it("extracts the message from a SerializedError", () => {
    expect(extractApiError({ message: "boom" })).toEqual({ message: "boom" });
  });

  it("falls back for a SerializedError with no message", () => {
    expect(extractApiError({})).toEqual({ message: "unknown error" });
  });
});
