import { FormEvent, useEffect, useState } from "react";
import {
  getQuoteAudit,
  listQuoteAudits,
  updateSalesQuoteManualPriceByQuoteId,
  type JsonValue,
  type QuoteAuditLog,
} from "../api/client";
import RiskTags from "../components/RiskTags";

interface AuditPageProps {
  embedded?: boolean;
}

export default function AuditPage({ embedded = false }: AuditPageProps = {}) {
  const [quoteId, setQuoteId] = useState("");
  const [record, setRecord] = useState<QuoteAuditLog | null>(null);
  const [records, setRecords] = useState<QuoteAuditLog[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isListLoading, setIsListLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [overridePrice, setOverridePrice] = useState("");
  const [overrideNote, setOverrideNote] = useState("");
  const [overrideReply, setOverrideReply] = useState("");
  const [overrideError, setOverrideError] = useState<string | null>(null);
  const [overrideNotice, setOverrideNotice] = useState<string | null>(null);
  const [isSavingOverride, setIsSavingOverride] = useState(false);

  useEffect(() => {
    void loadRecentAudits();
  }, []);

  useEffect(() => {
    if (!record) {
      return;
    }
    setOverridePrice(record.total_price_usd === null ? "" : String(record.total_price_usd));
    setOverrideNote("");
    setOverrideReply("");
    setOverrideError(null);
    setOverrideNotice(null);
  }, [record?.id]);

  async function loadRecentAudits(search = "") {
    setIsListLoading(true);
    try {
      const response = await listQuoteAudits({ limit: 40, query: search });
      setRecords(response);
      if (!record && response.length > 0) {
        setRecord(response[0]);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "审计列表加载失败");
    } finally {
      setIsListLoading(false);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = quoteId.trim();
    if (!trimmed) {
      await loadRecentAudits();
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

  async function saveManualOverride() {
    if (!record) {
      return;
    }
    if (!overridePrice.trim()) {
      setOverrideError("请填写人工确认 USD 金额。");
      return;
    }
    const price = Number(overridePrice);
    if (!Number.isFinite(price) || price < 0) {
      setOverrideError("请输入大于等于 0 的 USD 金额。");
      return;
    }
    if (!overrideNote.trim()) {
      setOverrideError("请填写人工改价/确认原因。");
      return;
    }
    const confirmed = window.confirm(
      "请二次确认：这会按当前 quote_id 更新销售报价记录的客户可见金额；审计原始记录和 Zone 价格矩阵不会被修改。确认保存？",
    );
    if (!confirmed) {
      return;
    }
    setIsSavingOverride(true);
    setOverrideError(null);
    setOverrideNotice(null);
    try {
      const updated = await updateSalesQuoteManualPriceByQuoteId(record.quote_id, {
        total_price_usd: price,
        override_note: overrideNote.trim(),
        customer_reply: overrideReply.trim() || null,
        confirmed: true,
      });
      setOverrideNotice(`已更新销售报价记录 #${updated.id}，客户可见金额为 USD ${Number(updated.total_price_usd).toFixed(2)}。`);
    } catch (caught) {
      setOverrideError(caught instanceof Error ? caught.message : "人工确认价保存失败");
    } finally {
      setIsSavingOverride(false);
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
              placeholder="输入 8 位报价 ID，也可留空刷新最近列表"
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
              <QuoteLogicCard record={record} />

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
              <ReadableRequestCard record={record} />
              <ManualPriceOverrideCard
                error={overrideError}
                isSaving={isSavingOverride}
                note={overrideNote}
                notice={overrideNotice}
                onNoteChange={setOverrideNote}
                onPriceChange={setOverridePrice}
                onReplyChange={setOverrideReply}
                onSave={() => void saveManualOverride()}
                price={overridePrice}
                record={record}
                reply={overrideReply}
              />
              <details className="rounded-md border border-slate-200 bg-slate-50 p-4">
                <summary className="cursor-pointer text-sm font-semibold text-slate-900">
                  调试 JSON
                </summary>
                <div className="mt-4 grid gap-5">
                  <JsonBlock title="请求原文 JSON" value={record.request_json} />
                  <JsonBlock title="报价结果 JSON" value={record.result_json} />
                </div>
              </details>
            </div>
          </div>
        </section>
      ) : (
        <section className="panel p-6 text-sm text-slate-600">
          输入报价 ID 后可查看原始请求、后端结果和落库的关键报价字段。
        </section>
      )}

      <section className="panel overflow-hidden">
        <div className="flex flex-col gap-3 border-b border-slate-200 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h3 className="section-title">最近审计列表</h3>
            <p className="mt-1 text-sm text-slate-600">
              新报价会使用 8 位数字报价 ID；旧 UUID 记录仍可查询。
            </p>
          </div>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => loadRecentAudits(quoteId)}
            disabled={isListLoading}
          >
            {isListLoading ? "刷新中..." : "刷新列表"}
          </button>
        </div>
        <div className="divide-y divide-slate-200">
          {records.length === 0 ? (
            <div className="px-5 py-6 text-sm text-slate-500">暂无审计记录。</div>
          ) : (
            records.map((item) => (
              <button
                key={`${item.id}-${item.quote_id}`}
                type="button"
                className={`grid w-full gap-3 px-5 py-4 text-left transition hover:bg-slate-50 lg:grid-cols-[9rem_1fr_7rem_7rem_8rem] lg:items-center ${
                  record?.id === item.id ? "bg-teal-50/70" : "bg-white"
                }`}
                onClick={() => {
                  setRecord(item);
                  setQuoteId(item.quote_id);
                }}
              >
                <div>
                  <p className="font-mono text-sm font-semibold text-slate-950">{item.quote_id}</p>
                  <p className="mt-1 text-xs text-slate-500">{formatDate(item.created_at)}</p>
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-900">
                    {item.postal_prefix || "-"} / {item.city || "-"} / {item.province || "-"}
                  </p>
                  <p className="mt-1 line-clamp-1 text-xs text-slate-500">
                    {logicHeadline(item) || sourceTypeLabel(item.source_type)}
                  </p>
                </div>
                <StatusBadge manual={item.manual_review_required} />
                <div className="text-sm font-semibold text-slate-900">
                  {item.origin || "-"} {item.zone === null ? "" : `Z${item.zone}`}
                </div>
                <div className="text-sm font-semibold text-slate-950">{formatMoney(item.total_price_usd)}</div>
              </button>
            ))
          )}
        </div>
      </section>
    </div>
  );
}

function QuoteLogicCard({ record }: { record: QuoteAuditLog }) {
  const logic = asRecord(record.quote_logic);
  const steps = readStringList(logic.steps);
  return (
    <div className="rounded-md border border-teal-200 bg-teal-50/70 p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-teal-800">报价逻辑说明</p>
          <h3 className="mt-1 text-lg font-semibold text-slate-950">
            {readText(logic.headline) || logicHeadline(record) || "系统未返回报价逻辑"}
          </h3>
        </div>
        <StatusBadge manual={record.manual_review_required} />
      </div>
      <dl className="mt-4 grid gap-3 sm:grid-cols-3">
        <FieldValue label="价格来源" value={readText(logic.price_source) || sourceTypeLabel(record.source_type)} />
        <FieldValue label="线路/分区" value={readText(logic.route) || `${record.origin || "-"} / ${record.zone ?? "-"}`} />
        <FieldValue label="下一步" value={readText(logic.next_action) || "按审计结果处理"} />
      </dl>
      {steps.length > 0 && (
        <ol className="mt-4 space-y-2 text-sm leading-6 text-slate-700">
          {steps.map((step, index) => (
            <li key={`${index}-${step}`} className="flex gap-2">
              <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-teal-600 text-xs font-semibold text-white">
                {index + 1}
              </span>
              <span>{step}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function ReadableRequestCard({ record }: { record: QuoteAuditLog }) {
  const request = asRecord(record.request_json);
  const result = asRecord(record.result_json);
  return (
    <div className="rounded-md border border-slate-200 bg-white p-4">
      <h3 className="section-title">询价明细</h3>
      <dl className="mt-3 grid gap-3 sm:grid-cols-2">
        <FieldValue label="地址" value={readText(request.address_line) || "-"} />
        <FieldValue label="邮编" value={readText(request.postal_code) || record.postal_code || "-"} />
        <FieldValue label="城市/省份" value={`${record.city || readText(request.city) || "-"} / ${record.province || readText(request.province) || "-"}`} />
        <FieldValue label="货物" value={`${readText(request.cbm) || "-"} CBM / ${readText(request.weight_kg) || "-"} KG / ${readText(request.piece_count) || "-"}件`} />
        <FieldValue label="计费托数" value={formatNullable(record.billing_pallets)} />
        <FieldValue label="托数拆分" value={readText(result.pallet_breakdown) || formatPalletBreakdown(asRecord(result.pallet_breakdown))} />
      </dl>
    </div>
  );
}

function ManualPriceOverrideCard({
  error,
  isSaving,
  note,
  notice,
  onNoteChange,
  onPriceChange,
  onReplyChange,
  onSave,
  price,
  record,
  reply,
}: {
  error: string | null;
  isSaving: boolean;
  note: string;
  notice: string | null;
  onNoteChange: (value: string) => void;
  onPriceChange: (value: string) => void;
  onReplyChange: (value: string) => void;
  onSave: () => void;
  price: string;
  record: QuoteAuditLog;
  reply: string;
}) {
  return (
    <section className="rounded-md border border-amber-200 bg-amber-50/70 p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 className="section-title text-amber-950">人工确认价</h3>
          <p className="mt-1 text-sm leading-6 text-amber-800">
            用当前 quote_id 更新销售报价记录。会二次确认；不会修改审计原始记录，也不会修改 Zone 价格矩阵。
          </p>
        </div>
        <StatusBadge manual={record.manual_review_required} />
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-[12rem_minmax(0,1fr)]">
        <label>
          <span className="field-label">确认金额 USD</span>
          <input
            className="field-input"
            min="0"
            step="0.01"
            type="number"
            value={price}
            onChange={(event) => onPriceChange(event.target.value)}
            placeholder="例如 365.00"
          />
        </label>
        <label>
          <span className="field-label">确认/改价原因</span>
          <input
            className="field-input"
            value={note}
            onChange={(event) => onNoteChange(event.target.value)}
            placeholder="例如：已与供应商确认，按 Calgary Zone 5 / 3 托处理"
          />
        </label>
      </div>
      <label className="mt-3 block">
        <span className="field-label">客户回复文案（可选）</span>
        <textarea
          className="field-input min-h-28"
          value={reply}
          onChange={(event) => onReplyChange(event.target.value)}
          placeholder="留空则系统按确认金额生成基础报价话术。"
        />
      </label>
      {error && (
        <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {error}
        </div>
      )}
      {notice && (
        <div className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          {notice}
        </div>
      )}
      <button
        className="btn-primary mt-3"
        type="button"
        disabled={isSaving}
        onClick={onSave}
      >
        {isSaving ? "保存中..." : "保存人工确认价"}
      </button>
    </section>
  );
}

function StatusBadge({ manual }: { manual: boolean }) {
  return (
    <span
      className={`inline-flex w-fit rounded-full border px-3 py-1 text-xs font-semibold ${
        manual
          ? "border-amber-300 bg-amber-50 text-amber-800"
          : "border-emerald-300 bg-emerald-50 text-emerald-800"
      }`}
    >
      {manual ? "需人工确认" : "已报价"}
    </span>
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

function logicHeadline(record: QuoteAuditLog): string {
  const logic = asRecord(record.quote_logic);
  return readText(logic.headline) || "";
}

function asRecord(value: JsonValue | unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function readText(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "";
  }
  if (typeof value === "object") {
    return "";
  }
  return String(value);
}

function readStringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((item) => readText(item)).filter(Boolean);
}

function formatPalletBreakdown(value: Record<string, unknown>): string {
  const entries = Object.entries(value).filter(([, entryValue]) => entryValue !== null && entryValue !== undefined);
  if (!entries.length) {
    return "-";
  }
  return entries.map(([key, entryValue]) => `${key}:${entryValue}`).join(" / ");
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
    hermes_agent_correction: "历史 LLM 辅助建议",
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
