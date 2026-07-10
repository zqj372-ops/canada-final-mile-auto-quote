import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import HermesModelSwitcher from "../components/HermesModelSwitcher";
import {
  getHermesDiagnostic,
  listHermesDiagnostics,
  runHermesDiagnostic,
  submitHermesDiagnosticSuggestion,
  type AIModelConfigPublic,
  type HermesDiagnosticRecord,
  type JsonValue,
} from "../api/client";

interface HermesDiagnosticsPageProps {
  embedded?: boolean;
}

type DiagnosticFilter = "pending" | "completed" | "failed" | "all";

export default function HermesDiagnosticsPage({ embedded = false }: HermesDiagnosticsPageProps) {
  const [filter, setFilter] = useState<DiagnosticFilter>("all");
  const [records, setRecords] = useState<HermesDiagnosticRecord[]>([]);
  const [selected, setSelected] = useState<HermesDiagnosticRecord | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isSavingSuggestion, setIsSavingSuggestion] = useState(false);
  const [isRunningAgent, setIsRunningAgent] = useState(false);
  const [suggestionNote, setSuggestionNote] = useState("");
  const [activeHermesConfig, setActiveHermesConfig] = useState<AIModelConfigPublic | null>(null);
  const detailRequestId = useRef(0);
  const agentRunRequestId = useRef(0);

  useEffect(() => {
    void loadRecords();
  }, [filter]);

  async function loadRecords() {
    setIsLoading(true);
    setError(null);
    try {
      const response = await listHermesDiagnostics({
        status: filter,
        quote_id: query.trim() || undefined,
        limit: 80,
      });
      setRecords(response);
      setSelected((current) => {
        if (!response.length) {
          return null;
        }
        if (current) {
          return response.find((item) => item.id === current.id) ?? response[0];
        }
        return response[0];
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Hermes 诊断队列加载失败");
    } finally {
      setIsLoading(false);
    }
  }

  async function selectRecord(record: HermesDiagnosticRecord) {
    const requestId = ++detailRequestId.current;
    agentRunRequestId.current += 1;
    setError(null);
    setSelected(record);
    try {
      const detail = await getHermesDiagnostic(record.id);
      if (requestId === detailRequestId.current) {
        setSelected(detail);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "读取诊断详情失败");
    }
  }

  async function runSelectedDiagnostic() {
    if (!selected) {
      return;
    }
    const diagnosticId = selected.id;
    const requestId = ++agentRunRequestId.current;
    setIsRunningAgent(true);
    setError(null);
    try {
      const response = await runHermesDiagnostic(diagnosticId);
      if (requestId !== agentRunRequestId.current) {
        return;
      }
      setSelected(response);
      setRecords((items) => items.map((item) => (item.id === response.id ? response : item)));
      if (response.status === "failed") {
        setError(response.agent_error || "Hermes 模型诊断失败");
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Hermes 模型诊断失败");
    } finally {
      setIsRunningAgent(false);
    }
  }

  async function saveSuggestion(action: "manual_review" | "learning_candidate" | "no_action") {
    if (!selected) {
      return;
    }
    const reason = suggestionNote.trim();
    if (!reason) {
      setError("请先填写 Hermes 建议说明。");
      return;
    }
    setIsSavingSuggestion(true);
    setError(null);
    try {
      const zoneHit = getObject(selected.diagnostic_package.zone_hit);
      const response = await submitHermesDiagnosticSuggestion(selected.id, {
        suggested_action: action,
        can_auto_correct: false,
        confidence: action === "no_action" ? 40 : 70,
        reason_zh: reason,
        suggested_origin: getText(zoneHit.origin) || null,
        suggested_zone: getNumber(zoneHit.zone),
        recommend_manual_review: action !== "no_action",
        recommend_learning_candidate: action === "learning_candidate",
      });
      setSelected(response);
      setRecords((items) => items.map((item) => (item.id === response.id ? response : item)));
      setSuggestionNote("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "保存 Hermes 建议失败");
    } finally {
      setIsSavingSuggestion(false);
    }
  }

  const counters = useMemo(() => {
    return {
      pending: records.filter((item) => item.status === "pending").length,
      completed: records.filter((item) => item.status === "completed").length,
      failed: records.filter((item) => item.status === "failed").length,
    };
  }, [records]);

  return (
    <div className={embedded ? "space-y-4" : "mx-auto max-w-[1600px] space-y-5 px-4 py-5 sm:px-6 lg:px-8"}>
      {!embedded && (
        <header className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <p className="text-sm font-semibold text-teal-700">Hermes Diagnostic Queue</p>
          <h1 className="mt-1 text-2xl font-semibold text-slate-950">Hermes 诊断队列</h1>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            报价成功或失败都会落诊断包。Hermes 只读这些包提出建议，不直接改价格；人工确认后才进入学习候选。
          </p>
        </header>
      )}

      <HermesModelSwitcher onConfigChange={setActiveHermesConfig} />

      <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-950">诊断列表</h2>
            <p className="text-sm leading-6 text-slate-600">
              先看系统报价逻辑，再看 Hermes 建议，最后由人工确认是否进入学习。
            </p>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <input
              className="min-h-10 rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-950 outline-none focus:border-teal-400 focus:ring-2 focus:ring-teal-100"
              placeholder="搜索 quote_id"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  void loadRecords();
                }
              }}
            />
            <button className="btn-secondary min-h-10 px-4 py-2" type="button" onClick={() => void loadRecords()}>
              刷新
            </button>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2" role="tablist" aria-label="Hermes 诊断状态">
          {(["all", "pending", "completed", "failed"] as DiagnosticFilter[]).map((item) => (
            <button
              key={item}
              className={`min-h-9 rounded-md border px-3 text-sm font-semibold transition ${
                filter === item
                  ? "border-teal-500 bg-teal-600 text-white shadow-sm"
                  : "border-slate-200 bg-white text-slate-700 hover:border-teal-200 hover:bg-slate-50"
              }`}
              type="button"
              onClick={() => setFilter(item)}
            >
              {filterLabel(item)}
            </button>
          ))}
          <span className="ml-auto rounded-md bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-800">
            待处理 {counters.pending}
          </span>
          <span className="rounded-md bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-800">
            已建议 {counters.completed}
          </span>
          <span className="rounded-md bg-rose-50 px-3 py-2 text-xs font-semibold text-rose-800">
            失败 {counters.failed}
          </span>
        </div>

        {error && (
          <div className="mt-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-medium text-rose-700">
            {error}
          </div>
        )}
      </section>

      <div className="grid gap-4 xl:grid-cols-[0.82fr_1.18fr]">
        <section className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-200 p-4">
            <h3 className="text-base font-semibold text-slate-950">队列</h3>
            <p className="mt-1 text-sm text-slate-600">
              {isLoading ? "正在加载..." : records.length ? `共 ${records.length} 条诊断` : "当前筛选下没有诊断"}
            </p>
          </div>
          <div className="max-h-[46rem] overflow-y-auto">
            {records.map((record) => (
              <button
                key={record.id}
                type="button"
                className={`block w-full border-b border-slate-100 p-4 text-left transition ${
                  selected?.id === record.id ? "bg-teal-50" : "bg-white hover:bg-slate-50"
                }`}
                onClick={() => void selectRecord(record)}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="font-mono text-sm font-semibold text-teal-700">{shortQuoteId(record.quote_id)}</p>
                    <p className="mt-1 truncate text-base font-semibold text-slate-950">
                      {locationSummary(record)}
                    </p>
                  </div>
                  <StatusPill status={record.status} quoteStatus={record.quote_status} />
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-600">
                  <span>来源：{sourceLabel(record.source_type)}</span>
                  <span>状态：{record.quote_status === "quoted" ? "已报价" : "需复核"}</span>
                  <span>创建：{formatDateTime(record.created_at)}</span>
                  <span>建议：{record.suggested_action ? actionLabel(record.suggested_action) : "待判断"}</span>
                </div>
              </button>
            ))}
          </div>
        </section>

        <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          {selected ? (
            <DiagnosticDetail
              record={selected}
              suggestionNote={suggestionNote}
              isSavingSuggestion={isSavingSuggestion}
              isRunningAgent={isRunningAgent}
              activeHermesConfig={activeHermesConfig}
              onNoteChange={setSuggestionNote}
              onRunAgent={runSelectedDiagnostic}
              onSaveSuggestion={saveSuggestion}
            />
          ) : (
            <div className="rounded-md border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">
              选择左侧诊断后查看系统逻辑、Hermes 建议和人工处理状态。
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function DiagnosticDetail({
  record,
  suggestionNote,
  isSavingSuggestion,
  isRunningAgent,
  activeHermesConfig,
  onNoteChange,
  onRunAgent,
  onSaveSuggestion,
}: {
  record: HermesDiagnosticRecord;
  suggestionNote: string;
  isSavingSuggestion: boolean;
  isRunningAgent: boolean;
  activeHermesConfig: AIModelConfigPublic | null;
  onNoteChange: (value: string) => void;
  onRunAgent: () => void;
  onSaveSuggestion: (action: "manual_review" | "learning_candidate" | "no_action") => void;
}) {
  const pkg = record.diagnostic_package;
  const request = getObject(pkg.quote_request);
  const result = getObject(pkg.quote_result);
  const address = getObject(pkg.address);
  const zoneHit = getObject(pkg.zone_hit);
  const priceMatrix = getObject(pkg.price_matrix);
  const failure = getObject(pkg.failure);
  const privateReference = getObject(pkg.private_reference_context);
  const neighboringFsa = getObjectArray(pkg.neighboring_fsa);
  const manualHistory = getObjectArray(pkg.historical_manual_confirmations);
  const suggestion = record.agent_suggestion ?? {};

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-sm font-semibold text-blue-700">诊断 #{record.id}</p>
          <h3 className="mt-1 text-2xl font-semibold tracking-normal text-slate-950">
            {shortQuoteId(record.quote_id)} / {getText(address.postal_prefix) || "无邮编前缀"}
          </h3>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            这条记录只解释系统为什么这样报价或为什么进入人工复核；不会修改 Zone 价格矩阵。
          </p>
        </div>
        <StatusPill status={record.status} quoteStatus={record.quote_status} />
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <InfoTile label="报价状态" value={record.quote_status === "quoted" ? "已报价" : "需人工复核"} />
        <InfoTile label="邮编 / 城市" value={`${getText(address.postal_prefix) || "-"} / ${getText(address.city) || "-"}`} />
        <InfoTile label="省份 / 预期始发" value={`${getText(address.province) || "-"} / ${getText(address.expected_origin_by_province) || "-"}`} />
        <InfoTile label="托数 / 金额" value={`${getText(result.billing_pallets) || "-"} 托 / ${money(getText(result.total_price_usd))}`} />
      </div>

      <Panel title="系统报价逻辑" subtitle="Quote Engine 的原始路径">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          <InfoTile label="来源类型" value={sourceLabel(getText(zoneHit.source_type))} />
          <InfoTile label="命中方式" value={getText(zoneHit.matched_by) || "未命中"} />
          <InfoTile label="候选数量" value={getText(zoneHit.candidate_count) || "0"} />
          <InfoTile label="命中始发仓" value={getText(zoneHit.origin) || "未返回"} />
          <InfoTile label="命中 Zone" value={getText(zoneHit.zone) || "未返回"} />
          <InfoTile label="基础价" value={money(getText(result.base_price_usd))} />
        </div>
        <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-3 text-sm leading-6 text-slate-700">
          {getText(zoneHit.matched_rule) || getText(failure.reason) || "系统未返回命中说明。"}
        </div>
      </Panel>

      <Panel title="价格矩阵检查" subtitle="只展示系统是否找到对应 origin + Zone + 托数的价格">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <InfoTile label="请求始发" value={getText(priceMatrix.requested_origin) || "待匹配"} />
          <InfoTile label="请求 Zone" value={getText(priceMatrix.requested_zone) || "待匹配"} />
          <InfoTile label="请求托数" value={getText(priceMatrix.requested_billing_pallets) || "待计算"} />
          <InfoTile label="价格命中" value={getBool(priceMatrix.exact_price_found) ? "已命中" : "未命中"} />
        </div>
      </Panel>

      <Panel title="相邻 FSA 证据" subtitle="给 Hermes 判断是否有可解释的邻近分区，不直接生成价格">
        {neighboringFsa.length ? (
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs text-slate-500">
                <tr>
                  <th className="px-3 py-2">FSA</th>
                  <th className="px-3 py-2">城市</th>
                  <th className="px-3 py-2">仓/Zone</th>
                  <th className="px-3 py-2">同托数价格</th>
                  <th className="px-3 py-2">说明</th>
                </tr>
              </thead>
              <tbody>
                {neighboringFsa.slice(0, 8).map((item, index) => (
                  <tr key={`${getText(item.postal_prefix)}-${index}`} className="border-t border-slate-100">
                    <td className="px-3 py-2 font-semibold text-slate-950">{getText(item.postal_prefix) || "-"}</td>
                    <td className="px-3 py-2 text-slate-700">{getText(item.city) || "-"}</td>
                    <td className="px-3 py-2 text-slate-700">
                      {getText(item.origin) || "-"} / {getText(item.zone) || "-"}
                    </td>
                    <td className="px-3 py-2 font-semibold text-slate-950">
                      {getBool(item.has_price_for_billing_pallets) ? money(getText(item.base_price_usd)) : "无"}
                    </td>
                    <td className="px-3 py-2 text-slate-600">{getText(item.note) || getText(item.match_level) || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyLine text="没有找到同省相邻 FSA 证据。" />
        )}
      </Panel>

      <Panel title="历史人工确认" subtitle="只作为证据，批准学习前不会复用">
        {manualHistory.length ? (
          <div className="grid gap-3 md:grid-cols-2">
            {manualHistory.slice(0, 6).map((item, index) => (
              <div key={`${getText(item.quote_id)}-${index}`} className="rounded-md border border-slate-200 bg-white p-3">
                <p className="font-mono text-sm font-semibold text-teal-700">{getText(item.quote_id) || "-"}</p>
                <p className="mt-1 text-sm text-slate-700">
                  {getText(item.city) || "-"} / {getText(item.province) || "-"} / {getText(item.postal_prefix) || "-"}
                </p>
                <p className="mt-2 text-sm font-semibold text-slate-950">
                  {money(getText(item.resolved_price_usd))} · {getText(item.billing_pallets) || "-"} 托
                </p>
              </div>
            ))}
          </div>
        ) : (
          <EmptyLine text="暂无可参考的历史人工确认。" />
        )}
      </Panel>

      <Panel title="私有地址参考包" subtitle="Agent/RAG 小上下文，不读取完整 Excel">
        {getBool(privateReference.available) ? (
          <div className="grid gap-3 md:grid-cols-3">
            <InfoTile label="参考包状态" value="已返回" />
            <InfoTile label="上下文键" value={Object.keys(privateReference).slice(0, 4).join(" / ") || "-"} />
            <InfoTile label="用途" value="只做地址和历史证据参考" />
          </div>
        ) : (
          <EmptyLine text={getText(privateReference.reason) || "私有地址参考包未配置。"} />
        )}
      </Panel>

      <Panel title="Hermes 建议" subtitle="Agent 只能输出建议，不能直接改价">
        {record.agent_suggestion ? (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <InfoTile label="建议动作" value={actionLabel(record.suggested_action || getText(suggestion.suggested_action))} />
            <InfoTile label="是否可自动纠错" value={getBool(suggestion.can_auto_correct) ? "建议可纠错" : "不建议自动纠错"} />
            <InfoTile label="建议 Zone" value={`${getText(suggestion.suggested_origin) || "-"} / ${getText(suggestion.suggested_zone) || "-"}`} />
            <InfoTile label="置信度" value={`${record.confidence ?? getText(suggestion.confidence) ?? 0}%`} />
            <div className="rounded-md border border-slate-200 bg-slate-50 p-3 md:col-span-2 xl:col-span-4">
              <p className="text-xs font-semibold text-slate-500">原因</p>
              <p className="mt-1 text-sm leading-6 text-slate-800">{getText(suggestion.reason_zh) || "未返回原因。"}</p>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <EmptyLine text="Hermes Agent 还没有提交建议。可以用当前绑定的模型立即运行，也可以人工记录建议。" />
            <button
              className="btn-primary min-h-10 w-full px-3 py-2 sm:w-auto"
              type="button"
              disabled={!activeHermesConfig || isRunningAgent || isSavingSuggestion}
              onClick={onRunAgent}
            >
              {isRunningAgent
                ? `${activeHermesConfig?.model_name || "Hermes"} 诊断中...`
                : activeHermesConfig
                  ? `用 ${activeHermesConfig.model_name} 运行 Hermes 诊断`
                  : "请先配置 Hermes 模型"}
            </button>
            <textarea
              className="min-h-24 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-950 outline-none focus:border-teal-400 focus:ring-2 focus:ring-teal-100"
              placeholder="写明建议原因，例如：相邻 S7H/S7K 均指向 Calgary Zone 5，但价格矩阵缺 3 托价格，建议人工复核后生成学习候选。"
              value={suggestionNote}
              onChange={(event) => onNoteChange(event.target.value)}
            />
            <div className="grid gap-2 sm:grid-cols-3">
              <button
                className="btn-secondary min-h-10 px-3 py-2"
                type="button"
                disabled={isSavingSuggestion}
                onClick={() => onSaveSuggestion("no_action")}
              >
                记录为不纠错
              </button>
              <button
                className="btn-secondary min-h-10 px-3 py-2"
                type="button"
                disabled={isSavingSuggestion}
                onClick={() => onSaveSuggestion("manual_review")}
              >
                建议人工确认
              </button>
              <button
                className="btn-primary min-h-10 px-3 py-2"
                type="button"
                disabled={isSavingSuggestion}
                onClick={() => onSaveSuggestion("learning_candidate")}
              >
                建议生成学习候选
              </button>
            </div>
          </div>
        )}
      </Panel>

      <Panel title="人工确认与学习发布" subtitle="真正可复用规则只从人工确认后的学习候选来">
        <div className="grid gap-3 md:grid-cols-3">
          <InfoTile label="是否建议人工" value={record.recommend_manual_review === false ? "否" : "是"} />
          <InfoTile label="是否建议学习" value={record.recommend_learning_candidate ? "是" : "否"} />
          <InfoTile label="学习候选" value={record.learning_candidate_id ? `#${record.learning_candidate_id}` : "未生成"} />
        </div>
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm leading-6 text-amber-900">
          运行顺序：系统报价或进入人工复核 → 写入诊断队列 → Hermes 提建议 → 人工确认价格 →
          生成学习候选 → 批准后发布为学习规则 → 后续仅在 Zone/价格表未命中时复用。
        </div>
      </Panel>
    </div>
  );
}

function Panel({ children, subtitle, title }: { children: ReactNode; subtitle?: string; title: string }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-3">
        <h4 className="text-base font-semibold text-slate-950">{title}</h4>
        {subtitle && <p className="mt-1 text-sm leading-6 text-slate-600">{subtitle}</p>}
      </div>
      {children}
    </section>
  );
}

function InfoTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
      <p className="text-xs font-semibold text-slate-500">{label}</p>
      <p className="mt-1 break-words text-base font-semibold text-slate-950">{value || "-"}</p>
    </div>
  );
}

function EmptyLine({ text }: { text: string }) {
  return <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-3 text-sm text-slate-600">{text}</div>;
}

function StatusPill({ quoteStatus, status }: { quoteStatus: string; status: string }) {
  const color =
    status === "completed"
      ? "border-emerald-200 bg-emerald-50 text-emerald-700"
      : status === "failed"
        ? "border-rose-200 bg-rose-50 text-rose-700"
        : "border-amber-200 bg-amber-50 text-amber-700";
  return (
    <span className={`shrink-0 rounded-full border px-3 py-1 text-xs font-semibold ${color}`}>
      {quoteStatus === "quoted" ? "已报价" : "需复核"} · {statusLabel(status)}
    </span>
  );
}

function getObject(value: JsonValue | undefined): Record<string, JsonValue> {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value;
  }
  return {};
}

function getObjectArray(value: JsonValue | undefined): Array<Record<string, JsonValue>> {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is Record<string, JsonValue> => Boolean(item && typeof item === "object" && !Array.isArray(item)));
}

function getText(value: JsonValue | undefined): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "";
}

function getNumber(value: JsonValue | undefined): number | null {
  if (typeof value === "number") {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function getBool(value: JsonValue | undefined): boolean {
  if (typeof value === "boolean") {
    return value;
  }
  if (typeof value === "string") {
    return ["true", "1", "yes", "是"].includes(value.toLowerCase());
  }
  return false;
}

function locationSummary(record: HermesDiagnosticRecord): string {
  const pkg = record.diagnostic_package;
  const address = getObject(pkg.address);
  return [getText(address.city), getText(address.province), getText(address.postal_prefix)].filter(Boolean).join(" / ") || "地址待识别";
}

function shortQuoteId(quoteId: string): string {
  return quoteId.length > 8 ? quoteId.slice(0, 8) : quoteId;
}

function money(value: string): string {
  return value ? `USD ${value}` : "未返回";
}

function filterLabel(value: DiagnosticFilter): string {
  const labels: Record<DiagnosticFilter, string> = {
    all: "全部",
    pending: "待建议",
    completed: "已建议",
    failed: "失败",
  };
  return labels[value];
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    pending: "待建议",
    completed: "已建议",
    failed: "失败",
  };
  return labels[status] ?? status;
}

function sourceLabel(sourceType: string): string {
  const labels: Record<string, string> = {
    zone_matrix: "Zone 价格矩阵",
    manual_required: "需要人工复核",
    learned_manual_quote: "人工学习规则",
    llm_auxiliary_advice: "LLM 辅助建议",
    hermes_agent_correction: "历史 LLM 辅助建议",
  };
  return labels[sourceType] ?? sourceType ?? "-";
}

function actionLabel(action: string | null): string {
  const labels: Record<string, string> = {
    no_action: "不建议纠错",
    manual_review: "建议人工确认",
    learning_candidate: "建议生成学习候选",
    suggest_zone_matrix: "建议 Zone 矩阵方向",
  };
  return action ? labels[action] ?? action : "待判断";
}

function formatDateTime(value: string | null): string {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}
