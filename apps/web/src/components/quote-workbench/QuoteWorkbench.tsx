import { useEffect, useReducer, useRef, useState } from "react";
import { calculateConfirmedQuote, extractQuote, type QuoteWorkbenchConfig } from "../../api/client";
import DraftForm from "./DraftForm";
import QuoteResult from "./QuoteResult";
import { initialState, normalizeQuoteSnapshot, toQuote, validateDraft, workbenchReducer } from "./state";
import "./workbench.css";

export default function QuoteWorkbench({ config, onSaved }: { config: QuoteWorkbenchConfig; onSaved: () => void }) {
  const [state, dispatch] = useReducer(workbenchReducer, initialState);
  const [ruralQuoteId, setRuralQuoteId] = useState<string | null>(null);
  const [forceAI, setForceAI] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const controller = useRef<AbortController | null>(null);
  const locked = useRef(false);
  const busy = state.phase === "extracting" || state.phase === "quoting";
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    if (!busy) return;
    const start = performance.now(); setElapsed(0);
    const timer = window.setInterval(() => setElapsed(Math.floor((performance.now() - start) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [busy]);

  function reset(value: string) {
    if (busy) return;
    if (state.draft && !window.confirm("修改原文会清空当前字段和报价结果，是否继续？")) return;
    dispatch({ type: "raw", value }); setRuralQuoteId(null);
  }
  async function parse() {
    if (locked.current || !state.raw.trim()) return;
    locked.current = true;
    const current = new AbortController(); controller.current = current;
    dispatch({ type: "extract_start" });
    try {
      const response = await extractQuote(state.raw, current.signal, forceAI);
      if (!current.signal.aborted) dispatch({ type: "extracted", response });
    } catch (error) {
      if (!current.signal.aborted) dispatch({ type: "error", message: error instanceof Error ? error.message : "解析失败，请重试。" });
    } finally { if (controller.current === current) locked.current = false; }
  }
  function cancel() {
    controller.current?.abort(); locked.current = false; dispatch({ type: "cancel" });
  }
  async function quote() {
    if (locked.current || !state.draft || Object.keys(validateDraft(state.draft)).length) return;
    locked.current = true; dispatch({ type: "quote_start" });
    try {
      const response = await calculateConfirmedQuote({
        customer_message: state.raw, quote: toQuote(state.draft), field_provenance: state.provenance,
        extraction_snapshot: state.extraction?.extraction || null,
        extraction_receipt: state.extraction?.extraction_receipt || null,
        correction_reasons: state.correctionReasons,
        supersedes_quote_id: state.response?.manual_task_id ? state.response.quote_result.quote_id : null,
      });
      dispatch({ type: "quoted", response, snapshot: normalizeQuoteSnapshot(state.draft) });
      setRuralQuoteId(null); onSaved();
    } catch (error) { dispatch({ type: "error", message: error instanceof Error ? error.message : "报价失败，请重试。" }); }
    finally { locked.current = false; }
  }
  async function importText(file: File | undefined) {
    if (!file) return;
    if (!/\.(txt|csv)$/i.test(file.name) || file.size > 100000) {
      dispatch({ type: "error", message: "请选择 100 KB 以内的 TXT 或 CSV 文本。价格表请通过后台导入。" }); return;
    }
    try { const text = await file.text(); if (text.length > 20000) throw new Error("询价文本最多 20,000 字符。"); reset(text); }
    catch (error) { dispatch({ type: "error", message: error instanceof Error ? error.message : "文件读取失败。" }); }
  }
  const step = state.response ? 2 : state.draft ? 1 : 0;
  return <div className="quote-workbench">
    <ol className="qw-steps" aria-label="报价流程">{["客户询价", "核对信息", "报价结果"].map((label, index) => <li key={label} className={index <= step ? "qw-step-active" : ""} aria-current={index === step ? "step" : undefined}><span>0{index + 1}</span>{label}</li>)}</ol>
    <div className="qw-columns">
      <section className="qw-panel qw-input" aria-labelledby="input-heading">
        <header><h2 id="input-heading">客户询价</h2><button className="qw-link" disabled={busy} onClick={() => reset(config.sample_input)}>填入示例</button></header>
        <label className="qw-raw-label"><span className="sr-only">客户原始询价</span><textarea value={state.raw} maxLength={20000} readOnly={Boolean(state.draft) || busy}
          onChange={(e) => dispatch({ type: "raw", value: e.target.value })}
          placeholder={"粘贴客户原始消息…\n\n货物尺寸、数量、重量\n派送地址、邮编及服务要求"} /></label>
        <p className="qw-note">支持中英文、cm / in、kg / lb</p>
        <div className="qw-input-actions">
          {state.draft ? <button className="qw-secondary" disabled={busy} onClick={() => reset(state.raw)}>修改原文</button>
            : <button className="qw-primary" disabled={busy || !state.raw.trim()} onClick={() => void parse()}>{state.phase === "extracting" ? "解析中…" : "解析字段"}</button>}
          {state.phase === "extracting" ? <button className="qw-secondary" onClick={cancel}>取消等待</button> : <button className="qw-secondary" disabled={busy || !state.raw} onClick={() => reset("")}>清空</button>}
          <label className={`qw-link qw-file ${busy ? "qw-disabled" : ""}`}>导入文本<input type="file" className="sr-only" accept=".txt,.csv" disabled={busy} onChange={(e) => { void importText(e.target.files?.[0]); e.target.value = ""; }} /></label>
        </div>
        {busy && <p className="qw-progress" role="status"><span className="qw-spinner" />{state.phase === "extracting" ? "正在解析" : "正在报价"} · 已等待 {elapsed} 秒</p>}
        {state.extraction && <div className="qw-extraction-status" role="status"><strong>{ { local: "规则解析完成", ai: "AI 解析完成", fallback: "模型未完成，已提取可识别字段" }[state.extraction.extraction_mode]}</strong><span>{(state.extraction.duration_ms / 1000).toFixed(2)} 秒</span>
          <p>{state.extraction.extraction_mode === "local" ? "本次无需调用模型，请核对右侧字段。" : "请核对识别结果，空缺字段可直接补充。"}</p>
          {state.extraction.extraction.validation_notes.some((n) => /mismatch|replaced/.test(n)) && <p className="qw-warning">原文汇总与尺寸计算存在差异，请重点核对体积、重量与件数。</p>}
        </div>}
        {!state.draft && <details className="qw-options"><summary>解析选项</summary><label><input type="checkbox" checked={forceAI} onChange={(e) => setForceAI(e.target.checked)} disabled={busy} /> 始终使用后台配置的模型</label></details>}
        <footer>解析后可修改字段，再确认报价。</footer>
      </section>
      <DraftForm correctionReasons={state.correctionReasons} onReasonChange={(field, value) => dispatch({ type: "reason", field, value })} draft={state.draft} config={config} sources={state.provenance} extraction={state.extraction} busy={busy}
        onChange={(field, value) => dispatch({ type: "edit", field, value })} onSubmit={() => void quote()} hasResult={Boolean(state.response)} />
      <QuoteResult state={state} config={config} ruralConfirmed={Boolean(state.response && ruralQuoteId === state.response.quote_result.quote_id)}
        onConfirmRural={(checked) => setRuralQuoteId(checked ? state.response?.quote_result.quote_id || null : null)} />
    </div>
  </div>;
}
