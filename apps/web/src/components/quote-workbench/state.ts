import type { CorrectionReasons, CorrectionReason, AIExtractResponse, ConfirmedCalculateResponse, FieldProvenance, QuoteField, ZoneQuoteRequest } from "../../api/client";

export type Phase = "empty" | "extracting" | "needs_input" | "ready" | "quoting" | "quoted" | "review" | "stale" | "error";
export type Draft = Record<Exclude<QuoteField, "requires_liftgate" | "requires_pallet_jack" | "requires_appointment">, string> & {
  requires_liftgate: boolean | null; requires_pallet_jack: boolean | null; requires_appointment: boolean | null;
};
export const emptyDraft: Draft = {
  address_line: "", postal_code: "", city: "", province: "", cbm: "", weight_kg: "", piece_count: "",
  packaging_type: "", longest_side_cm: "", explicit_pallet_count: "", is_stackable: "", address_type: "",
  requires_liftgate: null, requires_pallet_jack: null, requires_appointment: null, detention_minutes: "0",
};
export const labels: Record<QuoteField, string> = {
  address_line: "街道地址", postal_code: "邮编", city: "城市", province: "省份", cbm: "总体积 (CBM)", weight_kg: "总毛重 (kg)",
  piece_count: "件数", packaging_type: "包装类型", longest_side_cm: "最长边 (cm)", explicit_pallet_count: "客户明确托数",
  is_stackable: "可堆叠", address_type: "地址类型", requires_liftgate: "尾板", requires_pallet_jack: "手叉车",
  requires_appointment: "预约", detention_minutes: "等待时间 (分钟)",
};
export const sourceLabels = { customer_original: "客户原文", ai_extracted: "AI 提取", deterministic_extracted: "规则解析", human_edited: "人工修改" };
export const serviceFields: QuoteField[] = ["requires_liftgate", "requires_pallet_jack", "requires_appointment"];
const numbers: QuoteField[] = ["cbm", "weight_kg", "piece_count", "longest_side_cm", "explicit_pallet_count", "detention_minutes"];
const integers: QuoteField[] = ["piece_count", "explicit_pallet_count", "detention_minutes"];
const provinceInitials: Record<string, string> = { A: "NL", B: "NS", C: "PE", E: "NB", G: "QC", H: "QC", J: "QC", K: "ON", L: "ON", M: "ON", N: "ON", P: "ON", R: "MB", S: "SK", T: "AB", V: "BC", Y: "YT" };

export function validateDraft(draft: Draft): Partial<Record<QuoteField, string>> {
  const errors: Partial<Record<QuoteField, string>> = {};
  for (const key of serviceFields) if (draft[key] === null) errors[key] = "请确认是否需要";
  for (const key of ["address_line", "postal_code", "city", "province", "cbm", "weight_kg", "piece_count", "packaging_type", "address_type", "detention_minutes"] as QuoteField[]) {
    if (String(draft[key]).trim() === "") errors[key] = "请补充";
  }
  for (const key of numbers) {
    const text = String(draft[key]).trim();
    if (!text) continue;
    const value = Number(text);
    if (!Number.isFinite(value) || value < 0 || (integers.includes(key) && !Number.isInteger(value)) ||
      (["piece_count", "explicit_pallet_count"].includes(key) && value < 1)) errors[key] = "请输入有效数字";
  }
  const postal = draft.postal_code.replace(/[ -]/g, "").toUpperCase();
  if (postal && !/^[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTVWXYZ]\d[ABCEGHJ-NPRSTVWXYZ]\d$/.test(postal)) errors.postal_code = "邮编格式不正确";
  const province = draft.province.trim().toUpperCase();
  const expectedProvince = postal[0] === "X"
    ? ["X0A", "X0B", "X0C"].includes(postal.slice(0, 3)) ? "NU" : ["X0E", "X0G", "X1A"].includes(postal.slice(0, 3)) ? "NT" : null
    : provinceInitials[postal[0]];
  if (province && expectedProvince && province !== expectedProvince) errors.province = "省份与邮编不一致";
  if (["woven_bag", "flexible_packaging"].includes(draft.packaging_type) && !draft.is_stackable) errors.is_stackable = "请确认是否可堆叠";
  return errors;
}

