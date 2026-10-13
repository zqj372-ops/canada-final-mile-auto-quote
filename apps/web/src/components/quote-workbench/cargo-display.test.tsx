import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { AIExtractedQuoteDraft, QuoteWorkbenchConfig, ZoneQuoteResult } from "../../api/client";
import ParsedCargoTable from "../ParsedCargoTable";
import QuoteResult from "./QuoteResult";
import { emptyDraft, initialState } from "./state";

const extraction = {
  piece_count: 2, weight_kg: "800.0", cbm: "3.600",
  cargo_items: [{ quantity: 2, length_cm: "120.0", width_cm: "100.0", height_cm: "150.0", weight_kg: "400.00",
    cbm: "1.800000", total_weight_kg: "800.0", total_cbm: "3.600", source_span: "2托盘，120x100x150 cm，总重800kg" }],
} as AIExtractedQuoteDraft;

const renderCargo = (data = extraction, draft: typeof emptyDraft | null = null) => renderToStaticMarkup(<ParsedCargoTable extraction={data} draft={draft} />);

describe("cargo calculation display", () => {
  it("shows extracted totals, normalized dimensions and each item's returned calculation", () => {
    const html = renderCargo();
    expect(html).toContain("件毛体解析");
    expect(html).toContain("2 件");
    expect(html).toContain("800 kg");
    expect(html).toContain("3.600 CBM");
    expect(html).toContain("120 × 100 × 150 cm");
    expect(html).toContain("单件体积：120 × 100 × 150 ÷ 1,000,000 ≈ 1.8 CBM");
    expect(html).toContain("毛重计算：400 kg/件 × 2 件 ≈ 800 kg");
    expect(html).toContain("体积计算：1.8 CBM/件 × 2 件 ≈ 3.600 CBM");
  });

  it("preserves backend totals when per-piece averages are rounded", () => {
    const data = { ...extraction, piece_count: 3, weight_kg: "1000", cargo_items: [{ ...extraction.cargo_items[0], quantity: 3,
      weight_kg: "333.33", total_weight_kg: "1000", total_cbm: "5.400" }] };
    const html = renderCargo(data);
    expect(html).toContain("333.33 kg/件 × 3 件 ≈ 1,000 kg");
    expect(html).not.toContain("999.99 kg");
    expect(html).not.toContain("不一致");
  });

  it("keeps missing totals unknown and displays a real zero without inventing calculations", () => {
    const html = renderCargo({ ...extraction, weight_kg: null, cbm: "0", cargo_items: [] });
    expect(html).toContain("未提供");
    expect(html).toContain("0.000 CBM");
    expect(html).toContain("未返回可拆分的货物明细");
    expect(html).not.toContain("0 kg");
  });

  it("flags inconsistent per-piece and aggregate results instead of showing a false equality", () => {
    const html = renderCargo({ ...extraction, cargo_items: [{ ...extraction.cargo_items[0], total_weight_kg: "1000" }] });
    expect(html).toContain("与合计 1,000 kg 不一致，请核对");
    expect(html).not.toContain("≈ 1,000 kg");
  });

  it("labels edited summaries while retaining original parsed evidence", () => {
    const draft = { ...emptyDraft, piece_count: "2", weight_kg: "900", cbm: "3.6000" };
    const html = renderCargo(extraction, draft);
    expect(html).toContain("汇总已人工修改");
    expect(html).toContain("800 kg");
    expect(html).not.toContain("900 kg");
    expect(renderCargo(extraction, { ...draft, weight_kg: "800.00" })).not.toContain("汇总已人工修改");
  });

  it("flags dimensions that disagree with the declared volume", () => {
    const html = renderCargo({ ...extraction, cargo_items: [{ ...extraction.cargo_items[0], cbm: "2.0", total_cbm: "4.0" }] });
    expect(html).toContain("与单件体积 2 CBM 不一致，请核对");
    expect(html).not.toContain("≈ 1.8 CBM");
  });

  it("shows the quoted cargo snapshot and returned pallet breakdown after an edit", () => {
    const result = { quote_id: "fixture", source_type: "zone_matrix", manual_review_required: false,
      total_price_usd: "212", base_price_usd: "120", fuel_usd: "42", accessorials: { liftgate_fee_usd: "50" }, risk_tags: [],
      origin: "toronto", zone: 2, billing_pallets: 2, pallet_breakdown: { volume_pallets: 2, weight_pallets: 2, explicit_pallet_count: 2 },
      match_trace: { quote_logic: { price_formula: "基础价 USD 120.00 + 燃油 USD 42.00 + liftgate_fee_usd USD 50.00 = 合计 USD 212.00" } }, sales_note: "fixture",
    } as unknown as ZoneQuoteResult;
    const state = { ...initialState, phase: "stale" as const, draft: { ...emptyDraft, weight_kg: "1000" },
      snapshot: JSON.stringify({ piece_count: 2, weight_kg: 800, cbm: 3.6 }),
      response: { quote_result: result, sales_record_id: 1, manual_task_id: null, superseded_quote_id: null, superseded_task_id: null, diagnostic_queued: true } };
    const html = renderToStaticMarkup(<QuoteResult state={state} config={{ accessorial_labels: { liftgate_fee_usd: "尾板费" } } as unknown as QuoteWorkbenchConfig} ruralConfirmed={false} onConfirmRural={() => {}} />);
    expect(html).toContain("上次报价采用的件毛体，待重新计算");
    expect(html).toContain("800 kg");
    expect(html).not.toContain("1,000 kg");
    expect(html).toContain("体积折托");
    expect(html).toContain("重量折托");
    expect(html).toContain("最终计费托数");
    expect(html).toContain("212.00");
    expect(html).toContain("尾板费");
    expect(html).toContain("50.00");
    expect(html).not.toContain("基础派送费");
    expect(html).not.toContain("燃油");
    expect(html).not.toContain("120.00");
    expect(html).not.toContain("42.00");
    expect(html).not.toContain("price_formula");
  });
});
