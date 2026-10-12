import { describe, expect, it } from "vitest";
import type { AIExtractResponse, ConfirmedCalculateResponse } from "../../api/client";
import { canUseQuote, initialState, normalizeQuoteSnapshot, validateDraft, workbenchReducer } from "./state";

const extraction = {
  extraction: { address_line: "8888 Keele St", postal_code: "L4K 2N2", city: "Concord", province: "ON", cbm: "4.2", weight_kg: "850", piece_count: 10, packaging_type: "carton", address_type: "commercial", requires_liftgate: false, requires_pallet_jack: false, requires_appointment: false, detention_minutes: 0 },
  field_provenance: { cbm: "deterministic_extracted" }, draft_validation_errors: [], extraction_missing_fields: [],
} as unknown as AIExtractResponse;
const result = { quote_result: { quote_id: "q-1", postal_code: "L4K 2N2", total_price_usd: "162", manual_review_required: false, risk_tags: [] }, manual_task_id: null } as unknown as ConfirmedCalculateResponse;
const ready = () => workbenchReducer(initialState, { type: "extracted", response: extraction });
const quoted = () => { const s = ready(); return workbenchReducer(s, { type: "quoted", response: result, snapshot: normalizeQuoteSnapshot(s.draft!) }); };

describe("confirmed quote workflow", () => {
  it("keeps extraction separate from quoting and allows filling missing fields", () => {
    const parsing = workbenchReducer(initialState, { type: "extract_start" });
    expect(parsing.phase).toBe("extracting");
    const missing = workbenchReducer(parsing, { type: "extracted", response: { ...extraction, extraction: { ...extraction.extraction, weight_kg: null } } });
    expect(missing.phase).toBe("needs_input");
    const filled = workbenchReducer(missing, { type: "edit", field: "weight_kg", value: "850" });
    expect(filled.phase).toBe("ready"); expect(filled.response).toBeNull();
    expect(filled.provenance.weight_kg).toBe("human_edited");
  });
  it("locks copy and export after any pricing input changes", () => {
    const s = quoted(); expect(canUseQuote(s, false)).toBe(true);
    const changed = workbenchReducer(s, { type: "edit", field: "requires_liftgate", value: true });
    expect(changed.phase).toBe("stale"); expect(canUseQuote(changed, false)).toBe(false);
    expect(changed.response?.quote_result.total_price_usd).toBe("162");
    const restored = workbenchReducer(changed, { type: "edit", field: "requires_liftgate", value: false });
    expect(restored.phase).toBe("quoted");
  });
  it("does not invalidate a quote for equivalent postal/number formatting", () => {
    let s = quoted();
    s = workbenchReducer(s, { type: "edit", field: "postal_code", value: "l4k2n2" });
    s = workbenchReducer(s, { type: "edit", field: "cbm", value: "4.2000" });
    expect(s.phase).toBe("quoted");
  });
  it("clears the entire draft and quote when the original text changes", () => {
    const s = workbenchReducer(quoted(), { type: "raw", value: "new shipment" });
    expect(s.phase).toBe("empty"); expect(s.response).toBeNull(); expect(s.draft).toBeNull();
    expect(s.provenance).toEqual({}); expect(s.snapshot).toBeNull();
  });
  it("distinguishes system failure from manual review and disables old prices", () => {
    const failed = workbenchReducer(quoted(), { type: "error", message: "network failure" });
    expect(failed.phase).toBe("error"); expect(canUseQuote(failed, true)).toBe(false);
    const review = workbenchReducer(ready(), { type: "quoted", response: { ...result, manual_task_id: 1, quote_result: { ...result.quote_result, manual_review_required: true, total_price_usd: null } }, snapshot: "test" });
    expect(review.phase).toBe("review"); expect(canUseQuote(review, true)).toBe(false);
  });
  it("requires fresh rural confirmation and prevents edits while submitting", () => {
    const rural = quoted(); rural.response = { ...result, quote_result: { ...result.quote_result, postal_code: "T0B 3L0" } };
    expect(canUseQuote(rural, false)).toBe(false); expect(canUseQuote(rural, true)).toBe(true);
    const submitting = workbenchReducer(quoted(), { type: "quote_start" });
    expect(canUseQuote(submitting, true)).toBe(false);
    expect(workbenchReducer(submitting, { type: "edit", field: "weight_kg", value: "1000" })).toEqual(submitting);
  });
  it("validates province, flexible packaging, quantities and nonfinite numbers", () => {
    const draft = ready().draft!;
    expect(validateDraft({ ...draft, province: "BC" }).province).toBeTruthy();
    expect(validateDraft({ ...draft, packaging_type: "woven_bag" }).is_stackable).toBeTruthy();
    expect(validateDraft({ ...draft, piece_count: "0.5" }).piece_count).toBeTruthy();
    expect(validateDraft({ ...draft, detention_minutes: "" }).detention_minutes).toBeTruthy();
    expect(validateDraft({ ...draft, postal_code: "X0A 0H0", province: "NT" }).province).toBeTruthy();
    expect(validateDraft({ ...draft, weight_kg: "Infinity" }).weight_kg).toBeTruthy();
  });
});


describe("service confirmation and correction reasons", () => {
  it("preserves unknown service flags until a person explicitly confirms them", () => {
    let state = workbenchReducer(initialState, { type: "extracted", response: {
      ...extraction, extraction: { ...extraction.extraction, requires_liftgate: null },
    } });
    expect(state.draft!.requires_liftgate).toBeNull();
    expect(state.phase).toBe("needs_input");
    state = workbenchReducer(state, { type: "edit", field: "requires_liftgate", value: false });
    expect(state.phase).toBe("ready");
    state = workbenchReducer(state, { type: "reason", field: "requires_liftgate", value: "customer_update" });
    expect(state.correctionReasons.requires_liftgate).toBe("customer_update");
    expect(workbenchReducer(state, { type: "raw", value: "new" }).correctionReasons).toEqual({});
  });
});
