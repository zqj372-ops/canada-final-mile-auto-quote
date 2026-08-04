import { describe, expect, it } from "vitest";
import type { ZoneQuoteResult } from "../api/client";
import { formatBillingPalletSummary, formatManualReviewSummary } from "./quoteResultView";
import * as quoteResultView from "./quoteResultView";

const successfulResult: ZoneQuoteResult = {
  quote_id: "quote-success",
  origin: "toronto",
  zone: 2,
  billing_pallets: 3,
  total_price_usd: "625.00",
  manual_review_required: false,
  sales_note: "USD 625.00",
  public_flags: [],
};

const manualResult: ZoneQuoteResult = {
  ...successfulResult,
  quote_id: "quote-manual",
  billing_pallets: null,
  manual_review_required: true,
};

describe("quote result public summary", () => {
  it("formats a successful billing-pallet summary without internal fields", () => {
    const result = {
      ...successfulResult,
      pallet_breakdown: { volume_pallets: 2 },
      vehicles: [{ code: "26_non_cdl" }],
      accessorials: { heavy_surcharge: "75.00" },
      rule_version: 4,
      manual_reason: "not-public",
    } as ZoneQuoteResult;

    expect(formatBillingPalletSummary(result)).toBe("计费托数：3");
    expect(formatManualReviewSummary(result)).toBe("报价已完成");
  });

  it("hides candidate pallets when the result requires manual review", () => {
    expect(formatBillingPalletSummary(manualResult)).toBe("需要人工确认");
    expect(formatManualReviewSummary(manualResult)).toBe("需要人工确认");
  });

  it("does not turn a null result into an internal fallback", () => {
    expect(formatBillingPalletSummary(null)).toBe("需要人工确认");
  });

  it("formats only a confirmed origin and Zone for the result card", () => {
    const candidate = (quoteResultView as Record<string, unknown>).formatZoneMatch;
    expect(candidate).toBeTypeOf("function");

    const formatZoneMatch = candidate as (result: {
      origin: string | null;
      zone: number | null;
      manual_review_required: boolean;
    } | null) => string;

    expect(formatZoneMatch({ origin: "toronto", zone: 2, manual_review_required: false })).toBe(
      "Toronto / Zone 2",
    );
    expect(formatZoneMatch({ origin: "calgary", zone: 5, manual_review_required: true })).toBe(
      "Calgary / Zone 5",
    );
    expect(formatZoneMatch({ origin: null, zone: null, manual_review_required: true })).toBe("待人工确认");
    expect(formatZoneMatch(null)).toBe("待匹配");
  });
});