export function toQuote(draft: Draft): ZoneQuoteRequest {
  const result = Object.fromEntries(Object.entries(draft).map(([key, value]) => {
    if (numbers.includes(key as QuoteField)) return [key, value === "" ? null : Number(value)];
    if (key === "is_stackable") return [key, value === "" ? null : value === "true"];
    return [key, typeof value === "string" ? value.trim() || null : value];
  })) as unknown as ZoneQuoteRequest;
  return result;
}

export function normalizeQuoteSnapshot(draft: Draft): string {
  const quote = toQuote(draft);
  quote.postal_code = (quote.postal_code || "").replace(/[ -]/g, "").toUpperCase();
  quote.city = quote.city?.replace(/\s+/g, " ").toUpperCase() || null;
  quote.province = quote.province?.toUpperCase() || null;
  quote.packaging_type = quote.packaging_type?.toLowerCase() as ZoneQuoteRequest["packaging_type"];
  return JSON.stringify(Object.fromEntries(Object.entries(quote).sort(([a], [b]) => a.localeCompare(b))));
}

export interface WorkbenchState {
  raw: string; phase: Phase; draft: Draft | null; provenance: FieldProvenance; correctionReasons: CorrectionReasons;
  extraction: AIExtractResponse | null; response: ConfirmedCalculateResponse | null;
  snapshot: string | null; error: string | null;
}
export const initialState: WorkbenchState = { raw: "", phase: "empty", draft: null, provenance: {}, correctionReasons: {}, extraction: null, response: null, snapshot: null, error: null };
export type Action =
  | { type: "raw"; value: string }
  | { type: "extract_start" } | { type: "cancel" }
  | { type: "extracted"; response: AIExtractResponse }
  | { type: "edit"; field: QuoteField; value: string | boolean | null }
  | { type: "reason"; field: QuoteField; value: CorrectionReason | "" }
  | { type: "quote_start" }
  | { type: "quoted"; response: ConfirmedCalculateResponse; snapshot: string }
  | { type: "error"; message: string };

export function workbenchReducer(state: WorkbenchState, action: Action): WorkbenchState {
  switch (action.type) {
    case "raw": return { ...initialState, raw: action.value };
    case "extract_start": return { ...state, phase: "extracting", error: null };
    case "cancel": return { ...initialState, raw: state.raw };
    case "extracted": {
      const draft = { ...emptyDraft };
      for (const key of Object.keys(draft) as QuoteField[]) {
        const value = action.response.extraction[key];
        (draft as Record<string, string | boolean | null>)[key] = serviceFields.includes(key) ? value == null ? null : Boolean(value) : value == null ? "" : String(value);
      }
      return { ...state, draft, extraction: action.response, provenance: action.response.field_provenance,
        response: null, snapshot: null, error: null,
        phase: Object.keys(validateDraft(draft)).length || action.response.draft_validation_errors.length ? "needs_input" : "ready" };
    }
    case "edit": {
      if (!state.draft || ["extracting", "quoting"].includes(state.phase)) return state;
      const draft = { ...state.draft, [action.field]: action.value };
      const phase: Phase = state.snapshot
        ? normalizeQuoteSnapshot(draft) !== state.snapshot ? "stale" : state.response?.quote_result.manual_review_required ? "review" : "quoted"
        : Object.keys(validateDraft(draft)).length ? "needs_input" : "ready";
      return { ...state, draft, phase, error: null, provenance: { ...state.provenance, [action.field]: "human_edited" } };
    }
    case "reason": return { ...state, correctionReasons: { ...state.correctionReasons, [action.field]: action.value || undefined } };
    case "quote_start": return { ...state, phase: "quoting", error: null };
    case "quoted": return { ...state, response: action.response, snapshot: action.snapshot, error: null,
      phase: action.response.quote_result.manual_review_required ? "review" : "quoted" };
    case "error": return { ...state, phase: "error", error: action.message };
  }
}

export function canUseQuote(state: WorkbenchState, ruralConfirmed: boolean): boolean {
  const result = state.response?.quote_result;
  if (state.phase !== "quoted" || !result || result.manual_review_required || result.total_price_usd == null) return false;
  const rural = result.risk_tags.includes("rural_fsa_secondary_confirmation") || (result.postal_code || "")[1] === "0";
  return !rural || ruralConfirmed;
}
