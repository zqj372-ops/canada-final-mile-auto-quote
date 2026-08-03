import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, request } from "./http";

describe("scoped HTTP client", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("uses the sales API key for sales requests and the admin key for admin requests", async () => {
    localStorage.setItem("canada-final-mile-quote-api-key", "sales-key");
    localStorage.setItem("canada-final-mile-admin-api-key", "admin-key");
    const fetchMock = vi.fn().mockImplementation(() => new Response(JSON.stringify({ ok: true }), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await request("/sales", {}, "quote");
    await request("/admin", {}, "admin");

    expect(fetchMock.mock.calls[0][1].headers).toMatchObject({ "X-API-Key": "sales-key" });
    expect(fetchMock.mock.calls[1][1].headers).toMatchObject({ "X-API-Key": "admin-key" });
  });

  it("clears the scoped credential on 401 and preserves structured 409 conflict details", async () => {
    localStorage.setItem("canada-final-mile-quote-api-key", "sales-key");
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "登录已失效" }), { status: 401, headers: { "content-type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: { code: "revision_conflict", current_revision: 3 } }), { status: 409, headers: { "content-type": "application/json" } })));

    await expect(request("/expired", {}, "quote")).rejects.toMatchObject({ status: 401 });
    expect(localStorage.getItem("canada-final-mile-quote-api-key")).toBeNull();
    await expect(request("/conflict", {}, "quote")).rejects.toMatchObject({ status: 409, details: { code: "revision_conflict", current_revision: 3 } });
  });

  it("exposes a typed API error instead of swallowing request failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
    await expect(request("/offline", {}, "quote")).rejects.toThrow(ApiError);
  });
});
