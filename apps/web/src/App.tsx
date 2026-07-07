import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  clearStoredApiKey,
  getApiBaseUrl,
  getBackofficeActor,
  getQuoteErrorSummary,
  getStoredApiKey,
  setStoredApiKey,
  type CurrentActor,
  type QuoteErrorSummary,
} from "./api/client";
import AIQuotePage from "./pages/AIQuotePage";
import AISettingsPage from "./pages/AISettingsPage";
import AuditPage from "./pages/AuditPage";
import EmailSettingsPage from "./pages/EmailSettingsPage";
import LearningCandidatesPage from "./pages/LearningCandidatesPage";
import ManualTasksPage from "./pages/ManualTasksPage";
import PricingSettingsPage from "./pages/PricingSettingsPage";
import QuotePage from "./pages/QuotePage";
import QuoteSettingsPage from "./pages/QuoteSettingsPage";
import SearchSettingsPage from "./pages/SearchSettingsPage";

type RoutePath =
  | "/quote"
  | "/admin"
  | "/ai-quote"
  | "/manual-tasks"
  | "/learning-candidates"
  | "/audit"
  | "/settings/quote"
  | "/settings/pricing"
  | "/settings/ai"
  | "/settings/search"
  | "/settings/email";
const APP_BASE_PATH = normalizeBasePath(import.meta.env.VITE_APP_BASE_PATH || "/");

const adminRoutes: Array<{ path: RoutePath; label: string; description: string; group: "workbench" | "settings" }> = [
  { path: "/admin", label: "控制台", description: "仪表盘", group: "workbench" },
  { path: "/manual-tasks", label: "人工任务", description: "复核", group: "workbench" },
  { path: "/learning-candidates", label: "Hermes 学习", description: "候选", group: "workbench" },
  { path: "/audit", label: "审计查询", description: "日志", group: "workbench" },
  { path: "/ai-quote", label: "AI 调试", description: "提取", group: "workbench" },
  { path: "/settings/quote", label: "报价配置", description: "前台", group: "settings" },
  { path: "/settings/pricing", label: "价格配置", description: "价格", group: "settings" },
  { path: "/settings/ai", label: "AI 模型", description: "模型", group: "settings" },
  { path: "/settings/search", label: "搜索 API", description: "地址", group: "settings" },
  { path: "/settings/email", label: "邮件通知", description: "通知", group: "settings" },
  { path: "/quote", label: "前台报价", description: "销售", group: "settings" },
];

const adminGroupLabels = {
  workbench: "工作台",
  settings: "配置中心",
} as const;

