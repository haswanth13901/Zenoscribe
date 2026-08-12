import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { server } from "../mocks/server";
import { downloadAuthenticated, triggerBlobDownload } from "./download";

describe("triggerBlobDownload", () => {
  let createObjectURL: ReturnType<typeof vi.fn>;
  let revokeObjectURL: ReturnType<typeof vi.fn>;
  let clickSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    // Assign directly rather than vi.stubGlobal("URL", ...) - replacing the
    // whole URL global would also clobber the constructor itself, breaking
    // `new URL(...)` calls that fetch/MSW rely on elsewhere in these tests.
    createObjectURL = vi.fn(() => "blob:mock-url");
    revokeObjectURL = vi.fn();
    URL.createObjectURL = createObjectURL as unknown as typeof URL.createObjectURL;
    URL.revokeObjectURL = revokeObjectURL as unknown as typeof URL.revokeObjectURL;
    clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  });

  afterEach(() => {
    clickSpy.mockRestore();
  });

  it("creates an object URL, clicks a synthetic download link, then revokes it", () => {
    triggerBlobDownload(new Blob(["hello"], { type: "text/plain" }), "hello.txt");
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock-url");
  });
});

describe("downloadAuthenticated", () => {
  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => "blob:mock-url") as unknown as typeof URL.createObjectURL;
    URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL;
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  });

  it("throws on a non-OK response", async () => {
    // MSW's path-only pattern matches regardless of origin; the call site
    // still needs an absolute URL, same requirement as baseApi.ts (Node's
    // fetch has no implicit base for a relative string) - computed from
    // window.location.origin rather than hardcoded, matching how the app
    // itself builds this URL.
    server.use(http.get("/api/recordings/x/audio", () => new HttpResponse(null, { status: 404 })));
    const url = `${window.location.origin}/api/recordings/x/audio`;
    await expect(downloadAuthenticated(url, "tok", "x.wav")).rejects.toThrow("Download failed");
  });

  it("sends the Authorization header and triggers a download on success", async () => {
    let sawAuthHeader: string | null = null;
    server.use(
      http.get("/api/recordings/x/audio", ({ request }) => {
        sawAuthHeader = request.headers.get("Authorization");
        return HttpResponse.arrayBuffer(new ArrayBuffer(4), { headers: { "Content-Type": "audio/wav" } });
      }),
    );
    const url = `${window.location.origin}/api/recordings/x/audio`;
    await downloadAuthenticated(url, "tok", "x.wav");
    expect(sawAuthHeader).toBe("Bearer tok");
  });
});
