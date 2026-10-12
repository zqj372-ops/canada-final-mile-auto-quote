import { afterEach, describe, expect, it, vi } from "vitest";
import { listAllZoneCityRules } from "./client";

afterEach(() => vi.unstubAllGlobals());

function mockPages(total: number, override?: (offset: number) => Record<string, unknown>) {
  const fetcher = vi.fn(async (input: string) => {
    const params = new URL(input, "http://fixture").searchParams;
    const offset = Number(params.get("offset"));
    const limit = Number(params.get("limit"));
    const page = {
      total, city_count: 1065, postal_prefix_count: 1320,
      records: Array.from({ length: Math.max(0, Math.min(limit, total - offset)) }, (_, index) => ({ id: offset + index + 1 })),
      ...override?.(offset),
    };
    return new Response(JSON.stringify(page), { headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

describe("complete city rule loading", () => {
  it("loads all 2011 rules, including cities and city rows after the 1000-row boundary", async () => {
    const fetcher = mockPages(2011);
    const result = await listAllZoneCityRules();
    expect(result.records).toHaveLength(2011);
    expect(result.records[1000].id).toBe(1001);
    expect(result.records[result.records.length - 1]?.id).toBe(2011);
    expect(result.postal_prefix_count).toBe(1320);
    expect(fetcher.mock.calls.map(([url]) => Number(new URL(url, "http://fixture").searchParams.get("offset")))).toEqual([0, 1000, 2000]);
  });

  it("reads a genuinely empty configuration without requesting extra pages", async () => {
    const fetcher = mockPages(0);
    expect((await listAllZoneCityRules()).records).toEqual([]);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("rejects changed totals instead of exposing a partial configuration for editing", async () => {
    mockPages(1001, (offset) => offset ? { total: 1002 } : {});
    await expect(listAllZoneCityRules()).rejects.toThrow("读取期间发生变化");
  });

  it("rejects truncated or overlapping pages", async () => {
    mockPages(1001, (offset) => offset ? { records: [] } : {});
    await expect(listAllZoneCityRules()).rejects.toThrow("未完整读取");
    mockPages(1001, (offset) => offset ? { records: [{ id: 1000 }] } : {});
    await expect(listAllZoneCityRules()).rejects.toThrow("未完整读取");
  });

  it("propagates a later page failure rather than returning the first page as complete", async () => {
    const fetcher = mockPages(1001);
    fetcher.mockImplementationOnce(async () => new Response(JSON.stringify({ total: 1001, records: Array.from({ length: 1000 }, (_, id) => ({ id })) }), { headers: { "Content-Type": "application/json" } }));
    fetcher.mockImplementationOnce(async () => new Response(JSON.stringify({ detail: "读取失败" }), { status: 503, headers: { "Content-Type": "application/json" } }));
    await expect(listAllZoneCityRules()).rejects.toThrow("读取失败");
  });
});