export default function App() {
  const [path, setPath] = useState<RoutePath>(() =>
    normalizePath(window.location.pathname),
  );
  const [apiKeyInput, setApiKeyInput] = useState(() => getStoredApiKey("admin"));
  const [hasApiKey, setHasApiKey] = useState(() => Boolean(getStoredApiKey("admin")));
  const [adminActor, setAdminActor] = useState<CurrentActor | null>(null);
  const [adminAuthError, setAdminAuthError] = useState<string | null>(null);
  const [isVerifyingAdminKey, setIsVerifyingAdminKey] = useState(false);

  useEffect(() => {
    function handlePopState() {
      setPath(normalizePath(window.location.pathname));
    }
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    const main = document.getElementById("main-content");
    main?.focus({ preventScroll: true });
  }, [path]);

  useEffect(() => {
    if (path === "/quote" || adminActor || isVerifyingAdminKey || !getStoredApiKey("admin")) {
      return;
    }
    void verifyAdminKey();
  }, [path, adminActor, isVerifyingAdminKey]);

  const page = useMemo(() => {
    if (path === "/admin") {
      return <AdminHomePage navigate={navigate} />;
    }
    if (path === "/ai-quote") {
      return <AIQuotePage />;
    }
    if (path === "/manual-tasks") {
      return <ManualTasksPage />;
    }
    if (path === "/learning-candidates") {
      return <LearningCandidatesPage />;
    }
    if (path === "/audit") {
      return <AuditPage />;
    }
    if (path === "/settings/ai") {
      return <AISettingsPage />;
    }
    if (path === "/settings/quote") {
      return <QuoteSettingsPage />;
    }
    if (path === "/settings/pricing") {
      return <PricingSettingsPage />;
    }
    if (path === "/settings/search") {
      return <SearchSettingsPage />;
    }
    if (path === "/settings/email") {
      return <EmailSettingsPage />;
    }
    return <QuotePage adminHref={withBasePath("/admin")} />;
  }, [path]);

  function navigate(nextPath: RoutePath) {
    if (nextPath === path) {
      return;
    }
    window.history.pushState({}, "", withBasePath(nextPath));
    setPath(nextPath);
  }

  async function verifyAdminKey(): Promise<boolean> {
    const trimmed = apiKeyInput.trim();
    setAdminAuthError(null);
    if (!trimmed) {
      clearStoredApiKey("admin");
      setHasApiKey(false);
      setAdminActor(null);
      setAdminAuthError("请输入后台 API Key。");
      return false;
    }

    setStoredApiKey("admin", trimmed);
    setIsVerifyingAdminKey(true);
    try {
      const actor = await getBackofficeActor();
      setAdminActor(actor);
      setHasApiKey(true);
      setAdminAuthError(null);
      return true;
    } catch (caught) {
      clearStoredApiKey("admin");
      setHasApiKey(false);
      setAdminActor(null);
      setAdminAuthError(
        caught instanceof Error ? caught.message : "后台 API Key 验证失败",
      );
      return false;
    } finally {
      setIsVerifyingAdminKey(false);
    }
  }

  function clearAdminKey() {
    clearStoredApiKey("admin");
    setApiKeyInput("");
    setHasApiKey(false);
    setAdminActor(null);
    setAdminAuthError(null);
  }

  if (path === "/quote") {
    return (
      <div className="app-shell">
        <a
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-white focus:px-3 focus:py-2 focus:text-sm focus:font-semibold focus:text-blue-800"
          href="#main-content"
        >
          跳到主内容
        </a>
        <main id="main-content" tabIndex={-1}>
          <QuotePage adminHref={withBasePath("/admin")} />
        </main>
      </div>
    );
  }

  if (!adminActor) {
    return (
      <div className="app-shell">
        <a
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-white focus:px-3 focus:py-2 focus:text-sm focus:font-semibold focus:text-blue-800"
          href="#main-content"
        >
          跳到主内容
        </a>
        <main id="main-content" tabIndex={-1}>
          <AdminAccessGate
            apiKeyInput={apiKeyInput}
            error={adminAuthError}
            hasApiKey={hasApiKey}
            isVerifying={isVerifyingAdminKey}
            onChange={setApiKeyInput}
            onClear={clearAdminKey}
            onSubmit={() => {
              void verifyAdminKey();
            }}
            quoteHref={withBasePath("/quote")}
          />
        </main>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <a
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-white focus:px-3 focus:py-2 focus:text-sm focus:font-semibold focus:text-blue-800"
        href="#main-content"
      >
        跳到主内容
      </a>
      <AdminShell
        actor={adminActor}
        apiKeyInput={apiKeyInput}
        currentPath={path}
        hasApiKey={hasApiKey}
        isVerifying={isVerifyingAdminKey}
        onApiKeyChange={setApiKeyInput}
        onClearKey={clearAdminKey}
        onNavigate={navigate}
        onVerify={() => {
          void verifyAdminKey();
        }}
      >
        {page}
      </AdminShell>
    </div>
  );
}

function AdminShell({
  actor,
  apiKeyInput,
  children,
  currentPath,
  hasApiKey,
  isVerifying,
  onApiKeyChange,
  onClearKey,
  onNavigate,
  onVerify,
}: {
  actor: CurrentActor;
  apiKeyInput: string;
  children: ReactNode;
  currentPath: RoutePath;
  hasApiKey: boolean;
  isVerifying: boolean;
  onApiKeyChange: (value: string) => void;
  onClearKey: () => void;
  onNavigate: (path: RoutePath) => void;
  onVerify: () => void;
}) {
  const currentRoute =
    adminRoutes.find((route) => route.path === currentPath) ?? adminRoutes[0];
  const routesByGroup = adminRoutes.reduce<Record<"workbench" | "settings", typeof adminRoutes>>(
    (groups, route) => {
      groups[route.group].push(route);
      return groups;
    },
    { workbench: [], settings: [] },
  );

  return (
    <div className="admin-shell">
      <aside className="admin-sidebar">
        <div className="border-b border-slate-800 p-5">
          <p className="text-xs font-semibold uppercase tracking-wide text-blue-300">
            Canada Final Mile
          </p>
          <h1 className="mt-2 text-lg font-semibold text-white">报价后台</h1>
          <p className="mt-2 break-all font-mono text-[11px] leading-5 text-slate-400">
            {getApiBaseUrl()}
          </p>
        </div>

        <nav className="grid gap-5 p-3" aria-label="后台导航">
          {(["workbench", "settings"] as const).map((group) => (
            <div key={group}>
              <p className="px-2 py-2 text-xs font-semibold text-slate-500">
                {adminGroupLabels[group]}
              </p>
              <div className="grid gap-1">
                {routesByGroup[group].map((route) => {
                  const isActive = route.path === currentPath;
                  return (
                    <a
                      key={route.path}
                      className={`admin-nav-link ${isActive ? "admin-nav-link-active" : ""}`}
                      href={withBasePath(route.path)}
                      aria-current={isActive ? "page" : undefined}
                      onClick={(event) => {
                        event.preventDefault();
                        onNavigate(route.path);
                      }}
                    >
                      <span>{route.label}</span>
                      <span>{route.description}</span>
                    </a>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>
      </aside>

      <div className="min-w-0">
        <header className="admin-topbar">
          <div className="min-w-0">
            <p className="text-xs font-semibold text-slate-500">
              {adminGroupLabels[currentRoute.group]}
            </p>
            <h2 className="mt-1 text-xl font-semibold text-slate-950">
              {currentRoute.label}
            </h2>
          </div>

          <div className="flex flex-col gap-3 lg:items-end">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1 font-semibold text-slate-800">
                {actor.name}
              </span>
              <span className="rounded-md bg-blue-50 px-2.5 py-1 font-semibold text-blue-800">
                {actor.role}
              </span>
            </div>
            <form
              className="flex flex-col gap-2 sm:flex-row sm:items-end"
              onSubmit={(event) => {
                event.preventDefault();
                onVerify();
              }}
            >
              <label className="min-w-64">
                <span className="field-label text-xs">后台 X-API-Key</span>
                <input
                  className="field-input min-h-10 py-1 text-sm"
                  type="password"
                  value={apiKeyInput}
                  onChange={(event) => onApiKeyChange(event.target.value)}
                  placeholder={hasApiKey ? "后台 Key 已保存" : "输入后台 API Key"}
                  autoComplete="off"
                />
              </label>
              <button className="btn-primary min-h-10 px-3 py-1" type="submit">
                {isVerifying ? "验证中..." : "验证"}
              </button>
              <button className="btn-secondary min-h-10 px-3 py-1" type="button" onClick={onClearKey}>
                清除
              </button>
            </form>
          </div>
        </header>

        <main id="main-content" tabIndex={-1} className="min-w-0">
          {children}
        </main>
      </div>
    </div>
  );
}

function normalizePath(pathname: string): RoutePath {
  const strippedPath = stripBasePath(pathname);
  if (strippedPath === "/manual-tasks") {
    return "/manual-tasks";
  }
  if (strippedPath === "/learning-candidates") {
    return "/learning-candidates";
  }
  if (strippedPath === "/admin") {
    return "/admin";
  }
  if (strippedPath === "/ai-quote") {
    return "/ai-quote";
  }
  if (strippedPath === "/audit") {
    return "/audit";
  }
  if (strippedPath === "/settings/ai") {
    return "/settings/ai";
  }
  if (strippedPath === "/settings/quote") {
    return "/settings/quote";
  }
  if (strippedPath === "/settings/pricing") {
    return "/settings/pricing";
  }
  if (strippedPath === "/settings/search") {
    return "/settings/search";
  }
  if (strippedPath === "/settings/wecom" || strippedPath === "/settings/email") {
    return "/settings/email";
  }
  return "/quote";
}

function normalizeBasePath(basePath: string): string {
  if (!basePath || basePath === "/") {
    return "";
  }
  return `/${basePath.replace(/^\/+|\/+$/g, "")}`;
}

function stripBasePath(pathname: string): string {
  if (!APP_BASE_PATH) {
    return pathname;
  }
  if (pathname === APP_BASE_PATH || pathname === `${APP_BASE_PATH}/`) {
    return "/";
  }
  if (pathname.startsWith(`${APP_BASE_PATH}/`)) {
    return pathname.slice(APP_BASE_PATH.length) || "/";
  }
  return pathname;
}

function withBasePath(routePath: RoutePath): string {
  return `${APP_BASE_PATH}${routePath}`;
}

function AdminAccessGate({
  apiKeyInput,
  error,
  hasApiKey,
  isVerifying,
  onChange,
  onClear,
  onSubmit,
  quoteHref,
}: {
  apiKeyInput: string;
  error: string | null;
  hasApiKey: boolean;
  isVerifying: boolean;
  onChange: (value: string) => void;
  onClear: () => void;
  onSubmit: () => void;
  quoteHref: string;
}) {
  return (
    <div className="min-h-dvh bg-slate-950 px-4 py-10 text-slate-100">
      <section className="mx-auto grid max-w-2xl gap-6 rounded-md border border-slate-700 bg-slate-900 p-6 shadow-2xl sm:p-8">
        <div>
          <p className="text-sm font-semibold text-blue-300">Backoffice Access</p>
          <h1 className="mt-2 text-2xl font-semibold text-white">
            后台管理登录
          </h1>
          <p className="mt-3 text-sm leading-6 text-slate-300">
            后台页面需要先验证后台 Key。请使用 admin、operator 或 viewer 角色的 Key；
            前台报价 sales Key 不能进入后台。
          </p>
        </div>

        {error && (
          <div
            className="rounded-md border border-red-300/50 bg-red-500/10 px-4 py-3 text-sm leading-6 text-red-100"
            role="alert"
          >
            {error}
          </div>
        )}

        <form
          className="grid gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit();
          }}
        >
          <label>
            <span className="field-label text-slate-200">后台 X-API-Key</span>
            <input
              className="field-input border-slate-600 bg-slate-950 text-slate-100 placeholder:text-slate-500"
              type="password"
              value={apiKeyInput}
              onChange={(event) => onChange(event.target.value)}
              placeholder={hasApiKey ? "后台 Key 已保存，点击验证进入" : "输入后台 API Key"}
              autoComplete="off"
              autoFocus
            />
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <button className="btn-primary" type="submit" disabled={isVerifying}>
              {isVerifying ? "正在验证..." : "验证并进入后台"}
            </button>
            <button className="btn-secondary bg-slate-800 text-slate-100" type="button" onClick={onClear}>
              清除
            </button>
          </div>
        </form>

        <div className="flex flex-wrap gap-3 border-t border-slate-800 pt-5">
          <a className="btn-secondary bg-slate-800 text-slate-100" href={quoteHref}>
            返回前台报价
          </a>
        </div>
      </section>
    </div>
  );
}

function AdminHomePage({ navigate }: { navigate: (path: RoutePath) => void }) {
  const [summary, setSummary] = useState<QuoteErrorSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  useEffect(() => {
    async function loadSummary() {
      try {
        setSummary(await getQuoteErrorSummary(12));
        setSummaryError(null);
      } catch (caught) {
        setSummaryError(caught instanceof Error ? caught.message : "报价错误总览加载失败");
      }
    }

    void loadSummary();
  }, []);

  const shortcuts: Array<{ path: RoutePath; title: string; value: string; tone?: "neutral" | "warn" | "danger" }> = [
    { path: "/manual-tasks", title: "待处理任务", value: String(summary?.pending_manual_task_count ?? "-"), tone: "warn" },
    { path: "/learning-candidates", title: "Hermes 待审", value: String(summary?.pending_learning_candidate_count ?? "-"), tone: "warn" },
    { path: "/audit", title: "审计查询", value: "quote_id" },
    { path: "/settings/quote", title: "报价配置", value: "前台字段" },
    { path: "/settings/pricing", title: "价格配置", value: "Zone / Fuel" },
    { path: "/settings/ai", title: "AI 模型", value: "字段提取" },
    { path: "/settings/search", title: "搜索 API", value: "地址确认" },
    { path: "/settings/email", title: "邮件通知", value: "通知" },
  ];
  const quoteHistoryRows =
    summary?.recent_audits?.length
      ? summary.recent_audits
      : (summary?.recent_manual_audits ?? []);

  return (
    <div className="mx-auto flex max-w-[1500px] flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
      <section className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <div className="panel p-5">
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div>
              <p className="text-sm font-semibold text-blue-800">运营控制台</p>
              <h1 className="mt-1 text-2xl font-semibold text-slate-950">
                加拿大尾端报价后台仪表盘
              </h1>
              <p className="mt-2 text-sm leading-6 text-slate-600">
                报价历史、异常报价、人工任务和学习库只在后台展示，前台报价页保持面向销售/客户的简洁工作台。
              </p>
            </div>
            <button className="btn-primary" type="button" onClick={() => navigate("/manual-tasks")}>
              处理人工任务
            </button>
          </div>
        {summaryError && (
          <div className="mt-4 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900">
            {summaryError}
          </div>
        )}

          <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <AdminMetric label="近24h 审计" value={summary?.daily_total_audit_count} />
          <AdminMetric label="近24h 成功" value={summary?.daily_successful_quote_count} />
          <AdminMetric label="近24h 需人工" value={summary?.daily_manual_required_audit_count} tone="warn" />
          <AdminMetric label="近24h 待处理" value={summary?.daily_pending_manual_task_count} tone="warn" />
          <AdminMetric label="近24h AI 问题" value={summary?.daily_ai_issue_task_count} tone="danger" />
          <AdminMetric label="累计规则未完成" value={summary?.manual_required_audit_count} tone="warn" />
          <AdminMetric label="Hermes 待审" value={summary?.pending_learning_candidate_count} tone="warn" />
          <AdminMetric label="学习规则" value={summary?.active_learning_rule_count} />
          <AdminMetric label="学习复用" value={summary?.learning_rule_usage_count} />
        </div>
        </div>

        <aside className="panel p-5">
          <div className="flex items-center justify-between gap-3">
            <h2 className="section-title">快速入口</h2>
            <span className="text-xs font-medium text-slate-500">{summary?.window_label ?? "近24小时"}</span>
          </div>
          <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
            {shortcuts.map((shortcut) => (
              <button
                key={shortcut.path}
                className="grid min-h-14 grid-cols-[1fr_auto] items-center gap-3 rounded-md border border-slate-200 bg-white px-3 py-2 text-left transition hover:border-blue-300 hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-blue-700"
                type="button"
                onClick={() => navigate(shortcut.path)}
              >
                <span className="text-sm font-semibold text-slate-950">{shortcut.title}</span>
                <span className={`rounded-md px-2 py-1 text-xs font-semibold ${shortcut.tone === "warn" ? "bg-amber-50 text-amber-900" : shortcut.tone === "danger" ? "bg-red-50 text-red-900" : "bg-slate-100 text-slate-700"}`}>
                  {shortcut.value}
                </span>
              </button>
            ))}
          </div>
        </aside>
      </section>

      <section className="panel overflow-hidden">
        <div className="flex flex-col gap-3 border-b border-slate-200 px-5 py-4 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-sm font-semibold text-blue-800">Quote History</p>
            <h2 className="mt-1 text-lg font-semibold text-slate-950">报价历史</h2>
          </div>
          <button className="btn-secondary min-h-10 px-3 py-1" type="button" onClick={() => navigate("/audit")}>
            按 quote_id 查审计
          </button>
        </div>
        {quoteHistoryRows.length ? (
          <div className="overflow-x-auto">
            <div className="min-w-[920px]">
              <div className="grid grid-cols-[1.15fr_1fr_0.7fr_0.7fr_0.8fr_0.8fr_0.9fr] gap-3 bg-slate-50 px-5 py-3 text-xs font-semibold text-slate-500">
                <span>报价 ID</span>
                <span>目的地</span>
                <span>来源</span>
                <span>Zone</span>
                <span>托数</span>
                <span>金额</span>
                <span>状态 / 时间</span>
              </div>
              {quoteHistoryRows.slice(0, 10).map((audit) => (
                <button
                  key={audit.id}
                  className="grid w-full grid-cols-[1.15fr_1fr_0.7fr_0.7fr_0.8fr_0.8fr_0.9fr] gap-3 border-t border-slate-100 px-5 py-3 text-left text-sm transition hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-blue-700"
                  type="button"
                  onClick={() => navigate("/audit")}
                >
                  <span className="break-words font-mono font-semibold text-slate-950">{audit.quote_id}</span>
                  <span className="text-slate-700">
                    {[audit.city, audit.province, audit.postal_prefix || audit.postal_code].filter(Boolean).join(" / ") || "未返回"}
                  </span>
                  <span className="text-slate-700">{formatAuditSource(audit.source_type)}</span>
                  <span className="font-mono text-slate-700">{audit.zone ?? "-"}</span>
                  <span className="font-mono text-slate-700">{audit.billing_pallets ?? "-"}</span>
                  <span className="font-mono font-semibold text-slate-950">{formatMoneyValue(audit.total_price_usd)}</span>
                  <span>
                    <span
                      className={`inline-flex rounded-md px-2 py-1 text-xs font-semibold ${
                        audit.manual_review_required
                          ? "bg-amber-50 text-amber-900"
                          : "bg-emerald-50 text-emerald-800"
                      }`}
                    >
                      {audit.manual_review_required ? "需人工" : "已报价"}
                    </span>
                    <span className="mt-1 block text-xs text-slate-500">
                      {audit.created_at ? formatDateTime(audit.created_at) : "无时间"}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="px-5 py-6 text-sm text-slate-600">
            暂无报价历史。产生报价后，这里会显示最近审计记录。
          </div>
        )}
      </section>

      <section className="grid gap-5 xl:grid-cols-[0.85fr_1.15fr_0.9fr]">
        <div className="panel p-5">
          <h2 className="section-title">高频问题</h2>
          <div className="mt-3 flex flex-wrap gap-2">
              {summary?.daily_risk_tag_counts?.length ? (
                summary.daily_risk_tag_counts.map((item) => (
                  <span
                    key={item.tag}
                    className="rounded-md border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-900"
                  >
                    {item.label || item.tag} × {item.count}
                  </span>
                ))
              ) : (
                <span className="text-sm text-slate-500">暂无风险标签</span>
              )}
            </div>
          <div className="mt-5 grid gap-2 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
              <div className="flex justify-between gap-3">
                <span>累计审计</span>
                <strong className="text-slate-950">{summary?.total_audit_count ?? "-"}</strong>
              </div>
              <div className="flex justify-between gap-3">
                <span>累计成功报价</span>
                <strong className="text-slate-950">{summary?.successful_quote_count ?? "-"}</strong>
              </div>
              <div className="flex justify-between gap-3">
                <span>累计规则未完成</span>
                <strong className="text-slate-950">{summary?.manual_required_audit_count ?? "-"}</strong>
              </div>
              <div className="flex justify-between gap-3">
                <span>当前待处理任务</span>
                <strong className="text-slate-950">{summary?.pending_manual_task_count ?? "-"}</strong>
              </div>
              <div className="flex justify-between gap-3">
                <span>活跃学习规则</span>
                <strong className="text-slate-950">{summary?.active_learning_rule_count ?? "-"}</strong>
              </div>
              <div className="flex justify-between gap-3">
                <span>累计学习复用</span>
                <strong className="text-slate-950">{summary?.learning_rule_usage_count ?? "-"}</strong>
              </div>
            </div>
        </div>

        <div className="panel p-5">
          <div className="flex items-center justify-between gap-3">
            <h2 className="section-title">最近问题</h2>
            <button className="btn-secondary min-h-10 px-3 py-1" type="button" onClick={() => navigate("/manual-tasks")}>
              全部任务
            </button>
          </div>
          <div className="mt-3 grid gap-2">
              {summary?.recent_manual_tasks.length ? (
                summary.recent_manual_tasks.slice(0, 5).map((task) => (
                  <button
                    key={task.id}
                    className="rounded-md border border-slate-200 bg-white px-3 py-2 text-left text-sm hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-700"
                    type="button"
                    onClick={() => navigate("/manual-tasks")}
                  >
                    <span className="font-semibold text-slate-950">{task.quote_id}</span>
                    <span className="ml-2 rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-700">{task.status}</span>
                    <span className="mt-1 block line-clamp-2 text-slate-600">{task.reason_zh || task.reason}</span>
                    {task.risk_tag_labels?.length ? (
                      <span className="mt-2 block text-xs text-amber-700">
                        {task.risk_tag_labels.slice(0, 3).join("、")}
                      </span>
                    ) : null}
                  </button>
                ))
              ) : (
                <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-4 text-sm text-slate-600">
                  暂无待展示的问题任务。
                </div>
              )}
            </div>
        </div>

        <div className="panel p-5">
          <h2 className="section-title">学习库</h2>
          <div className="mt-3 grid gap-2">
                {summary?.recent_learning_rules?.length ? (
                  summary.recent_learning_rules.slice(0, 4).map((rule) => (
                    <div key={rule.id} className="rounded-md border border-emerald-100 bg-emerald-50 px-3 py-2 text-sm">
                      <span className="font-semibold text-emerald-950">
                        {rule.postal_prefix || rule.postal_code || "未知邮编"} / {rule.city || "未知城市"} / {rule.billing_pallets}托
                      </span>
                      <span className="ml-2 rounded bg-white px-2 py-0.5 text-xs text-emerald-800">
                        复用 {rule.usage_count} 次
                      </span>
                      <span className="mt-1 block text-emerald-900">
                        {rule.total_price_usd ? `$${Number(rule.total_price_usd).toFixed(2)} USD` : "金额待确认"}
                        {rule.zone !== null ? ` / Zone ${rule.zone}` : ""}
                      </span>
                    </div>
                  ))
                ) : (
                  <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-4 text-sm text-slate-600">
                    暂无学习记录
                  </div>
                )}
              </div>
        </div>
      </section>
    </div>
  );
}

function AdminMetric({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: number | undefined;
  tone?: "neutral" | "warn" | "danger";
}) {
  const toneClass =
    tone === "danger"
      ? "border-red-200 bg-red-50 text-red-900"
      : tone === "warn"
        ? "border-amber-200 bg-amber-50 text-amber-900"
        : "border-slate-200 bg-slate-50 text-slate-900";
  return (
    <div className={`rounded-md border p-4 ${toneClass}`}>
      <p className="text-xs font-semibold">{label}</p>
      <p className="mt-2 text-2xl font-semibold tabular-nums">{value ?? "-"}</p>
    </div>
  );
}

function formatAuditSource(value: string): string {
  const labels: Record<string, string> = {
    zone_matrix: "Zone 矩阵",
    manual_required: "人工复核",
    learned_manual_quote: "学习库",
    postal_code: "邮编",
    fsa: "FSA",
    city: "城市",
  };
  return labels[value] || value || "-";
}

function formatMoneyValue(value: string | number | null): string {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? `USD ${numberValue.toFixed(2)}` : String(value);
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
