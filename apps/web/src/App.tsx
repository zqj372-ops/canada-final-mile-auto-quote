import { useEffect, useMemo, useState } from "react";
import {
  clearStoredApiKey,
  getApiBaseUrl,
  getBackofficeActor,
  getStoredApiKey,
  setStoredApiKey,
  type CurrentActor,
} from "./api/client";
import AIQuotePage from "./pages/AIQuotePage";
import AISettingsPage from "./pages/AISettingsPage";
import AuditPage from "./pages/AuditPage";
import ManualTasksPage from "./pages/ManualTasksPage";
import QuotePage from "./pages/QuotePage";
import QuoteSettingsPage from "./pages/QuoteSettingsPage";
import SearchSettingsPage from "./pages/SearchSettingsPage";
import WeComSettingsPage from "./pages/WeComSettingsPage";

type RoutePath =
  | "/quote"
  | "/admin"
  | "/ai-quote"
  | "/manual-tasks"
  | "/audit"
  | "/settings/quote"
  | "/settings/ai"
  | "/settings/search"
  | "/settings/wecom";
const APP_BASE_PATH = normalizeBasePath(import.meta.env.VITE_APP_BASE_PATH || "/");

const adminRoutes: Array<{ path: RoutePath; label: string; description: string }> = [
  { path: "/admin", label: "后台首页", description: "总览" },
  { path: "/quote", label: "前台报价", description: "前台" },
  { path: "/ai-quote", label: "AI 自动报价", description: "模型提取" },
  { path: "/manual-tasks", label: "人工任务", description: "复核" },
  { path: "/audit", label: "审计查询", description: "日志" },
  { path: "/settings/quote", label: "报价配置", description: "后台" },
  { path: "/settings/ai", label: "AI 配置", description: "模型" },
  { path: "/settings/search", label: "搜索配置", description: "Tavily" },
  { path: "/settings/wecom", label: "企业微信配置", description: "机器人" },
];

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
    if (path === "/audit") {
      return <AuditPage />;
    }
    if (path === "/settings/ai") {
      return <AISettingsPage />;
    }
    if (path === "/settings/quote") {
      return <QuoteSettingsPage />;
    }
    if (path === "/settings/search") {
      return <SearchSettingsPage />;
    }
    if (path === "/settings/wecom") {
      return <WeComSettingsPage />;
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

      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-4 py-4 sm:px-6 lg:flex-row lg:items-center lg:justify-between lg:px-8">
          <div>
            <p className="text-sm font-semibold text-slate-950">
              Canada Final Mile
            </p>
            <p className="mt-1 text-sm text-slate-600">
              API: <span className="font-mono text-xs">{getApiBaseUrl()}</span>
            </p>
            <p className="mt-1 text-xs text-slate-500">
              后台管理使用独立 Key；前台报价 Key 请在 `/quote` 页面保存。
            </p>
          </div>

          <div className="flex flex-col gap-3 lg:items-end">
            <form
              className="flex flex-wrap items-end gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                void verifyAdminKey();
              }}
            >
              <label className="min-w-60">
                <span className="field-label text-xs">后台 X-API-Key</span>
                <input
                  className="field-input min-h-10 py-1 text-sm"
                  type="password"
                  value={apiKeyInput}
                  onChange={(event) => setApiKeyInput(event.target.value)}
                  placeholder={hasApiKey ? "后台 Key 已保存" : "输入后台 API Key"}
                  autoComplete="off"
                />
              </label>
              <button className="btn-primary min-h-10 px-3 py-1" type="submit">
                {isVerifyingAdminKey ? "验证中..." : "验证"}
              </button>
              <button
                className="btn-secondary min-h-10 px-3 py-1"
                type="button"
                onClick={clearAdminKey}
              >
                清除
              </button>
            </form>
            <p className="text-xs text-slate-500">
              已验证：{adminActor.name} / {adminActor.role}
            </p>

            <nav className="flex flex-wrap justify-end gap-2" aria-label="后台导航">
            {adminRoutes.map((route) => {
              const isActive = route.path === path;
              return (
                <a
                  key={route.path}
                  className={`min-h-11 rounded-md px-4 py-2 text-sm font-semibold transition focus:outline-none focus:ring-2 focus:ring-blue-700 focus:ring-offset-2 ${
                    isActive
                      ? "bg-blue-700 text-white"
                      : "border border-slate-300 bg-white text-slate-800 hover:bg-slate-50"
                  }`}
                  href={withBasePath(route.path)}
                  aria-current={isActive ? "page" : undefined}
                  onClick={(event) => {
                    event.preventDefault();
                    navigate(route.path);
                  }}
                >
                  <span>{route.label}</span>
                  <span
                    className={`ml-2 text-xs font-medium ${
                      isActive ? "text-blue-100" : "text-slate-500"
                    }`}
                  >
                    {route.description}
                  </span>
                </a>
              );
            })}
            </nav>
          </div>
        </div>
      </header>

      <main id="main-content" tabIndex={-1}>
        {page}
      </main>
    </div>
  );
}

function normalizePath(pathname: string): RoutePath {
  const strippedPath = stripBasePath(pathname);
  if (strippedPath === "/manual-tasks") {
    return "/manual-tasks";
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
  if (strippedPath === "/settings/search") {
    return "/settings/search";
  }
  if (strippedPath === "/settings/wecom") {
    return "/settings/wecom";
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
  const shortcuts: Array<{ path: RoutePath; title: string; body: string }> = [
    { path: "/manual-tasks", title: "人工任务", body: "查看和处理需要人工复核的报价。" },
    { path: "/audit", title: "审计查询", body: "按 quote_id 查看报价请求和结果。" },
    { path: "/settings/quote", title: "报价配置", body: "可视化维护前台字段、风险阈值和报价话术。" },
    { path: "/settings/ai", title: "AI 配置", body: "维护字段提取和话术模型配置。" },
    { path: "/settings/search", title: "搜索配置", body: "维护 Tavily 等搜索 API Key，用于地址和行情参考。" },
    { path: "/settings/wecom", title: "企业微信配置", body: "维护通知机器人和默认用途。" },
    { path: "/quote", title: "进入前台", body: "打开销售使用的 AI 报价工作台。" },
  ];

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
      <header>
        <p className="text-sm font-medium text-blue-800">Admin</p>
        <h1 className="mt-1 text-2xl font-semibold text-slate-950">
          加拿大尾端报价后台
        </h1>
      </header>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {shortcuts.map((shortcut) => (
          <button
            key={shortcut.path}
            className="panel min-h-36 p-5 text-left transition hover:border-blue-300 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-blue-700 focus:ring-offset-2"
            type="button"
            onClick={() => navigate(shortcut.path)}
          >
            <h2 className="text-lg font-semibold text-slate-950">{shortcut.title}</h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">{shortcut.body}</p>
          </button>
        ))}
      </div>
    </div>
  );
}
