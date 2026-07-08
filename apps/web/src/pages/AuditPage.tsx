import { FormEvent, useState } from "react";
import { getQuoteAudit, type QuoteAuditLog } from "../api/client";
import RiskTags from "../components/RiskTags";

interface AuditPageProps {
  embedded?: boolean;
}

export default function AuditPage({ embedded = false }: AuditPageProps = {}) {
  const [quoteId, setQuoteId] = useState("");
  const [record, setRecord] = useState<QuoteAuditLog | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = quoteId.trim();
    if (!trimmed) {
      setError("请输入 quote_id");
      return;
    }

    setIsLoading(true);
    setError(null);
    setRecord(null);

    try {
      const response = await getQuoteAudit(trimmed);
      setRecord(response);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "审计记录查询失败");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className={embedded ? "flex flex-col gap-5" : "mx-auto flex max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8"}>
      {!embedded && (
      <header>
        <p className="text-sm font-medium text-blue-800">Audit</p>
        <h1 className="mt-1 text-2xl font-semibold text-slate-950">
          报价审计查询
        </h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          用 quote_id 追溯一次报价为什么成功或为什么进入人工池，包括邮编、城市、Zone、托数和后端返回的完整 JSON。
        </p>
      </header>
      )}

      <section className="panel p-5">
        <form className="flex flex-col gap-3 md:flex-row md:items-end" onSubmit={handleSubmit}>
          <label className="flex-1">
            <span className="field-label">报价 ID</span>
            <input
              className="field-input"
              value={quoteId}
              onChange={(event) => setQuoteId(event.target.value)}
              placeholder="输入报价 ID"
            />
          </label>
          <button className="btn-primary" type="submit" disabled={isLoading}>
            {isLoading ? "查询中..." : "查询审计记录"}
          </button>
        </form>
        {error && (
          <div
            className="mt-4 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900"
            role="alert"
          >
            {error}
          </div>
        )}
      </section>

      {record ? (
        <section className="panel overflow-hidden">
          <div className="border-b border-slate-200 px-5 py-4">
            <p className="text-sm font-medium text-slate-600">Quote ID</p>
            <h2 className="mt-1 break-words font-mono text-lg font-semibold text-slate-950">
              {record.quote_id}
            </h2>
          </div>

          <div className="grid gap-6 p-5 xl:grid-cols-[0.85fr_1.15fr]">
            <div className="space-y-5">
              <div>
                <h3 className="section-title">审计字段</h3>
                <dl className="mt-3 grid gap-3 sm:grid-cols-2">
                  <FieldValue label="报价来源" value={sourceTypeLabel(record.source_type)} />
                  <FieldValue
                    label="是否人工复核"
                    value={record.manual_review_required ? "是" : "否"}
                  />
                  <FieldValue
                    label="邮编"
                    value={formatNullable(record.postal_code)}
                  />
                  <FieldValue
                    label="邮编前缀"
                    value={formatNullable(record.postal_prefix)}
                  />
                  <FieldValue label="城市" value={formatNullable(record.city)} />
                  <FieldValue label="省份" value={formatNullable(record.province)} />
                  <FieldValue label="始发仓" value={formatNullable(record.origin)} />
                  <FieldValue label="Zone" value={formatNullable(record.zone)} />
                  <FieldValue
                    label="计费托数"
                    value={formatNullable(record.billing_pallets)}
                  />
                  <FieldValue
                    label="基础派送费"
                    value={formatMoney(record.base_price_usd)}
                  />
                  <FieldValue
                    label="报价合计"
                    value={formatMoney(record.total_price_usd)}
                  />
                  <FieldValue label="创建时间" value={formatDate(record.created_at)} />
                </dl>
              </div>

              <div>
                <h3 className="section-title">风险标签</h3>
                <div className="mt-3">
                  <RiskTags tags={record.risk_tag_labels?.length ? record.risk_tag_labels : record.risk_tags} />
                </div>
              </div>
            </div>

            <div className="grid gap-5">
              <JsonBlock title="请求原文 JSON" value={record.request_json} />
              <JsonBlock title="报价结果 JSON" value={record.result_json} />
            </div>
          </div>
        </section>
      ) : (
        <section className="panel p-6 text-sm text-slate-600">
          输入报价 ID 后可查看原始请求、后端结果和落库的关键报价字段。
        </section>
      )}
    </div>
  );
}

function FieldValue({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="metric-label">{label}</dt>
      <dd className="metric-value break-words font-mono tabular-nums">{value}</dd>
    </div>
  );
}

function JsonBlock({ title, value }: { title: string; value: unknown }) {
  return (
    <div>
      <h3 className="section-title">{title}</h3>
      <pre className="mt-3 max-h-[28rem] overflow-auto rounded-md bg-slate-950 p-4 text-xs leading-5 text-slate-100">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

function formatNullable(value: string | number | null): string {
  if (value === null || value === undefined || value === "") {
    return "未返回";
  }
  return String(value);
}

function formatMoney(value: string | number | null): string {
  if (value === null || value === "") {
    return "未返回";
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `$${parsed.toFixed(2)}` : `$${String(value)}`;
}

function sourceTypeLabel(value: string): string {
  const labels: Record<string, string> = {
    zone_matrix: "Zone 价格矩阵",
    manual_required: "需要人工报价",
    learned_manual_quote: "人工学习规则",
    hermes_agent_correction: "Hermes Agent 纠错",
    fsa: "FSA 规则",
    postal_code: "邮编精确规则",
    city: "城市规则",
    rate_card: "供应商报价卡",
  };
  return labels[value] ? `${labels[value]}（${value}）` : value;
}

function formatDate(value: string | null): string {
  if (!value) {
    return "未返回";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
