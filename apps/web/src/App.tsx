import { useEffect, useMemo, useState } from "react";
import { clearStoredApiKey, getApiBaseUrl, getStoredApiKey, setStoredApiKey } from "./api/client";
import AIQuotePage from "./pages/AIQuotePage";
import AISettingsPage from "./pages/AISettingsPage";
import AuditPage from "./pages/AuditPage";
import ManualTasksPage from "./pages/ManualTasksPage";
import QuotePage from "./pages/QuotePage";
import QuoteSettingsPage from "./pages/QuoteSettingsPage";
import WeComSettingsPage from "./pages/WeComSettingsPage";

type RoutePath =
  | "/quote"
  | "/admin"
  | "/ai-quote"
  | "/manual-tasks"
  | "/audit"
  | "/settings/quote"
  | "/settings/ai"
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
  { path: "/settings/wecom", label: "企业微信配置", description: "机器人" },
];

export default function App() {
  const [path, setPath] = useState<RoutePath>(() =>
    normalizePath(window.location.pathname),
  );
  const [apiKeyInput, setApiKeyInput] = useState(() => getStoredApiKey("admin"));
  const [hasApiKey, setHasApiKey] = useState(() => Boolean(getStoredApiKey("admin")));

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
                setStoredApiKey("admin", apiKeyInput);
                setHasApiKey(Boolean(apiKeyInput.trim()));
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
                保存
              </button>
              <button
                className="btn-secondary min-h-10 px-3 py-1"
                type="button"
                onClick={() => {
                  clearStoredApiKey("admin");
                  setApiKeyInput("");
                  setHasApiKey(false);
                }}
              >
                清除
              </button>
            </form>

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

function AdminHomePage({ navigate }: { navigate: (path: RoutePath) => void }) {
  const shortcuts: Array<{ path: RoutePath; title: string; body: string }> = [
    { path: "/manual-tasks", title: "人工任务", body: "查看和处理需要人工复核的报价。" },
    { path: "/audit", title: "审计查询", body: "按 quote_id 查看报价请求和结果。" },
    { path: "/settings/quote", title: "报价配置", body: "可视化维护前台字段、风险阈值和报价话术。" },
    { path: "/settings/ai", title: "AI 配置", body: "维护字段提取和话术模型配置。" },
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
