import { useMemo, useState } from "react";
import type { SalesQuoteRecord } from "../../api/client";
import QuoteCopyButton from "../QuoteCopyButton";
export type SalesQuoteRecordFilter = "quoted" | "manual_required" | "superseded" | "all";

export default function SalesQuoteRecordsPanel({
  filter,
  isLoading,
  query,
  records,
  selectedRecordId,
  onFilterChange,
  onNewQuote,
  onQueryChange,
  onRefresh,
  onSelectRecord,
}: {
  filter: SalesQuoteRecordFilter;
  isLoading: boolean;
  query: string;
  records: SalesQuoteRecord[];
  selectedRecordId: number | null;
  onFilterChange: (value: SalesQuoteRecordFilter) => void;
  onNewQuote: () => void;
  onQueryChange: (value: string) => void;
  onRefresh: () => void;
  onSelectRecord: (id: number) => void;
}) {
  const visibleRecords = useMemo(
    () => filterSalesQuoteRecords(records, filter, query),
    [filter, query, records],
  );
  const selectedRecord =
    visibleRecords.find((record) => record.id === selectedRecordId) ?? visibleRecords[0] ?? null;
  const counts = countSalesQuoteRecords(records);

  return (
    <section className="panel p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase text-slate-500">销售记录</p>
          <h2 className="mt-1 text-xl font-semibold text-slate-950">报价记录</h2>
          <p className="mt-1 text-sm leading-6 text-slate-600">
            按当前账号回查已提交报价；人工复核状态以后端处理结果为准。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn-primary" type="button" onClick={onNewQuote}>
            新建报价
          </button>
          <button className="btn-secondary" type="button" onClick={onRefresh} disabled={isLoading}>
            {isLoading ? "刷新中" : "刷新记录"}
          </button>
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(220px,0.8fr)_minmax(0,1.2fr)]">
        <div className="grid gap-3">
          <div className="grid gap-3 rounded-md border border-slate-200 bg-slate-50 p-3">
            <label>
              <span className="text-xs font-semibold text-slate-500">搜索记录</span>
              <input
                className="field-input mt-2"
                value={query}
                onChange={(event) => onQueryChange(event.target.value)}
                placeholder="quote_id / 邮编 / 城市 / 原始询价"
              />
            </label>
            <div className="flex flex-wrap gap-2" role="tablist" aria-label="报价记录筛选">
              {(["all", "quoted", "manual_required", "superseded"] as SalesQuoteRecordFilter[]).map((item) => (
                <button
                  key={item}
                  className={filter === item ? "btn-primary" : "btn-secondary"}
                  type="button"
                  onClick={() => onFilterChange(item)}
                >
                  {salesRecordFilterLabel(item, counts)}
                </button>
              ))}
            </div>
          </div>

          <div className="max-h-[640px] overflow-auto rounded-md border border-slate-200">
            {visibleRecords.length ? (
              visibleRecords.map((record) => {
                const isSelected = selectedRecord?.id === record.id;
                return (
                  <button
                    key={record.id}
                    className={`grid w-full gap-2 border-b border-slate-100 px-3 py-3 text-left transition hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-teal-700 ${
                      isSelected ? "bg-slate-100" : "bg-white"
                    }`}
                    type="button"
                    onClick={() => onSelectRecord(record.id)}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <span className="min-w-0 break-all text-sm font-semibold text-slate-900">
                        {record.quote_id}
                      </span>
                      <SalesRecordStatusBadge status={record.status} />
                    </div>
                    <p className="line-clamp-2 text-sm leading-5 text-slate-600">
                      {record.destination}
                    </p>
                    <div className="grid grid-cols-2 gap-2 text-xs text-slate-400">
                      <span>{formatRecordDate(record.created_at)}</span>
                      <span className="text-right font-semibold text-slate-800">
                        {formatRecordMoney(record)}
                      </span>
                    </div>
                  </button>
                );
              })
            ) : (
              <div className="grid min-h-52 place-items-center p-5 text-center">
                <div>
                  <h3 className="text-base font-semibold text-slate-900">暂无报价记录</h3>
                  <p className="mt-2 text-sm leading-6 text-slate-400">
                    完成一次报价后，系统会自动把结果保存到这里。
                  </p>
                  <button className="btn-primary mt-4" type="button" onClick={onNewQuote}>
                    去报价
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>

        <SalesQuoteRecordDetail record={selectedRecord} />
      </div>
    </section>
  );
}

function SalesQuoteRecordDetail({ record }: { record: SalesQuoteRecord | null }) {
  const [acknowledgedId, setAcknowledgedId] = useState<number | null>(null);
  if (!record) {
    return (
      <div className="rounded-md border border-slate-200 bg-white p-5 text-sm text-slate-500">
        选择左侧记录后查看报价详情。
      </div>
    );
  }

  const rural = record.risk_tags.includes("rural_fsa_secondary_confirmation") || (record.postal_code || "")[1] === "0";
  const canCopyReply = record.status === "quoted" && Boolean(record.customer_reply?.trim()) && (!rural || acknowledgedId === record.id);
  const manualOverride = getManualOverride(record);

  return (
    <article className="rounded-md border border-slate-200 bg-white p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase text-slate-400">Quote ID</p>
          <h3 className="mt-1 break-all text-lg font-semibold text-slate-900">{record.quote_id}</h3>
          <p className="mt-1 text-sm text-slate-500">{formatRecordDate(record.created_at)}</p>
        </div>
        <SalesRecordStatusBadge status={record.status} />
      </div>

      {record.status === "manual_required" && (
        <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm font-semibold leading-6 text-amber-700">
          已提交人工复核。{record.manual_reason ? `原因：${record.manual_reason}` : "请等待后台确认后再回复客户金额。"}
        </div>
      )}

      {manualOverride && (
        <div className="mt-4 rounded-md border border-teal-200 bg-teal-50 px-3 py-2 text-sm leading-6 text-teal-800">
          后台已人工确认价格：USD {manualOverride.total_price_usd}
          {manualOverride.actor_name ? `，处理人：${manualOverride.actor_name}` : ""}。
          该金额只覆盖本条报价记录，不修改 Zone 价格矩阵。
        </div>
      )}

      <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        <RecordMetric label="报价金额" value={formatRecordMoney(record)} strong />
        <RecordMetric label="目的地" value={record.destination} wide />
        <RecordMetric label="货物" value={record.cargo_summary} />
        <RecordMetric label="Zone" value={record.zone === null ? "待匹配" : `Zone ${record.zone}`} />
        <RecordMetric label="计费托数" value={record.billing_pallets ? `${record.billing_pallets} 托` : "待计算"} />
        <RecordMetric label="规则依据" value={record.source_type === "learned_manual_quote" ? "人工审核" : `匹配评分 ${record.confidence}/100`} />
        <RecordMetric label="来源" value={formatRecordSourceType(record.source_type)} />
      </div>

      {(record.risk_tags.length > 0 || record.missing_fields.length > 0) && (
        <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-3">
          <h4 className="text-sm font-semibold text-amber-700">风险与缺失字段</h4>
          <div className="mt-3 flex flex-wrap gap-2">
            {[...record.missing_fields, ...record.risk_tags].map((tag) => (
              <span
                key={tag}
                className="rounded-md border border-amber-300/50 bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-800"
              >
                {tag}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="mt-4 grid gap-3 xl:grid-cols-2">
        <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
          <h4 className="text-sm font-semibold text-slate-700">客户原始询价</h4>
          <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-sm leading-6 text-slate-700">
            {record.customer_message}
          </pre>
        </div>
        <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
          <h4 className="text-sm font-semibold text-slate-700">客户回复</h4>
          <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-sm leading-6 text-slate-700">
            {record.customer_reply || "人工复核单不生成可直接发送的报价话术。"}
          </pre>
          <div className="mt-3">
            <>{rural && <label className="qw-rural mb-3"><input type="checkbox" checked={acknowledgedId === record.id} onChange={(e) => setAcknowledgedId(e.target.checked ? record.id : null)} />已核对乡村地址、城市、卡车准入和附加费。</label>}<QuoteCopyButton text={record.customer_reply ?? ""} disabled={!canCopyReply} /></>
          </div>
        </div>
      </div>
    </article>
  );
}

function RecordMetric({
  label,
  value,
  strong = false,
  wide = false,
}: {
  label: string;
  value: string;
  strong?: boolean;
  wide?: boolean;
}) {
  return (
    <div className={`rounded-md border border-slate-200 bg-white p-2.5 ${wide ? "sm:col-span-2" : ""}`}>
      <dt className="text-xs font-medium text-slate-500">{label}</dt>
      <dd className={`mt-1 break-words text-sm font-semibold tabular-nums ${strong ? "text-slate-900" : "text-slate-800"}`}>
        {value}
      </dd>
    </div>
  );
}

function SalesRecordStatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`shrink-0 rounded-md border px-2 py-1 text-xs font-semibold ${
        status === "quoted"
          ? "border-emerald-200 bg-emerald-50 text-emerald-700"
          : "border-amber-200 bg-amber-50 text-amber-700"
      }`}
    >
      {status === "quoted" ? "已报价" : status === "superseded" ? "已被替代" : "人工复核"}
    </span>
  );
}

function filterSalesQuoteRecords(
  records: SalesQuoteRecord[],
  filter: SalesQuoteRecordFilter,
  query: string,
): SalesQuoteRecord[] {
  const normalizedQuery = query.trim().toLowerCase();
  return records.filter((record) => {
    if (filter !== "all" && record.status !== filter) {
      return false;
    }
    if (!normalizedQuery) {
      return true;
    }
    return [
      record.quote_id,
      record.destination,
      record.cargo_summary,
      record.customer_message,
      record.postal_code,
      record.city,
      record.province,
    ]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(normalizedQuery));
  });
}

function countSalesQuoteRecords(records: SalesQuoteRecord[]): Record<SalesQuoteRecordFilter, number> {
  return {
    all: records.length,
    quoted: records.filter((record) => record.status === "quoted").length,
    superseded: records.filter((record) => record.status === "superseded").length,
    manual_required: records.filter((record) => record.status === "manual_required").length,
  };
}

function salesRecordFilterLabel(
  filter: SalesQuoteRecordFilter,
  counts: Record<SalesQuoteRecordFilter, number>,
): string {
  const labels: Record<SalesQuoteRecordFilter, string> = {
    all: "全部",
    quoted: "已报价",
    manual_required: "人工复核",
    superseded: "已被替代",
  };
  return `${labels[filter]} ${counts[filter]}`;
}

function formatRecordMoney(record: SalesQuoteRecord): string {
  if (record.status === "manual_required") {
    return "待人工确认";
  }
  const value = record.total_price_usd;
  if (value === null || value === undefined || value === "") {
    return "待匹配";
  }
  const numberValue = Number(value);
  return Number.isFinite(numberValue)
    ? `${record.currency_code} ${numberValue.toFixed(2)}`
    : `${record.currency_code} ${value}`;
}

function formatRecordDate(value: string | null): string {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value || "-";
  }
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatRecordSourceType(sourceType: string): string {
  if (sourceType === "zone_matrix") {
    return "Zone 价格矩阵";
  }
  if (sourceType === "manual_override") {
    return "后台人工确认价";
  }
  if (sourceType === "learned_manual_quote") {
    return "人工确认学习库";
  }
  if (sourceType === "llm_auxiliary_advice") {
    return "LLM 辅助建议";
  }
  if (sourceType === "hermes_agent_correction") {
    return "历史 LLM 辅助建议";
  }
  if (sourceType === "manual_required") {
    return "需要人工复核";
  }
  return sourceType || "待匹配";
}

function getManualOverride(record: SalesQuoteRecord): {
  total_price_usd?: string;
  actor_name?: string;
} | null {
  const resultJson = record.result_json;
  if (!resultJson || typeof resultJson !== "object" || Array.isArray(resultJson)) {
    return null;
  }
  const override = (resultJson as Record<string, unknown>).manual_override;
  if (!override || typeof override !== "object" || Array.isArray(override)) {
    return null;
  }
  const data = override as Record<string, unknown>;
  return {
    total_price_usd: data.total_price_usd === undefined ? undefined : String(data.total_price_usd),
    actor_name: data.actor_name === undefined ? undefined : String(data.actor_name),
  };
}

