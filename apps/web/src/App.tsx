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
  | "/ai-quote"
  | "/manual-tasks"
  | "/audit"
  | "/settings/quote"
  | "/settings/ai"
  | "/settings/wecom";
const APP_BASE_PATH = normalizeBasePath(import.meta.env.VITE_APP_BASE_PATH || "/");

const routes: Array<{ path: RoutePath; label: string; description: string }> = [
  { path: "/quote", label: "AI 报价工作台", description: "粘贴识别" },
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
  const [apiKeyInput, setApiKeyInput] = useState(() => getStoredApiKey());
  const [hasApiKey, setHasApiKey] = useState(() => Boolean(getStoredApiKey()));

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
    return <QuotePage />;
  }, [path]);

  function navigate(nextPath: RoutePath) {
    if (nextPath === path) {
      return;
    }
    window.history.pushState({}, "", withBasePath(nextPath));
    setPath(nextPath);
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
          </div>

          <div className="flex flex-col gap-3 lg:items-end">
            <form
              className="flex flex-wrap items-end gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                setStoredApiKey(apiKeyInput);
                setHasApiKey(Boolean(apiKeyInput.trim()));
              }}
            >
              <label className="min-w-60">
                <span className="field-label text-xs">X-API-Key</span>
                <input
                  className="field-input min-h-10 py-1 text-sm"
                  type="password"
                  value={apiKeyInput}
                  onChange={(event) => setApiKeyInput(event.target.value)}
                  placeholder={hasApiKey ? "已保存" : "输入 API Key"}
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
                  clearStoredApiKey();
                  setApiKeyInput("");
                  setHasApiKey(false);
                }}
              >
                清除
              </button>
            </form>

            <nav className="flex flex-wrap justify-end gap-2" aria-label="主导航">
            {routes.map((route) => {
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
