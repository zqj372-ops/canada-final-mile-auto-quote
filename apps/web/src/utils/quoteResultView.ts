import type { ZoneQuoteResult } from "../api/client";

/**
 * The browser-facing quote summary deliberately accepts only the public
 * result fields.  Internal calculation traces, vehicle candidates and fee
 * categories must stay in the audit response and are not valid fallbacks.
 */
export type PublicQuoteResult = Pick<ZoneQuoteResult, "billing_pallets" | "manual_review_required">;
export type PublicZoneMatch = Pick<ZoneQuoteResult, "origin" | "zone" | "manual_review_required">;

export function formatBillingPalletSummary(result: PublicQuoteResult | null): string {
  if (!result || result.manual_review_required) {
    return "需要人工确认";
  }
  if (result.billing_pallets === null || result.billing_pallets === undefined) {
    return "待计算";
  }
  return `计费托数：${result.billing_pallets}`;
}

export function formatManualReviewSummary(result: PublicQuoteResult | null): string {
  return result?.manual_review_required ? "需要人工确认" : "报价已完成";
}

export function formatZoneMatch(result: PublicZoneMatch | null): string {
  if (!result) {
    return "待匹配";
  }
  if (result.manual_review_required) {
    return "待人工确认";
  }
  if (!result.origin || result.zone === null || result.zone === undefined) {
    return "待匹配";
  }
  return `${formatOrigin(result.origin)} / Zone ${result.zone}`;
}

function formatOrigin(origin: string): string {
  return origin
    .trim()
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");
}
