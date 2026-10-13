import type { QuoteWorkbenchConfig, ZoneQuoteRequest } from "../../api/client";
import QuoteCopyButton from "../QuoteCopyButton";
import { CargoSummary } from "../ParsedCargoTable";
import { canUseQuote, type WorkbenchState } from "./state";

export function DocumentIcon() {
  return <svg className="qw-document-icon" viewBox="0 0 64 72" fill="none" aria-hidden="true"><path d="M12 3h27l14 15v48a3 3 0 0 1-3 3H12a3 3 0 0 1-3-3V6a3 3 0 0 1 3-3Z" stroke="currentColor" strokeWidth="3" strokeLinejoin="round" /><path d="M38 3v17h15M20 35h12M20 46h22" stroke="currentColor" strokeWidth="3" strokeLinecap="round" /></svg>;
}

export default function QuoteResult({ state, config, ruralConfirmed, onConfirmRural }: {
  state: WorkbenchState; config: QuoteWorkbenchConfig; ruralConfirmed: boolean; onConfirmRural: (checked: boolean) => void;
}) {
  const result = state.response?.quote_result;
  const quotedCargo: ZoneQuoteRequest | null = state.snapshot ? JSON.parse(state.snapshot) : null;
  const logicValue = result?.match_trace.quote_logic;
  const logic = logicValue && typeof logicValue === "object" && !Array.isArray(logicValue) ? logicValue : null;
  const matchingTrace = Object.fromEntries(Object.entries(result?.match_trace || {}).filter(([key]) => key !== "quote_logic"));
  const canUse = canUseQuote(state, ruralConfirmed);
  const rural = result && (result.risk_tags.includes("rural_fsa_secondary_confirmation") || (result.postal_code || "")[1] === "0");
  const currency = "USD"; // ZoneQuoteResult monetary fields are explicitly denominated in USD.
  const money = (value: unknown) => value == null ? "—" : new Intl.NumberFormat("en-CA", { style: "currency", currency }).format(Number(value));
  const busy = state.phase === "extracting" || state.phase === "quoting";
  const ready = ["needs_input", "ready"].includes(state.phase);
  function exportQuote() {
    if (!canUse || !result?.sales_note) return;
    const url = URL.createObjectURL(new Blob([result.sales_note], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url; link.download = `quote-${result.quote_id}.txt`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <section className="qw-panel qw-result" aria-labelledby="result-heading" aria-live="polite">
    <header><h2 id="result-heading">报价结果</h2></header>
    {state.phase === "error" ? <div className="qw-empty qw-error-state"><DocumentIcon /><h3>本次请求未完成</h3><p>{state.error}</p><p>请核对信息后重试。可在报价记录中核实上一次提交的结果。</p></div>
      : !result ? <div className="qw-empty"><DocumentIcon /><h3>{busy ? state.phase === "extracting" ? "正在解析字段" : "正在计算报价" : ready ? "等待确认信息" : "等待报价"}</h3>
        <p>{busy ? "请稍候，完成后将在这里更新。" : ready ? "补齐并核对中栏字段，确认后计算费用。" : "核对信息后，将在这里显示费用明细与匹配依据。"}</p></div>
      : <div className="qw-result-content">
        {state.phase === "stale" && <p className="qw-warning" role="status">字段已修改。以下为上一次结果，重新报价后才能复制或导出。</p>}
        {busy && <p className="qw-warning">正在重新计算，暂不可复制或导出。</p>}
        <div className="qw-total"><span>{result.manual_review_required ? "需要人工复核" : "报价合计"}</span>
          <strong>{result.manual_review_required ? "待人工确认" : money(result.total_price_usd)}</strong>
          {!result.manual_review_required && <small>{result.source_type === "learned_manual_quote" ? "USD · 人工审核整口价" : "USD"}</small>}
        </div>
        {result.manual_review_required ? <p className="qw-warning">{result.internal_note || result.matched_rule}<br />人工任务 #{state.response?.manual_task_id} 已保存。</p>
          : result.source_type === "learned_manual_quote" ? <p className="qw-note">仅适用于审核时确认的地址、货物、服务及有效期。</p>
          : Object.keys(result.accessorials).length > 0 && <dl className="qw-fees">
            {Object.entries(result.accessorials).map(([key, value]) => <div key={key}><dt>{config.accessorial_labels[key] || key}</dt><dd>{money(value)}</dd></div>)}
          </dl>}
        <dl className="qw-match"><div><dt>始发仓</dt><dd>{result.origin || "未匹配"}</dd></div><div><dt>分区</dt><dd>{result.zone == null ? "未匹配" : `Zone ${result.zone}`}</dd></div><div><dt>价格来源</dt><dd>{result.source_type === "zone_matrix" ? "Zone 价格矩阵" : result.source_type === "learned_manual_quote" ? "已审核人工价格" : "人工复核"}</dd></div></dl>
        <section className="qw-calculation" aria-labelledby="calculation-heading">
          <h3 id="calculation-heading">计费计算结果</h3>
          <p className="qw-note">{state.phase === "stale" ? "上次报价采用的件毛体，待重新计算。" : "本次报价采用的件毛体"}</p>
          {quotedCargo ? <CargoSummary cargo={quotedCargo} /> : typeof logic?.cargo === "string" ? <p>{logic.cargo}</p> : null}
          {Object.keys(result.pallet_breakdown).length > 0 ? <dl className="qw-pallet-calculation">
            {Object.entries(result.pallet_breakdown).map(([key, value]) => <div key={key}><dt>{palletLabels[key] || key}</dt><dd>{value} 托</dd></div>)}
          </dl> : <p className="qw-note">计费条件不足，暂未返回托数明细。</p>}
          <p className="qw-billing-total">最终计费托数 <strong>{result.billing_pallets == null ? "待确认" : `${result.billing_pallets} 托`}</strong></p>
        </section>
        {rural && <label className="qw-rural"><input type="checkbox" checked={ruralConfirmed} disabled={state.phase !== "quoted"} onChange={(e) => onConfirmRural(e.target.checked)} /><span>乡村地址二次确认：已核对完整地址、城市、卡车准入及可能的偏远附加费。</span></label>}
        {result.risk_tags.length > 0 && <details className="qw-details"><summary>风险提示（{result.risk_tags.length}）</summary><ul>{result.risk_tags.map((tag) => <li key={tag}>{config.backend_risk_tag_labels[tag] || tag}</li>)}</ul></details>}
        <div className="qw-result-actions"><QuoteCopyButton key={result.quote_id} text={result.sales_note || ""} disabled={!canUse || !result.sales_note} /><button className="qw-secondary" onClick={exportQuote} disabled={!canUse || !result.sales_note}>导出报价</button></div>
        <details className="qw-details"><summary>匹配依据与报价编号</summary><p>{result.quote_id}</p><p>{result.matched_rule}</p><pre>{JSON.stringify(matchingTrace, null, 2)}</pre></details>
        {state.response?.superseded_quote_id && <p className="qw-note">已替代原人工任务，历史记录保留。</p>}
        {state.response && !state.response.diagnostic_queued && <p className="qw-warning">报价已保存，诊断队列写入失败。</p>}
      </div>}
    <footer>价格由报价规则计算，缺少价格时转人工确认。</footer>
  </section>;
}

const palletLabels: Record<string, string> = {
  volume_pallets: "体积折托", weight_pallets: "重量折托", long_piece_pallets: "超长件折托",
  wooden_crate_pallets: "木箱折托", explicit_pallet_count: "客户明确托数", normal_basis_pallets: "基础托数",
};
