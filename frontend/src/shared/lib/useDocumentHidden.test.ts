import { renderHook, act } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useDocumentHidden } from "@/shared/lib/useDocumentHidden";

function setHidden(value: boolean) {
  Object.defineProperty(document, "hidden", { configurable: true, value, writable: true });
}

describe("useDocumentHidden", () => {
  afterEach(() => {
    setHidden(false);
  });

  it("starts false in the default (visible) test environment", () => {
    const { result } = renderHook(() => useDocumentHidden());
    expect(result.current).toBe(false);
  });

  it("flips to true when the tab backgrounds, and back on return", () => {
    const { result } = renderHook(() => useDocumentHidden());

    act(() => {
      setHidden(true);
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(result.current).toBe(true);

    act(() => {
      setHidden(false);
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(result.current).toBe(false);
  });
});
