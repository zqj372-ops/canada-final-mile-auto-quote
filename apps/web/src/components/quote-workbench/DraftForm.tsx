import type { CorrectionReasons, CorrectionReason, AIExtractResponse, FieldProvenance, QuoteField, QuoteWorkbenchConfig } from "../../api/client";
import { emptyDraft, labels, sourceLabels, validateDraft, serviceFields, type Draft } from "./state";

export default function DraftForm({ draft, config, sources, extraction, busy, onChange, onSubmit, hasResult, correctionReasons, onReasonChange }: {
  draft: Draft | null; config: QuoteWorkbenchConfig; sources: FieldProvenance;
  extraction: AIExtractResponse | null; busy: boolean; hasResult: boolean;
  correctionReasons: CorrectionReasons; onReasonChange: (field: QuoteField, value: CorrectionReason | "") => void;
  onChange: (field: QuoteField, value: string | boolean | null) => void; onSubmit: () => void;
}) {
  const values = draft ?? emptyDraft;
  const errors = draft ? validateDraft(draft) : {};
  const disabled = !draft || busy;
  const selectOptions: Partial<Record<QuoteField, Array<{ value: string; label: string }>>> = {
    province: config.provinces.map((p) => ({ value: p.code, label: `${p.code} · ${p.name}` })),
    packaging_type: config.packaging_options,
    address_type: config.address_type_options,
    is_stackable: [{ value: "true", label: "可以堆叠" }, { value: "false", label: "不可堆叠" }],
    ...Object.fromEntries(serviceFields.map((field) => [field, [{ value: "true", label: "需要" }, { value: "false", label: "不需要" }]])),
  };
  const numericFields = ["cbm", "weight_kg", "piece_count", "longest_side_cm", "explicit_pallet_count", "detention_minutes"];

  function field(key: QuoteField, wide = false) {
    const options = selectOptions[key];
    const props = { id: `quote-${key}`, "aria-invalid": Boolean(errors[key]),
      "aria-describedby": errors[key] ? `error-${key}` : undefined,
      disabled, value: values[key] == null ? "" : String(values[key]),
      onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => onChange(key, serviceFields.includes(key) ? event.target.value === "" ? null : event.target.value === "true" : event.target.value) };
    return <label key={key} className={`qw-field ${wide ? "qw-wide" : ""}`}>
      <span className="qw-field-label"><span>{labels[key]}</span>{sources[key] && <small>{sourceLabels[sources[key]!]}</small>}</span>
      {options ? <select {...props}><option value="">未确认</option>{options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select>
        : <input {...props} placeholder="—" type={numericFields.includes(key) ? "number" : "text"}
          min={numericFields.includes(key) ? 0 : undefined} step={numericFields.includes(key) ? "any" : undefined} />}
      {sources[key] === "human_edited" && <select aria-label={`${labels[key]}修改原因`} disabled={disabled}
        value={correctionReasons[key] || ""} onChange={(event) => onReasonChange(key, event.target.value as CorrectionReason | "")}>
        <option value="">修改原因（可选）</option><option value="extraction_error">解析错误</option>
        <option value="customer_update">客户补充或变更</option><option value="business_decision">业务调整或人工判断</option>
      </select>}
      {errors[key] && <small className="qw-field-error" id={`error-${key}`}>{errors[key]}</small>}
    </label>;
  }

  return <section className="qw-panel qw-confirm" aria-labelledby="confirm-heading">
    <header><h2 id="confirm-heading">核对信息</h2><p>请核对地址、货物和附加服务</p></header>
    <form onSubmit={(event) => { event.preventDefault(); if (draft && !busy && !Object.keys(errors).length) onSubmit(); }}>
      <fieldset disabled={disabled}>
        <legend>派送地址</legend>
        <div className="qw-fields">{field("postal_code")}{field("city")}{field("province")}{field("address_type")}{field("address_line", true)}</div>
      </fieldset>
      <fieldset disabled={disabled}>
        <legend>货物信息</legend>
        <div className="qw-fields">{field("piece_count")}{field("weight_kg")}{field("cbm")}{field("packaging_type")}</div>
      </fieldset>
      <details className="qw-details" open={Boolean(errors.is_stackable)}>
        <summary>补充计费条件</summary>
        <div className="qw-fields">{field("longest_side_cm")}{field("explicit_pallet_count")}{field("is_stackable")}{field("detention_minutes")}</div>
      </details>
      <fieldset disabled={disabled}>
        <legend>附加服务</legend>
        <div className="qw-fields">{serviceFields.map((key) => field(key))}</div>
      </fieldset>
      {extraction?.address_validation && <details className="qw-address-evidence"><summary>查看解析时的地址校验</summary>
        <p>{extraction.address_validation.note_zh}</p><p>编辑地址后，提交报价时会重新校验。</p>
        <a href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent([values.address_line, values.city, values.province, values.postal_code].join(", "))}`} target="_blank" rel="noreferrer">在 Google 地图核对地址</a>
      </details>}
      <button className="qw-primary qw-submit" type="submit" disabled={disabled || Object.keys(errors).length > 0}>
        {busy ? "处理中…" : hasResult ? "确认修改并重新报价" : "确认并计算报价"}
      </button>
    </form>
  </section>;
}
