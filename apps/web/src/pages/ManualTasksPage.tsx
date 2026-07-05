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
                {item}
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
                        {task.status}
                      </span>
                    </div>

                    <dl className="mt-4 grid gap-3 sm:grid-cols-2">
                      <FieldValue label="reason" value={task.reason} />
                      <FieldValue label="assigned_to" value={task.assigned_to || "未分配"} />
                      <FieldValue
                        label="resolved_price_usd"
                        value={formatMoney(task.resolved_price_usd)}
                      />
                      <FieldValue label="created_at" value={formatDate(task.created_at)} />
                      <FieldValue label="updated_at" value={formatDate(task.updated_at)} />
                      <div>
                        <dt className="metric-label">risk_tags</dt>
                        <dd className="mt-2">
                          <RiskTags tags={task.risk_tags} />
                        </dd>
                      </div>
                    </dl>
                  </div>

                  <div className="rounded-md border border-slate-200 p-4">
                    <h3 className="section-title">处理任务</h3>
                    <div className="mt-3 grid gap-3">
                      <label>
                        <span className="field-label">status</span>
                        <select
                          className="field-input"
                          value={draft.status}
                          onChange={(event) =>
                            updateDraft(task.id, "status", event.target.value)
                          }
                        >
                          <option value="pending">pending</option>
                          <option value="in_progress">in_progress</option>
                          <option value="resolved">resolved</option>
                          <option value="cancelled">cancelled</option>
                        </select>
                      </label>
                      <label>
                        <span className="field-label">assigned_to</span>
                        <input
                          className="field-input"
                          value={draft.assigned_to}
                          onChange={(event) =>
                            updateDraft(task.id, "assigned_to", event.target.value)
                          }
                        />
                      </label>
                      <label>
                        <span className="field-label">resolved_price_usd</span>
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
                          仅用于人工处理结果，不会改写 Quote Engine 自动报价。
                        </p>
                      </label>
                      <label>
                        <span className="field-label">resolved_note</span>
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
                          <span className="field-label">wecom_bot_id</span>
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
