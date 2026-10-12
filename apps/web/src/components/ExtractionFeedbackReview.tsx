import { useState } from "react";
import { reviewExtractionFeedback, type JsonValue, type QuoteAuditLog } from "../api/client";
import { labels } from "./quote-workbench/state";

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export default function ExtractionFeedbackReview({ audit }: { audit: QuoteAuditLog }) {
  const request = record(audit.request_json);
  const initial = record(request.extraction_feedback);
  const [feedback, setFeedback] = useState(initial);
  const [approved, setApproved] = useState<string[]>([]);
  const [group, setGroup] = useState(String(initial.evaluation_group || ""));
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!feedback.version) return null;
  const corrections = Array.isArray(feedback.corrections) ? feedback.corrections.map(record) : [];
  if (!corrections.length) return null;

  async function save(fields: string[]) {
    setBusy(true); setError(null);
    try {
      const result = await reviewExtractionFeedback(audit.quote_id, {
        expected_version: String(feedback.version), approved_fields: fields, note: note.trim(),
        evaluation_group: group.trim(), split: "test",
      });
      setFeedback(result); setApproved([]);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "纠错审核保存失败"); }
    finally { setBusy(false); }
  }

  return <section className="rounded-lg border border-slate-200 p-4">
    <h3 className="section-title">解析纠错审核</h3>
    <p className="mt-2 text-sm text-slate-600">核对原文后，将选中的解析错误加入回归测试。客户补充和业务调整会保留记录，不作为解析答案。</p>
    <p className="mt-2 text-sm">来源：{feedback.verified_source === true ? "服务端已验证" : "未验证，仅供参考"} · 状态：{({ pending_review: "待审核", approved: "已纳入回归集", excluded: "已排除" } as Record<string, string>)[String(feedback.status)] || String(feedback.status)}</p>
    <blockquote className="my-3 whitespace-pre-wrap rounded bg-slate-50 p-3 text-sm">{String(request.customer_message || "未保存原文")}</blockquote>
    <div className="overflow-auto"><table className="w-full text-left text-sm"><thead><tr><th>选择</th><th>字段</th><th>解析值</th><th>确认值</th><th>修改原因</th></tr></thead>
      <tbody>{corrections.map((item) => {
        const field = String(item.field);
        const eligible = feedback.verified_source === true && item.reason === "extraction_error";
        return <tr key={field}><td><input type="checkbox" aria-label={`批准 ${field}`} disabled={busy || !eligible} checked={approved.includes(field)}
          onChange={(event) => setApproved(event.target.checked ? [...approved, field] : approved.filter((value) => value !== field))} /></td>
          <td>{labels[field as keyof typeof labels] || field}</td><td>{JSON.stringify(item.before as JsonValue) ?? "未知"}</td><td>{JSON.stringify(item.after as JsonValue)}</td>
          <td>{({ extraction_error: "解析错误", customer_update: "客户补充或变更", business_decision: "业务调整", unclassified: "未分类" } as Record<string, string>)[String(item.reason)]}</td></tr>;
      })}</tbody></table></div>
    <label className="mt-3 block"><span className="field-label">客户 / 模板分组（同类询价使用同一分组）</span><input className="field-input" value={group} onChange={(event) => setGroup(event.target.value)} maxLength={200} disabled={busy} /></label>
    <label className="mt-3 block"><span className="field-label">核对说明</span><textarea className="field-input" value={note} onChange={(event) => setNote(event.target.value)} maxLength={1000} disabled={busy} /></label>
    {error && <p role="alert" className="mt-2 text-red-700">{error}</p>}
    <div className="mt-3 flex gap-2"><button className="btn-primary" disabled={busy || !approved.length || !group.trim() || !note.trim()} onClick={() => void save(approved)}>纳入回归集</button>
      <button className="btn-secondary" disabled={busy || !group.trim() || !note.trim()} onClick={() => void save([])}>排除此记录</button></div>
  </section>;
}
