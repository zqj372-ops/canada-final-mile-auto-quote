import { useEffect, useMemo, useState } from "react";
import {
  listHermesLearningCandidates,
  listEmailConfigs,
  listManualTasks,
  updateManualTask,
  type EmailConfigPublic,
  type HermesLearningCandidate,
  type ManualQuoteTask,
  type ManualQuoteTaskUpdate,
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
  const [emailConfigs, setEmailConfigs] = useState<EmailConfigPublic[]>([]);
  const [learningCandidates, setLearningCandidates] = useState<HermesLearningCandidate[]>([]);
  const [notifyEmail, setNotifyEmail] = useState(false);
  const [selectedEmailConfigId, setSelectedEmailConfigId] = useState("");
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);
  const [taskQuery, setTaskQuery] = useState("");

  useEffect(() => {
    void refreshTasksAndLearning();
    void loadEmailConfigs();
  }, []);

  const visibleTasks = useMemo(() => {
    const filteredByStatus = filter === "all" ? tasks : tasks.filter((task) => task.status === filter);
    const query = taskQuery.trim().toLowerCase();
    if (!query) {
      return filteredByStatus;
    }
    return filteredByStatus.filter((task) => taskMatchesQuery(task, query));
  }, [filter, taskQuery, tasks]);

  const learningCandidateByTaskId = useMemo(() => {
    const map = new Map<number, HermesLearningCandidate>();
    learningCandidates.forEach((candidate) => {
      if (candidate.source_task_id !== null && !map.has(candidate.source_task_id)) {
        map.set(candidate.source_task_id, candidate);
      }
    });
    return map;
  }, [learningCandidates]);
  const selectedTask =
    visibleTasks.find((task) => task.id === selectedTaskId) ?? visibleTasks[0] ?? null;
  const selectedDraft = selectedTask ? drafts[selectedTask.id] ?? draftFromTask(selectedTask) : null;
  const selectedLearningCandidate = selectedTask
    ? learningCandidateByTaskId.get(selectedTask.id) ?? null
    : null;

  useEffect(() => {
    if (!visibleTasks.length) {
      if (selectedTaskId !== null) {
        setSelectedTaskId(null);
      }
      return;
    }
    if (!visibleTasks.some((task) => task.id === selectedTaskId)) {
      setSelectedTaskId(visibleTasks[0].id);
    }
  }, [selectedTaskId, visibleTasks]);

  async function refreshTasksAndLearning() {
    await Promise.all([loadTasks(), loadLearningCandidates()]);
  }

  async function loadTasks() {
    setIsLoading(true);
    setError(null);
    try {
      const response = await listManualTasks();
      const nextTasks = Array.isArray(response) ? response : [];
      setTasks(nextTasks);
      setDrafts(
        Object.fromEntries(nextTasks.map((task) => [task.id, draftFromTask(task)])),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "人工任务加载失败");
    } finally {
      setIsLoading(false);
    }
  }

  async function loadLearningCandidates() {
    try {
      const response = await listHermesLearningCandidates({ status: "all", limit: 200 });
      setLearningCandidates(Array.isArray(response) ? response : []);
    } catch {
      setLearningCandidates([]);
    }
  }

  async function loadEmailConfigs() {
    try {
      const response = await listEmailConfigs();
      setEmailConfigs(Array.isArray(response) ? response : []);
    } catch {
      setEmailConfigs([]);
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
        notify_email: notifyEmail,
        email_config_id: selectedEmailConfigId ? Number(selectedEmailConfigId) : null,
      };
      const updated = await updateManualTask(task.id, payload);
      setTasks((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setDrafts((current) => ({ ...current, [updated.id]: draftFromTask(updated) }));
      setNotice(`任务 ${updated.id} 已更新`);
      await loadLearningCandidates();
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
    <div className="manual-tasks-page">
      <header className="admin-page-header">
        <div>
          <h1>人工任务</h1>
          <p>AI 识别不确定或高风险的报价单，需要人工 review 和处理。</p>
        </div>
        <div className="manual-actions">
          <label className="manual-search">
            <span className="sr-only">搜索任务</span>
            <input
              value={taskQuery}
              onChange={(event) => setTaskQuery(event.target.value)}
              placeholder="搜索 quote_id、目的地、原因..."
            />
          </label>
          <button className="btn-secondary" type="button" onClick={() => void refreshTasksAndLearning()}>
            刷新
          </button>
        </div>
      </header>

      <div className="manual-tabs" role="tablist" aria-label="任务状态筛选">
        {(["pending", "resolved", "all"] as TaskFilter[]).map((item) => (
          <button
            key={item}
            type="button"
            className={filter === item ? "manual-tab-active" : ""}
            onClick={() => setFilter(item)}
          >
            {taskFilterLabel(item)}
            <span>{taskFilterCount(item, tasks)}</span>
          </button>
        ))}
      </div>

      {error && (
        <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <div className="rounded-md border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-900" role="status">
          {notice}
        </div>
      )}

      {isLoading ? (
        <section className="panel p-6 text-sm text-slate-600">正在加载任务...</section>
      ) : visibleTasks.length === 0 ? (
        <section className="panel p-6 text-sm text-slate-600">当前筛选下没有人工确认任务。</section>
      ) : selectedTask && selectedDraft ? (
        <div className="manual-task-workspace">
          <section className="panel manual-task-list">
            <div className="manual-list-head">
              <span>Quote ID</span>
              <span>目的地</span>
              <span>原因</span>
              <span>创建时间</span>
              <span>风险标签</span>
            </div>
            {visibleTasks.map((task) => {
              const isSelected = selectedTask.id === task.id;
              const details = buildInquiryDetails(task);
              const destination = briefDestination(details);
              return (
                <button
                  key={task.id}
                  className={`manual-list-row ${isSelected ? "manual-list-row-active" : ""}`}
                  type="button"
                  onClick={() => setSelectedTaskId(task.id)}
                >
                  <span className="manual-select-dot" aria-hidden="true" />
                  <strong>{task.quote_id}</strong>
                  <span>{destination}</span>
                  <span>{task.reason_zh || task.reason}</span>
                  <span>{formatDate(task.created_at)}</span>
                  <span>
                    <RiskTags tags={(task.risk_tag_labels?.length ? task.risk_tag_labels : task.risk_tags).slice(0, 2)} />
                  </span>
                </button>
              );
            })}
            <div className="manual-list-footer">
              <span>共 {visibleTasks.length} 条</span>
              <div>
                <button type="button" disabled>‹</button>
                <button className="active" type="button">1</button>
                <button type="button">2</button>
                <button type="button">3</button>
                <button type="button">4</button>
                <button type="button">›</button>
              </div>
              <select aria-label="每页条数">
                <option>10 条/页</option>
              </select>
            </div>
          </section>

          <section className="panel manual-detail-panel">
            <div className="manual-detail-header">
              <div>
                <p>Quote ID</p>
                <h2>{selectedTask.quote_id}</h2>
              </div>
              <TaskStatusBadge status={selectedTask.status} />
            </div>

            <ManualTaskLearningBridge
              candidate={selectedLearningCandidate}
              draft={selectedDraft}
              task={selectedTask}
            />

            <InquiryDetails task={selectedTask} />

            <section className="manual-process-form">
              <h3>处理表单</h3>
              <div className="grid gap-3 lg:grid-cols-3">
                <label>
                  <span className="field-label">状态</span>
                  <select
                    className="field-input"
                    value={selectedDraft.status}
                    onChange={(event) => updateDraft(selectedTask.id, "status", event.target.value)}
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
                    value={selectedDraft.assigned_to}
                    onChange={(event) => updateDraft(selectedTask.id, "assigned_to", event.target.value)}
                    placeholder="请输入处理人姓名"
                  />
                </label>
                <label>
                  <span className="field-label">人工确认金额 USD</span>
                  <input
                    className="field-input"
                    type="number"
                    min="0"
                    step="0.01"
                    value={selectedDraft.resolved_price_usd}
                    onChange={(event) => updateDraft(selectedTask.id, "resolved_price_usd", event.target.value)}
                    placeholder="请输入最终确认金额"
                  />
                </label>
              </div>
              <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_18rem]">
                <label>
                  <span className="field-label">处理备注</span>
                  <textarea
                    className="field-input min-h-28"
                    value={selectedDraft.resolved_note}
                    onChange={(event) => updateDraft(selectedTask.id, "resolved_note", event.target.value)}
                    placeholder="请说明处理过程、确认重点及特殊情况..."
                  />
                </label>
                <div className="grid gap-3 rounded-md border border-slate-200 p-3">
                  <label className="flex min-h-11 items-center gap-3">
                    <input
                      className="h-4 w-4 rounded border-slate-300 text-teal-700 focus:ring-teal-700"
                      type="checkbox"
                      checked={notifyEmail}
                      onChange={(event) => setNotifyEmail(event.target.checked)}
                    />
                    <span className="text-sm font-medium text-slate-800">保存后邮件发送给客户</span>
                  </label>
                  <label>
                    <span className="field-label">邮件通知配置</span>
                    <select
                      className="field-input"
                      value={selectedEmailConfigId}
                      onChange={(event) => setSelectedEmailConfigId(event.target.value)}
                      disabled={!notifyEmail}
                    >
                      <option value="">使用 manual_resolved/default 邮箱</option>
                      {emailConfigs.map((config) => (
                        <option key={config.id} value={config.id}>
                          {config.name} / {config.purpose}
                          {config.is_default ? " / 默认" : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              </div>
              <div className="mt-4 flex justify-center gap-3">
                <button
                  className="btn-secondary min-w-28"
                  type="button"
                  onClick={() =>
                    setDrafts((current) => ({
                      ...current,
                      [selectedTask.id]: draftFromTask(selectedTask),
                    }))
                  }
                >
                  取消
                </button>
                <button
                  className="btn-primary min-w-36"
                  type="button"
                  onClick={() => void saveTask(selectedTask)}
                  disabled={savingTaskId === selectedTask.id}
                >
                  {savingTaskId === selectedTask.id ? "保存中..." : "保存处理结果"}
                </button>
              </div>
            </section>
          </section>
        </div>
      ) : null}
    </div>
  );
}

function TaskStatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`manual-status-badge ${
        status === "resolved"
          ? "manual-status-resolved"
          : status === "cancelled"
            ? "manual-status-cancelled"
            : "manual-status-pending"
      }`}
    >
      {taskStatusLabel(status)}
    </span>
  );
}

function taskFilterCount(filter: TaskFilter, tasks: ManualQuoteTask[]): number {
  if (filter === "all") {
    return tasks.length;
  }
  return tasks.filter((task) => task.status === filter).length;
}

function taskMatchesQuery(task: ManualQuoteTask, query: string): boolean {
  const details = buildInquiryDetails(task);
  return [
    task.quote_id,
    task.reason,
    task.reason_zh,
    task.assigned_to,
    briefDestination(details),
    ...details.addressItems.map((item) => item.value),
    ...details.missingFields,
  ]
    .filter(Boolean)
    .some((value) => String(value).toLowerCase().includes(query));
}

function briefDestination(details: ReturnType<typeof buildInquiryDetails>): string {
  const city = details.addressItems.find((item) => item.label === "城市")?.value;
  const province = details.addressItems.find((item) => item.label === "省份")?.value;
  return [city, province]
    .filter((value) => value && value !== "未返回")
    .join(", ") || "目的地待确认";
}

function ManualTaskLearningBridge({
  candidate,
  draft,
  task,
}: {
  candidate: HermesLearningCandidate | null;
  draft: TaskDraft;
  task: ManualQuoteTask;
}) {
  const status = hermesBridgeStatus(task, draft, candidate);
  return (
    <section className={`rounded-md border px-3 py-3 ${status.className}`}>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Hermes 学习
          </p>
          <h4 className="mt-1 text-sm font-semibold text-slate-950">{status.title}</h4>
          <p className="mt-1 text-sm leading-5 text-slate-600">{status.description}</p>
        </div>
        <a
          className="inline-flex min-h-9 w-fit items-center justify-center rounded-md border border-blue-200 bg-white px-3 text-sm font-semibold text-blue-800 hover:bg-blue-50"
          href={withBasePath("/learning-candidates")}
        >
          打开 Hermes
        </a>
      </div>
      <div className="mt-3 grid gap-2 text-xs font-semibold text-slate-700 sm:grid-cols-3">
        <HermesStep active done label="1 人工确认" />
        <HermesStep active={status.step >= 2} done={status.step > 2} label="2 生成候选" />
        <HermesStep active={status.step >= 3} done={status.done} label="3 批准复用" />
      </div>
      {candidate && (
        <div className="mt-3 grid gap-2 rounded-md bg-white/70 p-2 text-sm sm:grid-cols-2">
          <span>
            <span className="text-slate-500">候选</span>
            <span className="ml-2 font-semibold text-slate-950">#{candidate.id}</span>
          </span>
          <span>
            <span className="text-slate-500">状态</span>
            <span className="ml-2 font-semibold text-slate-950">
              {candidateStatusLabel(candidate.status)}
            </span>
          </span>
          <span>
            <span className="text-slate-500">建议价</span>
            <span className="ml-2 font-semibold text-slate-950">
              {formatMoney(candidate.resolved_total_price_usd)}
            </span>
          </span>
          <span>
            <span className="text-slate-500">范围</span>
            <span className="ml-2 font-semibold text-slate-950">
              {candidate.scope} / {candidate.billing_pallets} 托
            </span>
          </span>
        </div>
      )}
    </section>
  );
}

function HermesStep({ active, done, label }: { active: boolean; done: boolean; label: string }) {
  return (
    <span
      className={`rounded-md px-2 py-1 text-center ${
        done
          ? "bg-emerald-100 text-emerald-800"
          : active
            ? "bg-blue-100 text-blue-800"
            : "bg-slate-100 text-slate-500"
      }`}
    >
      {label}
    </span>
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

      <div className="mt-4 grid min-w-0 gap-3 lg:grid-cols-3">
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
    <div className="min-w-0 rounded-md border border-slate-200 bg-white p-3">
      <h4 className="text-sm font-semibold text-slate-950">{title}</h4>
      <dl className="mt-3 grid gap-2">
        {items.map((item) => (
          <div key={item.label} className="grid min-w-0 grid-cols-[5.5rem_minmax(0,1fr)] gap-2 text-sm">
            <dt className="text-slate-500">{item.label}</dt>
            <dd className="min-w-0 break-words font-medium leading-5 text-slate-900 [overflow-wrap:anywhere]">
              {item.value}
            </dd>
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

function candidateStatusLabel(value: string): string {
  const labels: Record<string, string> = {
    pending_review: "待审核",
    approved: "已批准",
    rejected: "已拒绝",
  };
  return labels[value] ?? value;
}

function hermesBridgeStatus(
  task: ManualQuoteTask,
  draft: TaskDraft,
  candidate: HermesLearningCandidate | null,
): {
  className: string;
  description: string;
  done: boolean;
  step: number;
  title: string;
} {
  if (candidate) {
    if (candidate.status === "approved") {
      return {
        className: "border-emerald-200 bg-emerald-50",
        description: `已发布为学习规则 #${candidate.promoted_rule_id ?? "-"}，后续仅在 Zone/价格表未命中时复用。`,
        done: true,
        step: 3,
        title: "已进入 Hermes 并批准复用",
      };
    }
    return {
      className: candidate.status === "rejected" ? "border-slate-200 bg-slate-50" : "border-blue-200 bg-blue-50",
      description:
        candidate.status === "rejected"
          ? "这条候选已被拒绝，不会进入自动复用规则。"
          : "这条人工任务已生成 Hermes 待审核候选，批准后才会被自动报价复用。",
      done: false,
      step: candidate.status === "rejected" ? 2 : 3,
      title: `已生成候选 #${candidate.id} / ${candidateStatusLabel(candidate.status)}`,
    };
  }

  const result = asRecord(task.result_json);
  const request = asRecord(task.request_json);
  const draftIsResolved = draft.status === "resolved";
  const hasPrice = Boolean(draft.resolved_price_usd.trim() || task.resolved_price_usd);
  const hasBillingPallets = numberValue(result?.billing_pallets) !== null;
  const hasPostalBasis = Boolean(
    stringValue(request?.postal_code)
      || stringValue(result?.postal_code)
      || stringValue(result?.postal_prefix),
  );

  if (!draftIsResolved) {
    return {
      className: "border-slate-200 bg-slate-50",
      description: "先填写人工确认金额，并把处理状态保存为“已解决”。",
      done: false,
      step: 1,
      title: "尚未进入 Hermes",
    };
  }
  if (!hasPrice) {
    return {
      className: "border-amber-200 bg-amber-50",
      description: "状态已选“已解决”，但还没有人工确认金额；保存前不会生成 Hermes 候选。",
      done: false,
      step: 1,
      title: "缺人工确认金额",
    };
  }
  if (!hasBillingPallets) {
    return {
      className: "border-amber-200 bg-amber-50",
      description: "缺少可学习的计费托数。请先确认实际托数或重新报价，否则 Hermes 不会生成候选。",
      done: false,
      step: 1,
      title: "暂不能生成 Hermes 候选",
    };
  }
  if (!hasPostalBasis) {
    return {
      className: "border-amber-200 bg-amber-50",
      description: "缺少邮编或邮编前缀，无法确定学习规则适用范围。",
      done: false,
      step: 1,
      title: "缺少学习范围",
    };
  }
  if (task.status === "resolved" && task.resolved_price_usd) {
    return {
      className: "border-amber-200 bg-amber-50",
      description: "任务已解决但未关联到候选，可能已合并到相同范围的其他 Hermes 候选；请到 Hermes 学习页查看。",
      done: false,
      step: 2,
      title: "未找到关联候选",
    };
  }
  return {
    className: "border-blue-200 bg-blue-50",
    description: "保存后会自动生成 Hermes 待审核候选；候选批准前不会影响自动报价。",
    done: false,
    step: 2,
    title: "保存后生成 Hermes 候选",
  };
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
    detailItem("计费托数", formatBillingPallets(resultRecord.billing_pallets, palletBreakdown)),
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
    hermes_agent_correction: "Hermes Agent 纠错",
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
    volume_pallets: "体积",
    cbm_pallets: "体积",
    weight_pallets: "重量",
    long_piece_pallets: "超长",
    oversized_pallets: "超长",
    wooden_crate_pallets: "木箱",
    explicit_pallet_count: "显式",
    normal_basis_pallets: "基础",
    billing_pallets: "计费",
  };
  return Object.entries(value)
    .map(([key, entryValue]) => `${labels[key] ?? key}: ${formatPalletComponent(key, entryValue, value)}`)
    .join(" / ");
}

function formatBillingPallets(value: unknown, breakdown: JsonRecord | null): string {
  const suspiciousLongPiecePallets = getSuspiciousLongPiecePallets(breakdown);
  if (suspiciousLongPiecePallets !== null) {
    const normalBasis = numberValue(breakdown?.normal_basis_pallets)
      ?? maxFinite([
        numberValue(breakdown?.volume_pallets),
        numberValue(breakdown?.weight_pallets),
        numberValue(breakdown?.explicit_pallet_count),
      ]);
    return normalBasis !== null
      ? `异常 ${suspiciousLongPiecePallets} 托，需复核件数/最长边；基础约 ${normalBasis} 托`
      : `异常 ${suspiciousLongPiecePallets} 托，需复核件数/最长边`;
  }
  return displayValue(value);
}

function formatPalletComponent(key: string, value: unknown, breakdown: JsonRecord): string {
  const formatted = displayValue(value);
  if (key !== "long_piece_pallets") {
    return formatted;
  }
  const suspiciousLongPiecePallets = getSuspiciousLongPiecePallets(breakdown);
  return suspiciousLongPiecePallets !== null ? `${formatted}（异常需复核）` : formatted;
}

function getSuspiciousLongPiecePallets(breakdown: JsonRecord | null): number | null {
  const longPiecePallets = numberValue(breakdown?.long_piece_pallets);
  if (longPiecePallets === null || longPiecePallets < 50) {
    return null;
  }
  const normalBasis = numberValue(breakdown?.normal_basis_pallets)
    ?? maxFinite([
      numberValue(breakdown?.volume_pallets),
      numberValue(breakdown?.weight_pallets),
      numberValue(breakdown?.explicit_pallet_count),
    ]);
  const threshold = Math.max(50, (normalBasis ?? 0) * 10);
  return longPiecePallets > threshold ? longPiecePallets : null;
}

function numberValue(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function maxFinite(values: Array<number | null>): number | null {
  const finiteValues = values.filter((value): value is number => value !== null);
  return finiteValues.length ? Math.max(...finiteValues) : null;
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

function withBasePath(routePath: string): string {
  const base = normalizeBasePath(import.meta.env.VITE_APP_BASE_PATH || "/");
  const normalizedRoute = routePath.startsWith("/") ? routePath.slice(1) : routePath;
  return `${base}${normalizedRoute}`;
}

function normalizeBasePath(path: string): string {
  if (!path || path === "/") {
    return "/";
  }
  return path.endsWith("/") ? path : `${path}/`;
}
