import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  getBatchDiagnosticReport,
  listBatchDiagnosticReports,
  type BatchDiagnosticReportDetail,
  type BatchDiagnosticReportSummary,
  type JsonValue,
} from "../api/client";

interface BatchDiagnosticReportsPageProps {
  embedded?: boolean;
}

type JsonObject = Record<string, JsonValue>;

export default function BatchDiagnosticReportsPage({ embedded = false }: BatchDiagnosticReportsPageProps) {
  const [reports, setReports] = useState<BatchDiagnosticReportSummary[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [detail, setDetail] = useState<BatchDiagnosticReportDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoadingList, setIsLoadingList] = useState(false);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);

  useEffect(() => {
    void loadReports();
  }, []);

  async function loadReports() {
    setIsLoadingList(true);
    setError(null);
    try {
      const response = await listBatchDiagnosticReports();
      setReports(response);
      const firstBatchId = selectedBatchId || response[0]?.batch_id || null;
      setSelectedBatchId(firstBatchId);
      if (firstBatchId) {
        await loadDetail(firstBatchId);
      } else {
        setDetail(null);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "批量诊断报告加载失败");
    } finally {
      setIsLoadingList(false);
    }
  }

  async function loadDetail(batchId: string) {
    setSelectedBatchId(batchId);
    setIsLoadingDetail(true);
    setError(null);
    try {
      setDetail(await getBatchDiagnosticReport(batchId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "批量诊断详情加载失败");
    } finally {
      setIsLoadingDetail(false);
    }
  }

  const activeSummary = useMemo(
    () => reports.find((item) => item.batch_id === selectedBatchId) ?? reports[0] ?? null,
    [reports, selectedBatchId],
  );

  return (
    <div className={embedded ? "space-y-4" : "mx-auto max-w-[1600px] space-y-5 px-4 py-5 sm:px-6 lg:px-8"}>
      {!embedded && (
        <header className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <p className="text-sm font-semibold text-teal-700">Batch Diagnostic Reports</p>
          <h1 className="mt-1 text-2xl font-semibold text-slate-950">批量诊断报告</h1>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            查看随机邮编命中测试的汇总、Top 缺口和整理建议。这里不会修改价格表，也不会发布学习规则。
          </p>
        </header>
      )}

      <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-950">批量测试总览</h2>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              优先读取服务器报告文件；如果 API 容器看不到文件，会回退展示已落库的诊断队列数据。
            </p>
          </div>
          <button
            className="btn-secondary min-h-10 px-4 py-2"
            type="button"
            onClick={() => void loadReports()}
          >
            {isLoadingList ? "刷新中..." : "刷新报告"}
          </button>
        </div>
        {error && (
          <div className="mt-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-medium text-rose-700">
            {error}
          </div>
        )}
      </section>

      <div className="grid gap-4 xl:grid-cols-[0.58fr_1.42fr]">
        <section className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-200 p-4">
            <h3 className="text-base font-semibold text-slate-950">报告批次</h3>
            <p className="mt-1 text-sm text-slate-600">
              {reports.length ? `共 ${reports.length} 个批次` : "暂无批量诊断报告"}
            </p>
          </div>
          <div className="max-h-[44rem] overflow-y-auto">
            {reports.map((report) => (
              <button
                key={report.batch_id}
                type="button"
                className={`block w-full border-b border-slate-100 p-4 text-left transition ${
                  activeSummary?.batch_id === report.batch_id ? "bg-teal-50" : "bg-white hover:bg-slate-50"
                }`}
                onClick={() => void loadDetail(report.batch_id)}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="font-mono text-base font-semibold text-slate-950">{report.batch_id}</p>
                    <p className="mt-1 text-xs text-slate-500">{formatDateTime(report.generated_at)}</p>
                  </div>
                  <span
                    className={`rounded-full px-2 py-1 text-xs font-semibold ${
                      report.report_available
                        ? "bg-emerald-50 text-emerald-700"
                        : "bg-amber-50 text-amber-700"
                    }`}
                  >
                    {report.report_available ? "完整报告" : "落库诊断"}
                  </span>
                </div>
                <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
                  <MiniStat label="样本" value={numberText(report.actual_sample_size)} />
                  <MiniStat label="人工" value={numberText(report.manual_required)} />
                  <MiniStat label="建议" value={numberText(report.learning_suggestion_count)} />
                </div>
              </button>
            ))}
          </div>
        </section>

        <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          {isLoadingDetail ? (
            <div className="rounded-md border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">
              正在读取批量诊断报告...
            </div>
          ) : detail ? (
            <ReportDetail report={detail} />
          ) : (
            <div className="rounded-md border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">
              还没有可展示的批量测试数据。先在服务器运行 postal hit test agent 后刷新。
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function ReportDetail({ report }: { report: BatchDiagnosticReportDetail }) {
  const matchedBy = report.counters?.matched_by ?? {};
  const riskTags = report.counters?.risk_tags ?? {};
  const originZones = report.counters?.origin_zone ?? {};
  const fullReportMissing = !report.report_available;

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-sm font-semibold text-teal-700">批次 {report.batch_id}</p>
          <h3 className="mt-1 text-2xl font-semibold text-slate-950">邮编命中测试报告</h3>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            生成时间：{formatDateTime(report.generated_at)} · 数据来源：
            {report.report_available ? "完整 JSON 报告" : "诊断队列回退汇总"}
          </p>
        </div>
        <span className="rounded-full bg-slate-100 px-3 py-2 text-sm font-semibold text-slate-700">
          {report.source}
        </span>
      </div>

      {fullReportMissing && (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm leading-6 text-amber-800">
          API 当前没有读到完整报告文件，只能展示已写入诊断队列的样本。要看到 5000 次完整成功率和 Top 建议，请确认
          `outputs/postal_hit_tests` 已挂载到 API 容器。
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <InfoTile label="实际样本" value={numberText(report.actual_sample_size)} />
        <InfoTile label="成功报价" value={numberText(report.quoted)} />
        <InfoTile label="需要人工" value={numberText(report.manual_required)} />
        <InfoTile label="成功率" value={report.quote_success_rate || "-"} />
        <InfoTile label="整理建议" value={numberText(report.learning_suggestion_count)} />
      </div>

      <Panel title="最值得先看的缺口" subtitle="价格矩阵缺口、重复人工、模糊命中会优先排在这里">
        <div className="grid gap-3 lg:grid-cols-3">
          <ClusterList title="价格矩阵缺口" clusters={report.top_price_gap_clusters} empty="暂无价格缺口聚类" />
          <ClusterList title="人工复核聚类" clusters={report.top_manual_clusters} empty="暂无重复人工聚类" />
          <ClusterList title="模糊命中聚类" clusters={report.top_fallback_clusters} empty="暂无模糊命中聚类" />
        </div>
      </Panel>

      <Panel title="Hermes / Agent 整理建议" subtitle="这里只是建议；人工确认后才会进入学习候选或改价格配置">
        {report.learning_suggestions.length ? (
          <div className="grid gap-3">
            {report.learning_suggestions.slice(0, 12).map((item, index) => {
              const suggestion = asObject(item);
              return (
                <SuggestionCard key={`${textOf(suggestion, "action")}-${index}`} item={suggestion} />
              );
            })}
          </div>
        ) : (
          <EmptyLine text="暂无达到阈值的整理建议。" />
        )}
      </Panel>

      <div className="grid gap-4 xl:grid-cols-3">
        <CounterPanel title="命中方式 Top" data={matchedBy} />
        <CounterPanel title="风险标签 Top" data={riskTags} />
        <CounterPanel title="仓库 / Zone Top" data={originZones} />
      </div>

      <Panel title="样例异常" subtitle="用于回看具体 quote_id 和规则命中原因">
        {report.sample_anomalies.length ? (
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs text-slate-500">
                <tr>
                  <th className="px-3 py-2">Quote ID</th>
                  <th className="px-3 py-2">邮编/城市</th>
                  <th className="px-3 py-2">仓/Zone</th>
                  <th className="px-3 py-2">托数</th>
                  <th className="px-3 py-2">原因</th>
                </tr>
              </thead>
              <tbody>
                {report.sample_anomalies.slice(0, 18).map((item, index) => {
                  const row = asObject(item);
                  return (
                    <tr key={`${textOf(row, "quote_id")}-${index}`} className="border-t border-slate-100">
                      <td className="px-3 py-2 font-mono font-semibold text-slate-950">{shortId(textOf(row, "quote_id"))}</td>
                      <td className="px-3 py-2 text-slate-700">
                        {textOf(row, "postal_prefix") || textOf(row, "postal_code") || "-"} / {textOf(row, "city") || "-"}
                      </td>
                      <td className="px-3 py-2 text-slate-700">
                        {textOf(row, "origin") || "-"} / {textOf(row, "zone") || "-"}
                      </td>
                      <td className="px-3 py-2 text-slate-700">{textOf(row, "billing_pallets") || "-"}</td>
                      <td className="max-w-md px-3 py-2 text-slate-600">
                        <span className="line-clamp-2">{textOf(row, "matched_rule") || tagsText(row.risk_tags) || "-"}</span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyLine text="暂无样例异常。" />
        )}
      </Panel>
    </div>
  );
}

function SuggestionCard({ item }: { item: JsonObject }) {
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-950">
            {actionLabel(textOf(item, "action"))}
          </p>
          <p className="mt-1 text-sm leading-6 text-slate-600">{textOf(item, "reason_zh") || "建议人工审核。"}</p>
        </div>
        <span className="w-fit rounded-full bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-700">
          支持 {textOf(item, "support_count") || "1"}
        </span>
      </div>
      <div className="mt-3 grid gap-2 text-xs text-slate-600 sm:grid-cols-2 xl:grid-cols-4">
        <span>FSA：{textOf(item, "postal_prefix") || "-"}</span>
        <span>城市：{textOf(item, "city") || "-"}</span>
        <span>建议仓：{textOf(item, "suggested_origin") || "-"}</span>
        <span>Zone：{textOf(item, "suggested_zone") || "-"}</span>
      </div>
    </div>
  );
}

function ClusterList({ clusters, empty, title }: { clusters: JsonValue[]; empty: string; title: string }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white p-3">
      <h4 className="text-sm font-semibold text-slate-950">{title}</h4>
      <div className="mt-3 space-y-2">
        {clusters.length ? (
          clusters.slice(0, 6).map((item, index) => {
            const cluster = asObject(item);
            const example = asObject(asArray(cluster.examples)[0]);
            return (
              <div key={`${title}-${index}`} className="rounded border border-slate-100 bg-slate-50 p-2">
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-semibold text-slate-950">
                    {textOf(example, "postal_prefix") || "-"} / {textOf(example, "city") || "-"}
                  </p>
                  <span className="rounded-full bg-amber-50 px-2 py-1 text-xs font-semibold text-amber-700">
                    {textOf(cluster, "count") || "0"} 次
                  </span>
                </div>
                <p className="mt-1 text-xs leading-5 text-slate-600">
                  {textOf(example, "origin") || "-"} Zone {textOf(example, "zone") || "-"} · {tagsText(example.risk_tags)}
                </p>
              </div>
            );
          })
        ) : (
          <p className="text-sm text-slate-500">{empty}</p>
        )}
      </div>
    </div>
  );
}

function CounterPanel({ data, title }: { data: Record<string, number>; title: string }) {
  const rows = Object.entries(data || {}).slice(0, 10);
  return (
    <Panel title={title}>
      {rows.length ? (
        <div className="space-y-2">
          {rows.map(([key, value]) => (
            <div key={key} className="flex items-center justify-between gap-3 rounded-md bg-slate-50 px-3 py-2 text-sm">
              <span className="min-w-0 truncate text-slate-700">{key}</span>
              <span className="font-semibold text-slate-950">{value}</span>
            </div>
          ))}
        </div>
      ) : (
        <EmptyLine text="暂无数据" />
      )}
    </Panel>
  );
}

function Panel({ children, subtitle, title }: { children: ReactNode; subtitle?: string; title: string }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-3">
        <h3 className="text-base font-semibold text-slate-950">{title}</h3>
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
      <p className="mt-2 text-xl font-semibold text-slate-950">{value}</p>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-slate-50 px-2 py-2">
      <p className="text-[11px] text-slate-500">{label}</p>
      <p className="mt-1 font-semibold text-slate-950">{value}</p>
    </div>
  );
}

function EmptyLine({ text }: { text: string }) {
  return <p className="rounded-md border border-dashed border-slate-200 p-3 text-sm text-slate-500">{text}</p>;
}

function asObject(value: JsonValue | undefined): JsonObject {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as JsonObject) : {};
}

function asArray(value: JsonValue | undefined): JsonValue[] {
  return Array.isArray(value) ? value : [];
}

function textOf(object: JsonObject, key: string): string {
  const value = object[key];
  if (value === null || value === undefined) {
    return "";
  }
  return String(value);
}

function tagsText(value: JsonValue | undefined): string {
  const tags = asArray(value).map((item) => String(item)).filter(Boolean);
  return tags.length ? tags.join(" / ") : "-";
}

function actionLabel(value: string): string {
  const labels: Record<string, string> = {
    fill_zone_price_matrix_after_supplier_confirmation: "补价格矩阵",
    manual_cluster_review: "人工聚类复核",
    review_expected_origin_formalization: "固化始发仓规则",
    review_fallback_zone_rule: "审核模糊分区规则",
    manual_review: "进入人工确认",
    review_rule_formalization: "整理可复用规则",
    no_action: "无需处理",
  };
  return labels[value] || value || "建议处理";
}

function numberText(value: number | null | undefined): string {
  return value === null || value === undefined ? "-" : String(value);
}

function shortId(value: string): string {
  if (!value) {
    return "-";
  }
  return value.length > 18 ? `${value.slice(0, 18)}...` : value;
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
