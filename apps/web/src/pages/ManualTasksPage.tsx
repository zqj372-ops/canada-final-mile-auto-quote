import { useEffect, useMemo, useState } from "react";
import {
  listWeComBots,
  listManualTasks,
  updateManualTask,
  type ManualQuoteTask,
  type ManualQuoteTaskUpdate,
  type WeComBotConfigPublic,
} from "../api/client";
import RiskTags from "../components/RiskTags";

type TaskFilter = "pending" | "resolved" | "all";
type TaskStatus = "pending" | "in_progress" | "resolved" | "cancelled";

interface TaskDraft {
  status: string;
  assigned_to: string;
  resolved_price_usd: string;
  resolved_note: string;
}

export default function ManualTasksPage() {
  const [tasks, setTasks] = useState<ManualQuoteTask[]>([]);
  const [drafts, setDrafts] = useState<Record<number, TaskDraft>>({});
  const [filter, setFilter] = useState<TaskFilter>("pending");
  const [isLoading, setIsLoading] = useState(true);
  const [savingTaskId, setSavingTaskId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [wecomBots, setWecomBots] = useState<WeComBotConfigPublic[]>([]);
  const [notifyWecom, setNotifyWecom] = useState(false);
  const [selectedWecomBotId, setSelectedWecomBotId] = useState("");

  useEffect(() => {
    void loadTasks();
    void loadWecomBots();
  }, []);

  const visibleTasks = useMemo(() => {
    if (filter === "all") {
      return tasks;
    }
    return tasks.filter((task) => task.status === filter);
  }, [filter, tasks]);

  async function loadTasks() {
    setIsLoading(true);
    setError(null);
    try {
      const response = await listManualTasks();
      setTasks(response);
      setDrafts(
        Object.fromEntries(response.map((task) => [task.id, draftFromTask(task)])),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "人工任务加载失败");
    } finally {
      setIsLoading(false);
    }
  }

  async function loadWecomBots() {
    try {
      setWecomBots(await listWeComBots());
    } catch {
      setWecomBots([]);
    }
  }

  async function saveTask(task: ManualQuoteTask) {
    const draft = drafts[task.id] ?? draftFromTask(task);

    setSavingTaskId(task.id);
    setError(null);
    setNotice(null);
    if (draft.status === "resolved" && !draft.resolved_price_usd.trim()) {
      setError("标记为已解决时必须填写人工确认价格，系统会基于这条结果生成 Hermes 待审核候选。");
      setSavingTaskId(null);
      return;
    }

    try {
      const payload: ManualQuoteTaskUpdate = {
        status: draft.status || task.status,
        assigned_to: optionalText(draft.assigned_to),
        resolved_price_usd: optionalNumber(draft.resolved_price_usd),
        resolved_note: optionalText(draft.resolved_note),
        notify_wecom: notifyWecom,
        wecom_bot_id: selectedWecomBotId ? Number(selectedWecomBotId) : null,
      };
      const updated = await updateManualTask(task.id, payload);
      setTasks((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setDrafts((current) => ({ ...current, [updated.id]: draftFromTask(updated) }));
      setNotice(`任务 ${updated.id} 已更新`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "人工任务更新失败");
    } finally {
      setSavingTaskId(null);
    }
  }

  function updateDraft<K extends keyof TaskDraft>(
    taskId: number,
    key: K,
    value: TaskDraft[K],
  ) {
    setDrafts((current) => ({
      ...current,
      [taskId]: {
        ...(current[taskId] ?? {
          status: "pending",
          assigned_to: "",
          resolved_price_usd: "",
          resolved_note: "",
        }),
        [key]: value,
      },
    }));
  }

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
      <header className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-sm font-medium text-blue-800">Manual Tasks</p>
          <h1 className="mt-1 text-2xl font-semibold text-slate-950">
            人工确认池
          </h1>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            只处理无法自动命中价格表的报价。任务标记为已解决并填写金额后，系统会生成 Hermes 待审核候选；批准后才会复用。
          </p>
        </div>
        <button className="btn-secondary" type="button" onClick={() => void loadTasks()}>
          刷新任务
        </button>
      </header>

      <section className="panel p-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex flex-wrap gap-2" role="tablist" aria-label="任务状态筛选">
            {(["pending", "resolved", "all"] as TaskFilter[]).map((item) => (
              <button
                key={item}
                type="button"
                className={
                  filter === item
                    ? "btn-primary"
                    : "btn-secondary bg-white text-slate-700"
                }
                onClick={() => setFilter(item)}
              >
                {taskFilterLabel(item)}
              </button>
            ))}
          </div>
          <p className="text-sm text-slate-600">
            当前显示 {visibleTasks.length} / {tasks.length} 个任务
          </p>
        </div>
      </section>

      {error && (
        <div
          className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900"
          role="alert"
        >
          {error}
        </div>
      )}
      {notice && (
        <div
          className="rounded-md border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-900"
          role="status"
        >
          {notice}
        </div>
      )}

      {isLoading ? (
        <section className="panel p-6 text-sm text-slate-600">正在加载任务...</section>
      ) : visibleTasks.length === 0 ? (
        <section className="panel p-6 text-sm text-slate-600">
          当前筛选下没有人工确认任务。
        </section>
      ) : (
        <div className="grid gap-4">
          {visibleTasks.map((task) => {
            const draft = drafts[task.id] ?? draftFromTask(task);
            return (
              <article key={task.id} className="panel p-5">
                <div className="grid gap-4 lg:grid-cols-[1fr_0.9fr]">
                  <div>
                    <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
                      <div>
                        <p className="text-xs font-medium uppercase text-slate-500">
                          Task #{task.id}
                        </p>
                        <h2 className="mt-1 break-words text-lg font-semibold text-slate-950">
                          {task.quote_id}
                        </h2>
                      </div>
                      <span
                        className={`inline-flex rounded-md px-2 py-1 text-xs font-semibold ${
                          task.status === "resolved"
                            ? "bg-emerald-50 text-emerald-800"
                            : "bg-amber-50 text-amber-900"
                        }`}
                          >
                        {taskStatusLabel(task.status)}
                      </span>
                    </div>

                    <dl className="mt-4 grid gap-3 sm:grid-cols-2">
                      <FieldValue label="需人工原因" value={task.reason_zh || task.reason} />
                      <FieldValue label="处理人" value={task.assigned_to || "未分配"} />
                      <FieldValue
                        label="人工确认金额"
                        value={formatMoney(task.resolved_price_usd)}
                      />
                      <FieldValue label="创建时间" value={formatDate(task.created_at)} />
                      <FieldValue label="更新时间" value={formatDate(task.updated_at)} />
                      <div>
                        <dt className="metric-label">风险标签</dt>
                        <dd className="mt-2">
                          <RiskTags tags={task.risk_tag_labels?.length ? task.risk_tag_labels : task.risk_tags} />
                        </dd>
                      </div>
                    </dl>

                    <InquiryDetails task={task} />
                  </div>

                  <div className="rounded-md border border-slate-200 p-4">
                    <h3 className="section-title">处理任务</h3>
                    <p className="mt-1 text-sm leading-6 text-slate-600">
                      已解决任务必须填写人工确认金额；保存后只生成 Hermes 候选，不会直接影响报价。
                    </p>
                    <div className="mt-3 grid gap-3">
                      <label>
                        <span className="field-label">处理状态</span>
                        <select
                          className="field-input"
                          value={draft.status}
                          onChange={(event) =>
                            updateDraft(task.id, "status", event.target.value)
                          }
                        >
                          {(["pending", "in_progress", "resolved", "cancelled"] as TaskStatus[]).map((status) => (
                            <option key={status} value={status}>
                              {taskStatusLabel(status)}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        <span className="field-label">处理人</span>
                        <input
                          className="field-input"
                          value={draft.assigned_to}
                          onChange={(event) =>
                            updateDraft(task.id, "assigned_to", event.target.value)
                          }
                        />
                      </label>
                      <label>
                        <span className="field-label">人工确认金额 USD</span>
                        <input
                          className="field-input"
                          type="number"
                          min="0"
                          step="0.01"
                          value={draft.resolved_price_usd}
                          onChange={(event) =>
                            updateDraft(
                              task.id,
                              "resolved_price_usd",
                              event.target.value,
                            )
                          }
                        />
                        <p className="field-hint">
                          仅用于人工处理结果；已解决时必填，不会改写 Zone 价格矩阵。
                        </p>
                      </label>
                      <label>
                        <span className="field-label">处理备注</span>
                        <textarea
                          className="field-input min-h-24"
                          value={draft.resolved_note}
                          onChange={(event) =>
                            updateDraft(task.id, "resolved_note", event.target.value)
                          }
                        />
                      </label>
                      <div className="grid gap-3 rounded-md border border-slate-200 p-3">
                        <label className="flex min-h-11 items-center gap-3">
                          <input
                            className="h-4 w-4 rounded border-slate-300 text-blue-700 focus:ring-blue-700"
                            type="checkbox"
                            checked={notifyWecom}
                            onChange={(event) => setNotifyWecom(event.target.checked)}
                          />
                          <span className="text-sm font-medium text-slate-800">
                            resolved 后同步推送企业微信
                          </span>
                        </label>
                        <label>
                          <span className="field-label">企业微信机器人</span>
                          <select
                            className="field-input"
                            value={selectedWecomBotId}
                            onChange={(event) => setSelectedWecomBotId(event.target.value)}
                            disabled={!notifyWecom}
                          >
                            <option value="">使用 manual_resolved/default 机器人</option>
                            {wecomBots.map((bot) => (
                              <option key={bot.id} value={bot.id}>
                                {bot.name} / {bot.purpose}
                                {bot.is_default ? " / 默认" : ""}
                              </option>
                            ))}
                          </select>
                        </label>
                      </div>
                      <button
                        className="btn-primary"
                        type="button"
                        onClick={() => void saveTask(task)}
                        disabled={savingTaskId === task.id}
                      >
                        {savingTaskId === task.id ? "保存中..." : "保存处理结果"}
                      </button>
                    </div>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}

function InquiryDetails({ task }: { task: ManualQuoteTask }) {
  const details = buildInquiryDetails(task);

  return (
    <section className="mt-5 rounded-md border border-blue-100 bg-blue-50/40 p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 className="section-title">询价明细</h3>
          <p className="mt-1 text-sm leading-6 text-slate-600">
            展示客户原始输入、AI/规则解析字段和后端报价结果，方便人工确认。
          </p>
        </div>
        {details.quoteSource && (
          <span className="inline-flex rounded-md bg-white px-2.5 py-1 text-xs font-semibold text-blue-800 ring-1 ring-blue-200">
            {details.quoteSource}
          </span>
        )}
      </div>

      {details.customerMessage && (
        <div className="mt-4 rounded-md border border-slate-200 bg-white p-3">
          <p className="field-label">客户原始询价</p>
          <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words text-sm leading-6 text-slate-800">
            {details.customerMessage}
          </pre>
        </div>
      )}

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <DetailGroup title="货物信息" items={details.cargoItems} />
        <DetailGroup title="地址信息" items={details.addressItems} />
        <DetailGroup title="报价/服务信息" items={details.serviceItems} />
      </div>

      {details.missingFields.length > 0 && (
        <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-3">
          <p className="field-label text-amber-900">缺失字段</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {details.missingFields.map((field) => (
              <span key={field} className="rounded-md bg-white px-2 py-1 text-xs font-semibold text-amber-900">
                {fieldLabel(field)}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <JsonDetails title="请求 JSON" value={task.request_json} />
        <JsonDetails title="结果 JSON" value={task.result_json} />
      </div>
    </section>
  );
}

function DetailGroup({ title, items }: { title: string; items: Array<{ label: string; value: string }> }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white p-3">
      <h4 className="text-sm font-semibold text-slate-950">{title}</h4>
      <dl className="mt-3 grid gap-2">
        {items.map((item) => (
          <div key={item.label} className="grid grid-cols-[6rem_1fr] gap-3 text-sm">
            <dt className="text-slate-500">{item.label}</dt>
            <dd className="break-words font-medium text-slate-900">{item.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function JsonDetails({ title, value }: { title: string; value: unknown }) {
  return (
    <details className="rounded-md border border-slate-200 bg-white">
      <summary className="cursor-pointer px-3 py-2 text-sm font-semibold text-slate-800">
        {title}
      </summary>
      <pre className="max-h-72 overflow-auto border-t border-slate-200 bg-slate-950 p-3 text-xs leading-5 text-slate-100">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}

function draftFromTask(task: ManualQuoteTask): TaskDraft {
  return {
    status: task.status || "pending",
    assigned_to: task.assigned_to ?? "",
    resolved_price_usd:
      task.resolved_price_usd === null ? "" : String(task.resolved_price_usd),
    resolved_note: task.resolved_note ?? "",
  };
}

function FieldValue({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="metric-label">{label}</dt>
      <dd className="metric-value break-words tabular-nums">{value}</dd>
    </div>
  );
}

function optionalText(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function optionalNumber(value: string): number | null {
  if (!value.trim()) {
    return null;
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) {
    throw new Error("resolved_price_usd 必须是大于等于 0 的数字");
  }
  return parsed;
}

function taskFilterLabel(value: TaskFilter): string {
  const labels: Record<TaskFilter, string> = {
    pending: "待处理",
    resolved: "已解决",
    all: "全部",
  };
  return labels[value];
}

function taskStatusLabel(value: string): string {
  const labels: Record<string, string> = {
    pending: "待处理",
    in_progress: "处理中",
    resolved: "已解决",
    cancelled: "已取消",
  };
  return labels[value] ?? value;
}

type JsonRecord = Record<string, unknown>;

function buildInquiryDetails(task: ManualQuoteTask): {
  customerMessage: string | null;
  quoteSource: string | null;
  missingFields: string[];
  cargoItems: Array<{ label: string; value: string }>;
  addressItems: Array<{ label: string; value: string }>;
  serviceItems: Array<{ label: string; value: string }>;
} {
  const request = asRecord(task.request_json);
  const result = asRecord(task.result_json);
  const extraction = asRecord(result?.extraction);
  const palletBreakdown = asRecord(result?.pallet_breakdown);
  const accessorials = asRecord(result?.accessorials);
  const source = extraction ?? request ?? {};
  const resultRecord = result ?? {};
  const customerMessage = stringValue(request?.customer_message);
  const cbm = firstValue(source.cbm, request?.cbm);
  const weightKg = firstValue(source.weight_kg, request?.weight_kg);

  const cargoItems = [
    detailItem("件数", firstValue(source.piece_count, request?.piece_count)),
    detailItem("总体积 CBM", cbm, formatNumber),
    detailItem("总重量 KG", weightKg, formatNumber),
    detailItem("密度 KG/CBM", calculateDensity(cbm, weightKg)),
    detailItem("最大单边 cm", firstValue(source.longest_side_cm, request?.longest_side_cm), formatNumber),
    detailItem("包装类型", packagingLabel(stringValue(firstValue(source.packaging_type, request?.packaging_type)))),
    detailItem("显式托数", firstValue(source.explicit_pallet_count, request?.explicit_pallet_count)),
    detailItem("计费托数", resultRecord.billing_pallets),
    detailItem("托数拆分", formatPalletBreakdown(palletBreakdown)),
  ];

  const addressItems = [
    detailItem("地址", firstValue(source.address_line, request?.address_line)),
    detailItem("城市", firstValue(source.city, request?.city, resultRecord.city)),
    detailItem("省份", firstValue(source.province, request?.province, resultRecord.province)),
    detailItem("邮编", firstValue(source.postal_code, request?.postal_code, resultRecord.postal_code)),
    detailItem("推荐城市", resultRecord.preferred_city),
    detailItem("邮编前缀", resultRecord.postal_prefix),
    detailItem("始发仓", resultRecord.origin),
    detailItem("Zone", resultRecord.zone),
  ];

  const serviceItems = [
    detailItem("地址类型", addressTypeLabel(stringValue(firstValue(source.address_type, request?.address_type)))),
    detailItem("是否可堆叠", booleanLabel(firstValue(source.is_stackable, request?.is_stackable))),
    detailItem("需要尾板", booleanLabel(firstValue(source.requires_liftgate, request?.requires_liftgate))),
    detailItem("需要手叉车", booleanLabel(firstValue(source.requires_pallet_jack, request?.requires_pallet_jack))),
    detailItem("需要预约", booleanLabel(firstValue(source.requires_appointment, request?.requires_appointment))),
    detailItem("等待时间", appendUnit(firstValue(source.detention_minutes, request?.detention_minutes), "分钟")),
    detailItem("基础费用", formatMoneyLike(resultRecord.base_price_usd)),
    detailItem("燃油", formatMoneyLike(resultRecord.fuel_usd)),
    detailItem("附加费", formatAccessorials(accessorials)),
    detailItem("合计", formatMoneyLike(resultRecord.total_price_usd)),
  ];

  return {
    customerMessage,
    quoteSource: sourceTypeLabel(stringValue(resultRecord.source_type)),
    missingFields: arrayOfStrings(resultRecord.missing_fields),
    cargoItems,
    addressItems,
    serviceItems,
  };
}

function detailItem(
  label: string,
  value: unknown,
  formatter: (value: unknown) => string = displayValue,
): { label: string; value: string } {
  return { label, value: formatter(value) };
}

function firstValue(...values: unknown[]): unknown {
  return values.find((value) => value !== null && value !== undefined && value !== "");
}

function asRecord(value: unknown): JsonRecord | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as JsonRecord;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function arrayOfStrings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map((item) => String(item)).filter((item) => item.trim())
    : [];
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "未返回";
  }
  if (typeof value === "boolean") {
    return booleanLabel(value);
  }
  if (typeof value === "number") {
    return Number.isFinite(value) ? String(value) : "未返回";
  }
  if (typeof value === "string") {
    return value.trim() || "未返回";
  }
  return JSON.stringify(value);
}

function formatNumber(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "未返回";
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(parsed % 1 === 0 ? 0 : 3).replace(/\.?0+$/, "") : displayValue(value);
}

function calculateDensity(cbm: unknown, weightKg: unknown): string {
  const cbmNumber = Number(cbm);
  const weightNumber = Number(weightKg);
  if (!Number.isFinite(cbmNumber) || !Number.isFinite(weightNumber) || cbmNumber <= 0) {
    return "未返回";
  }
  return `${(weightNumber / cbmNumber).toFixed(1)}`;
}

function appendUnit(value: unknown, unit: string): string {
  const formatted = displayValue(value);
  return formatted === "未返回" ? formatted : `${formatted} ${unit}`;
}

function booleanLabel(value: unknown): string {
  if (value === true) {
    return "是";
  }
  if (value === false) {
    return "否";
  }
  return "待确认";
}

function packagingLabel(value: string | null): string {
  const labels: Record<string, string> = {
    carton: "纸箱",
    wooden_crate: "木箱",
    pallet: "托盘",
    woven_bag: "编织袋",
    flexible_packaging: "软包装",
    unknown: "待确认",
  };
  return value ? labels[value] ?? value : "未返回";
}

function addressTypeLabel(value: string | null): string {
  const labels: Record<string, string> = {
    commercial: "商业地址",
    residential: "住宅地址",
    private: "私人地址",
    rural_residential: "偏远住宅",
  };
  return value ? labels[value] ?? value : "待确认";
}

function sourceTypeLabel(value: string | null): string | null {
  if (!value) {
    return null;
  }
  const labels: Record<string, string> = {
    zone_matrix: "Zone 价格矩阵",
    manual_required: "需要人工报价",
    learned_manual_quote: "人工学习规则",
  };
  return labels[value] ? `${labels[value]} / ${value}` : value;
}

function fieldLabel(value: string): string {
  const labels: Record<string, string> = {
    address_line: "地址",
    postal_code: "邮编",
    city: "城市",
    province: "省份",
    cbm: "体积 CBM",
    weight_kg: "重量 KG",
    piece_count: "件数",
    packaging_type: "包装类型",
    address_type: "地址类型",
  };
  return labels[value] ?? value;
}

function formatPalletBreakdown(value: JsonRecord | null): string {
  if (!value || Object.keys(value).length === 0) {
    return "未返回";
  }
  const labels: Record<string, string> = {
    cbm_pallets: "体积",
    weight_pallets: "重量",
    oversized_pallets: "超长",
    wooden_crate_pallets: "木箱",
    explicit_pallet_count: "显式",
    billing_pallets: "计费",
  };
  return Object.entries(value)
    .map(([key, entryValue]) => `${labels[key] ?? key}: ${displayValue(entryValue)}`)
    .join(" / ");
}

function formatAccessorials(value: JsonRecord | null): string {
  if (!value || Object.keys(value).length === 0) {
    return "无";
  }
  const labels: Record<string, string> = {
    residential_fee_usd: "住宅",
    liftgate_fee_usd: "尾板",
    pallet_jack_fee_usd: "手叉车",
    appointment_fee_usd: "预约",
    detention_fee_usd: "等待",
  };
  return Object.entries(value)
    .map(([key, entryValue]) => `${labels[key] ?? key}: ${formatMoneyLike(entryValue)}`)
    .join(" / ");
}

function formatMoneyLike(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "未返回";
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `$${parsed.toFixed(2)}` : displayValue(value);
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

function formatMoney(value: string | number | null): string {
  if (value === null || value === "") {
    return "未填写";
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `$${parsed.toFixed(2)}` : `$${String(value)}`;
}
