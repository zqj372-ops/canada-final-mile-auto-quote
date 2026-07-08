import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  clearStoredAuthToken,
  clearStoredApiKey,
  getApiBaseUrl,
  getBackofficeActor,
  getQuoteErrorSummary,
  getStoredAuthToken,
  login,
  setStoredAuthToken,
  type CurrentActor,
  type QuoteErrorSummary,
} from "./api/client";
import AIQuotePage from "./pages/AIQuotePage";
import AISettingsPage from "./pages/AISettingsPage";
import EmailSettingsPage from "./pages/EmailSettingsPage";
import OperationsWorkbenchPage from "./pages/OperationsWorkbenchPage";
import PricingSettingsPage from "./pages/PricingSettingsPage";
import QuotePage from "./pages/QuotePage";
import QuoteSettingsPage from "./pages/QuoteSettingsPage";
import SearchSettingsPage from "./pages/SearchSettingsPage";
import UserSettingsPage from "./pages/UserSettingsPage";

type RoutePath =
  | "/quote"
  | "/admin"
  | "/ai-quote"
  | "/ops"
  | "/manual-tasks"
  | "/hermes-diagnostics"
  | "/learning-candidates"
  | "/audit"
  | "/settings/quote"
  | "/settings/pricing"
  | "/settings/ai"
  | "/settings/search"
  | "/settings/email"
  | "/settings/users";
const APP_BASE_PATH = normalizeBasePath(import.meta.env.VITE_APP_BASE_PATH || "/");

type AdminRouteGroup =
  | "overview"
  | "core"
  | "manual"
  | "audit"
  | "pricing"
  | "system"
  | "integration";
type AdminIconName =
  | "alert"
  | "bot"
  | "box"
  | "calculator"
  | "dashboard"
  | "file"
  | "link"
  | "mail"
  | "menu"
  | "refresh"
  | "search"
  | "settings"
  | "shield"
  | "truck"
  | "user"
  | "users";

const adminRoutes: Array<{
  path: RoutePath;
  label: string;
  description: string;
  group: AdminRouteGroup;
  icon: AdminIconName;
  adminOnly?: boolean;
}> = [
  { path: "/admin", label: "运营控制台", description: "总览", group: "overview", icon: "dashboard" },
  { path: "/ai-quote", label: "AI 报价", description: "调试", group: "core", icon: "bot" },
  { path: "/quote", label: "销售前台", description: "报价", group: "core", icon: "truck" },
  { path: "/ops", label: "处理工作台", description: "复核/诊断/学习", group: "manual", icon: "user" },
  { path: "/settings/quote", label: "报价规则", description: "前台", group: "pricing", icon: "file" },
  { path: "/settings/pricing", label: "价格矩阵", description: "Zone", group: "pricing", icon: "calculator" },
  { path: "/settings/ai", label: "AI 模型配置", description: "模型", group: "system", icon: "settings" },
  { path: "/settings/search", label: "搜索 API 配置", description: "地址", group: "system", icon: "link" },
  { path: "/settings/email", label: "邮件通知配置", description: "通知", group: "system", icon: "mail" },
  { path: "/settings/users", label: "用户账号", description: "权限", group: "system", icon: "users", adminOnly: true },
];

const adminGroupLabels = {
  overview: "",
  core: "核心业务",
  manual: "人工处理",
  audit: "审计与查询",
  pricing: "价格与报价配置",
  system: "系统配置",
  integration: "系统集成",
} as const;

const adminGroupOrder: AdminRouteGroup[] = [
  "overview",
  "core",
  "manual",
  "audit",
  "pricing",
  "system",
  "integration",
];

export default function App() {
  const [path, setPath] = useState<RoutePath>(() =>
    normalizePath(window.location.pathname),
  );
  const [adminUsername, setAdminUsername] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [adminActor, setAdminActor] = useState<CurrentActor | null>(null);
  const [adminAuthError, setAdminAuthError] = useState<string | null>(null);
  const [isCheckingAdminSession, setIsCheckingAdminSession] = useState(
    () => Boolean(getStoredAuthToken()),
  );
  const [isLoggingInAdmin, setIsLoggingInAdmin] = useState(false);

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
    if (path === "/quote") {
      if (isCheckingAdminSession) {
        setIsCheckingAdminSession(false);
      }
      return;
    }
    if (adminActor) {
      return;
    }
    if (!getStoredAuthToken()) {
      if (isCheckingAdminSession) {
        setIsCheckingAdminSession(false);
      }
      return;
    }
    void restoreAdminSession();
  }, [path, adminActor]);

  const page = useMemo(() => {
    if (path === "/admin") {
      return <AdminHomePage navigate={navigate} />;
    }
    if (path === "/ai-quote") {
      return <AIQuotePage />;
    }
    if (path === "/ops") {
      return <OperationsWorkbenchPage initialTab="manual" />;
    }
    if (path === "/manual-tasks") {
      return <OperationsWorkbenchPage initialTab="manual" />;
    }
    if (path === "/hermes-diagnostics") {
      return <OperationsWorkbenchPage initialTab="diagnostics" />;
    }
    if (path === "/learning-candidates") {
      return <OperationsWorkbenchPage initialTab="hermes" />;
    }
    if (path === "/audit") {
      return <OperationsWorkbenchPage initialTab="audit" />;
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
    if (path === "/settings/users") {
      return <UserSettingsPage />;
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

  async function restoreAdminSession(): Promise<boolean> {
    setAdminAuthError(null);
    if (!getStoredAuthToken()) {
      setAdminActor(null);
      return false;
    }

    setIsCheckingAdminSession(true);
    try {
      const actor = await getBackofficeActor();
      setAdminActor(actor);
      setAdminAuthError(null);
      return true;
    } catch (caught) {
      clearStoredAuthToken();
      setAdminActor(null);
      setAdminAuthError(
        caught instanceof Error ? caught.message : "后台登录已失效，请重新登录。",
      );
      return false;
    } finally {
      setIsCheckingAdminSession(false);
    }
  }

  async function handleAdminLogin(): Promise<void> {
    setAdminAuthError(null);
    if (!adminUsername.trim() || !adminPassword) {
      setAdminAuthError("请输入后台账号和密码。");
      return;
    }

    setIsLoggingInAdmin(true);
    try {
      const response = await login({
        username: adminUsername.trim(),
        password: adminPassword,
      });
      setStoredAuthToken(response.access_token);
      const actor = await getBackofficeActor();
      setAdminActor(actor);
      setAdminPassword("");
      setAdminAuthError(null);
    } catch (caught) {
      clearStoredAuthToken();
      setAdminActor(null);
      setAdminAuthError(caught instanceof Error ? caught.message : "后台登录失败");
    } finally {
      setIsLoggingInAdmin(false);
    }
  }

  function logoutAdmin() {
    clearStoredAuthToken();
    clearStoredApiKey("admin");
    setAdminActor(null);
    setAdminPassword("");
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
            password={adminPassword}
            username={adminUsername}
            error={adminAuthError}
            isChecking={isCheckingAdminSession}
            isLoggingIn={isLoggingInAdmin}
            onPasswordChange={setAdminPassword}
            onSubmit={() => {
              void handleAdminLogin();
            }}
            onUsernameChange={setAdminUsername}
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
        currentPath={path}
        onLogout={logoutAdmin}
        onNavigate={navigate}
      >
        {page}
      </AdminShell>
    </div>
  );
}

function AdminShell({
  actor,
  children,
  currentPath,
  onLogout,
  onNavigate,
}: {
  actor: CurrentActor;
  children: ReactNode;
  currentPath: RoutePath;
  onLogout: () => void;
  onNavigate: (path: RoutePath) => void;
}) {
  const currentRoute =
    adminRoutes.find((route) => route.path === currentPath)
    ?? (isOperationsPath(currentPath) ? adminRoutes.find((route) => route.path === "/ops") : undefined)
    ?? adminRoutes[0];
  const visibleRoutes = adminRoutes.filter((route) => !route.adminOnly || actor.role === "admin");
  const routesByGroup = visibleRoutes.reduce<Record<AdminRouteGroup, typeof adminRoutes>>(
    (groups, route) => {
      groups[route.group].push(route);
      return groups;
    },
    {
      audit: [],
      core: [],
      integration: [],
      manual: [],
      overview: [],
      pricing: [],
      system: [],
    },
  );

  return (
    <div className="admin-shell">
      <aside className="admin-sidebar">
        <div className="admin-brand">
          <div className="admin-brand-mark">
            <AdminIcon name="truck" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-slate-950">Canada Final Mile</p>
            <p className="mt-1 text-xs font-medium text-slate-500">AI 报价系统</p>
          </div>
        </div>

        <nav className="admin-nav" aria-label="后台导航">
          {adminGroupOrder.map((group) =>
            routesByGroup[group].length ? (
            <div key={group}>
              {adminGroupLabels[group] && (
                <p className="admin-nav-group">
                  {adminGroupLabels[group]}
                </p>
              )}
              <div className="grid gap-1">
                {routesByGroup[group].map((route) => {
                  const isActive = route.path === currentPath || (route.path === "/ops" && isOperationsPath(currentPath));
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
                      <AdminIcon name={route.icon} />
                      <span className="min-w-0 truncate">{route.label}</span>
                    </a>
                  );
                })}
              </div>
            </div>
            ) : null,
          )}
        </nav>

        <div className="admin-sidebar-footer">
          <div className="admin-avatar">{actor.name.slice(0, 1).toUpperCase()}</div>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-slate-950">{actor.name}</p>
            <p className="text-xs text-slate-500">{roleLabel(actor.role)}</p>
          </div>
        </div>
      </aside>

      <div className="admin-shell-main">
        <header className="admin-topbar">
          <div className="admin-topbar-title">
            <button className="admin-icon-button" type="button" aria-label="菜单">
              <AdminIcon name="menu" />
            </button>
            <div className="min-w-0">
              <h2>{currentRoute.label}</h2>
              <p>{currentRoute.description}</p>
            </div>
          </div>

          <div className="admin-topbar-actions">
            <label className="admin-search-box">
              <AdminIcon name="search" />
              <input placeholder="全局搜索（报价ID/地址/运单号）" />
              <span>Ctrl K</span>
            </label>
            <button className="btn-primary min-h-10 px-3 py-1" type="button" onClick={() => onNavigate("/ops")}>
              <AdminIcon name="user" />
              处理工作台
            </button>
            <span className="admin-role-chip">
              {roleLabel(actor.role)}
            </span>
            <span className="admin-user-pill">
              <span className="admin-avatar admin-avatar-small">{actor.name.slice(0, 1).toUpperCase()}</span>
              {actor.name}
            </span>
            <button className="admin-icon-button" type="button" onClick={onLogout} aria-label="退出登录">
              <AdminIcon name="shield" />
            </button>
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
  if (strippedPath === "/hermes-diagnostics") {
    return "/hermes-diagnostics";
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
  if (strippedPath === "/ops") {
    return "/ops";
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
  if (strippedPath === "/settings/users") {
    return "/settings/users";
  }
  if (strippedPath === "/settings/wecom" || strippedPath === "/settings/email") {
    return "/settings/email";
  }
  return "/quote";
}

function isOperationsPath(path: RoutePath): boolean {
  return (
    path === "/ops" ||
    path === "/manual-tasks" ||
    path === "/hermes-diagnostics" ||
    path === "/learning-candidates" ||
    path === "/audit"
  );
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
  error,
  isChecking,
  isLoggingIn,
  onPasswordChange,
  onSubmit,
  onUsernameChange,
  password,
  quoteHref,
  username,
}: {
  error: string | null;
  isChecking: boolean;
  isLoggingIn: boolean;
  onPasswordChange: (value: string) => void;
  onSubmit: () => void;
  onUsernameChange: (value: string) => void;
  password: string;
  quoteHref: string;
  username: string;
}) {
  return (
    <div className="admin-login-screen px-4 py-8 sm:px-6">
      <section className="mx-auto grid max-w-5xl overflow-hidden rounded-lg border border-slate-200 bg-white shadow-xl lg:grid-cols-[0.92fr_1.08fr]">
        <div className="admin-login-visual">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-teal-700 text-sm font-black text-white">
              CFM
            </div>
            <div>
              <p className="text-sm font-semibold text-slate-950">Canada Final Mile</p>
              <p className="text-xs font-medium text-slate-500">Quote Operations</p>
            </div>
          </div>
          <div className="mt-10 max-w-md">
            <p className="admin-eyebrow">Backoffice</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-normal text-slate-950">
              后台运营控制台
            </h1>
            <p className="mt-4 text-sm leading-6 text-slate-600">
              使用账号登录后，可处理人工任务、查看 Hermes 诊断建议、审核学习候选、查询审计记录，并维护报价、价格、AI、搜索和邮件配置。
            </p>
          </div>
          <div className="mt-10 grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
            <LoginFeature label="人工复核" value="任务队列" tone="amber" />
            <LoginFeature label="配置中心" value="报价/AI/通知" tone="indigo" />
            <LoginFeature label="权限管理" value="用户账号" tone="teal" />
          </div>
        </div>

        <form
          className="grid content-center gap-5 p-6 sm:p-8"
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit();
          }}
        >
          <div>
            <p className="admin-eyebrow">Account Login</p>
            <h2 className="mt-2 text-2xl font-semibold text-slate-950">
              后台账号登录
            </h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              管理员、运营和查看者角色可以进入后台；销售账号只进入前台报价。
            </p>
          </div>

          {error && (
            <div
              className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm leading-6 text-red-900"
              role="alert"
            >
              {error}
            </div>
          )}

          <label>
            <span className="field-label">账号</span>
            <input
              className="field-input"
              value={username}
              onChange={(event) => onUsernameChange(event.target.value)}
              placeholder="admin@example.com"
              autoComplete="username"
              autoFocus
            />
          </label>
          <label>
            <span className="field-label">密码</span>
            <input
              className="field-input"
              type="password"
              value={password}
              onChange={(event) => onPasswordChange(event.target.value)}
              placeholder="输入密码"
              autoComplete="current-password"
            />
          </label>
          <button className="btn-primary" type="submit" disabled={isLoggingIn || isChecking}>
            {isChecking ? "正在恢复会话..." : isLoggingIn ? "登录中..." : "登录后台"}
          </button>
          <a className="btn-secondary" href={quoteHref}>
            打开销售前台
          </a>
        </form>
      </section>
    </div>
  );
}

function LoginFeature({
  label,
  tone,
  value,
}: {
  label: string;
  tone: "amber" | "indigo" | "teal";
  value: string;
}) {
  const toneClass = {
    amber: "border-amber-200 bg-amber-50 text-amber-900",
    indigo: "border-indigo-200 bg-indigo-50 text-indigo-900",
    teal: "border-teal-200 bg-teal-50 text-teal-900",
  }[tone];
  return (
    <div className={`rounded-lg border p-4 ${toneClass}`}>
      <p className="text-xs font-semibold uppercase tracking-wide">{label}</p>
      <p className="mt-2 text-sm font-semibold">{value}</p>
    </div>
  );
}

function AdminIcon({ name }: { name: AdminIconName }) {
  const paths: Record<AdminIconName, ReactNode> = {
    alert: (
      <>
        <path d="M10 3 2.7 16.2a1.5 1.5 0 0 0 1.3 2.3h12a1.5 1.5 0 0 0 1.3-2.3L10 3Z" />
        <path d="M10 8v4" />
        <path d="M10 15h.01" />
      </>
    ),
    bot: (
      <>
        <path d="M6 8h8a3 3 0 0 1 3 3v4a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3v-4a3 3 0 0 1 3-3Z" />
        <path d="M10 8V4" />
        <path d="M7.5 12h.01" />
        <path d="M12.5 12h.01" />
        <path d="M8 15h4" />
      </>
    ),
    box: (
      <>
        <path d="m3 7 7-4 7 4-7 4-7-4Z" />
        <path d="M3 7v7l7 4 7-4V7" />
        <path d="M10 11v7" />
      </>
    ),
    calculator: (
      <>
        <rect x="5" y="3" width="10" height="14" rx="2" />
        <path d="M7.5 6.5h5" />
        <path d="M8 10h.01M10 10h.01M12 10h.01M8 13h.01M10 13h.01M12 13h.01" />
      </>
    ),
    dashboard: (
      <>
        <path d="M3 10.5 10 4l7 6.5" />
        <path d="M5 9.5V17h10V9.5" />
        <path d="M8 17v-4h4v4" />
      </>
    ),
    file: (
      <>
        <path d="M6 3h6l4 4v10H6V3Z" />
        <path d="M12 3v4h4" />
        <path d="M8 11h5M8 14h4" />
      </>
    ),
    link: (
      <>
        <path d="M8.5 12.5 11.5 9.5" />
        <path d="M7.5 9.5 6.4 10.6a3 3 0 0 0 4.2 4.2l1.1-1.1" />
        <path d="m12.3 6.3 1.1-1.1a3 3 0 0 1 4.2 4.2l-1.1 1.1" />
      </>
    ),
    mail: (
      <>
        <rect x="3" y="5" width="14" height="10" rx="2" />
        <path d="m4 7 6 4 6-4" />
      </>
    ),
    menu: (
      <>
        <path d="M4 6h12" />
        <path d="M4 10h12" />
        <path d="M4 14h12" />
      </>
    ),
    refresh: (
      <>
        <path d="M15.5 8A5.5 5.5 0 1 0 14 13.3" />
        <path d="M15.5 4.5V8h-3.5" />
        <path d="M4.5 12A5.5 5.5 0 0 0 14 13.3" />
        <path d="M4.5 15.5V12H8" />
      </>
    ),
    search: (
      <>
        <circle cx="9" cy="9" r="5" />
        <path d="m13 13 4 4" />
      </>
    ),
    settings: (
      <>
        <path d="M10 6.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z" />
        <path d="M10 2.5v2M10 15.5v2M3.5 10h-2M18.5 10h-2M5.4 5.4 4 4M16 16l-1.4-1.4M14.6 5.4 16 4M4 16l1.4-1.4" />
      </>
    ),
    shield: (
      <>
        <path d="M10 3 16 5v5c0 4-2.4 6.6-6 8-3.6-1.4-6-4-6-8V5l6-2Z" />
        <path d="M8 10.5 9.5 12l3-3" />
      </>
    ),
    truck: (
      <>
        <path d="M3 6h9v7H3V6Z" />
        <path d="M12 9h3l2 2v2h-5V9Z" />
        <circle cx="6" cy="15" r="1.5" />
        <circle cx="14" cy="15" r="1.5" />
      </>
    ),
    user: (
      <>
        <circle cx="10" cy="6.5" r="3" />
        <path d="M4.5 17a5.5 5.5 0 0 1 11 0" />
      </>
    ),
    users: (
      <>
        <circle cx="7.5" cy="7" r="2.5" />
        <circle cx="14" cy="8" r="2" />
        <path d="M3 17a4.5 4.5 0 0 1 9 0" />
        <path d="M12.5 17a3.5 3.5 0 0 1 4.5-3.3" />
      </>
    ),
  };

  return (
    <svg
      aria-hidden="true"
      className="admin-icon"
      fill="none"
      viewBox="0 0 20 20"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.7"
    >
      {paths[name]}
    </svg>
  );
}

function roleLabel(role: string): string {
  const labels: Record<string, string> = {
    admin: "管理员",
    operator: "运营",
    sales: "销售",
    viewer: "查看者",
  };
  return labels[role] ?? role;
}

function AdminHomePage({ navigate }: { navigate: (path: RoutePath) => void }) {
  const [summary, setSummary] = useState<QuoteErrorSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  async function loadSummary() {
    try {
      setSummary(await getQuoteErrorSummary(12));
      setSummaryError(null);
    } catch (caught) {
      setSummaryError(caught instanceof Error ? caught.message : "报价错误总览加载失败");
    }
  }

  useEffect(() => {
    void loadSummary();
  }, []);

  const quoteHistoryRows =
    summary?.recent_audits?.length
      ? summary.recent_audits
      : (summary?.recent_manual_audits ?? []);
  const totalToday = summary?.daily_total_audit_count ?? 0;
  const successToday = summary?.daily_successful_quote_count ?? 0;
  const successRate = totalToday > 0 ? `${Math.round((successToday / totalToday) * 1000) / 10}%` : "-";
  const manualRate =
    totalToday > 0 && summary?.daily_manual_required_audit_count !== undefined
      ? `${Math.round((summary.daily_manual_required_audit_count / totalToday) * 1000) / 10}%`
      : "-";
  const hermesRate =
    totalToday > 0 && summary?.pending_learning_candidate_count !== undefined
      ? `${Math.round((summary.pending_learning_candidate_count / totalToday) * 1000) / 10}%`
      : "-";
  const aiIssueRate =
    totalToday > 0 && summary?.daily_ai_issue_task_count !== undefined
      ? `${Math.round((summary.daily_ai_issue_task_count / totalToday) * 1000) / 10}%`
      : "-";
  const riskItems = summary?.daily_risk_tag_counts?.length
    ? summary.daily_risk_tag_counts
    : summary?.risk_tag_counts ?? [];
  const todayLabel = new Date().toLocaleDateString("en-CA");

  return (
    <div className="admin-dashboard-page">
      <section className="panel admin-overview-panel">
        <div className="admin-section-toolbar">
          <div>
            <h1>近 24h 运营概览</h1>
            <p>{summary?.window_label ?? "报价、人工任务、Hermes 学习和 AI 问题总览"}</p>
          </div>
          <div className="admin-toolbar-actions">
            <span className="admin-date-chip">{todayLabel}</span>
            <span className="admin-date-chip">近24小时</span>
            <button className="admin-icon-button" type="button" onClick={() => void loadSummary()} aria-label="刷新概览">
              <AdminIcon name="refresh" />
            </button>
          </div>
        </div>
        {summaryError && (
          <div className="mt-4 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900">
            {summaryError}
          </div>
        )}

        <div className="admin-overview-metrics">
          <AdminOverviewMetric
            icon="file"
            label="近24h 报价总数"
            trend="+12.5%"
            value={summary?.daily_total_audit_count}
          />
          <AdminOverviewMetric
            icon="shield"
            label="报价成功"
            note={`成功率 ${successRate}`}
            tone="success"
            trend="+8.2%"
            value={summary?.daily_successful_quote_count}
          />
          <AdminOverviewMetric
            icon="user"
            label="需人工处理"
            note={manualRate}
            tone="warn"
            trend="+5.4%"
            value={summary?.daily_manual_required_audit_count}
          />
          <AdminOverviewMetric
            icon="box"
            label="Hermes 待审"
            note={hermesRate}
            tone="purple"
            trend="+3.1%"
            value={summary?.pending_learning_candidate_count}
          />
          <AdminOverviewMetric
            icon="alert"
            label="AI 问题（需处理）"
            note={aiIssueRate}
            tone="danger"
            trend="+2.0%"
            value={summary?.daily_ai_issue_task_count}
          />
        </div>
      </section>

      <AdminQuickActions navigate={navigate} />

      <div className="admin-dashboard-grid">
        <section className="panel admin-table-panel">
          <div className="admin-card-header">
            <h2>最近报价</h2>
            <div className="flex flex-wrap gap-2">
              <button className="btn-secondary min-h-9 px-3 py-1" type="button" onClick={() => navigate("/audit")}>
                导出
              </button>
              <button className="btn-secondary min-h-9 px-3 py-1" type="button" onClick={() => void loadSummary()}>
                刷新
              </button>
              <button className="btn-secondary min-h-9 px-3 py-1 text-teal-700" type="button" onClick={() => navigate("/audit")}>
                查看全部
              </button>
            </div>
          </div>
          {quoteHistoryRows.length ? (
            <div className="overflow-x-auto">
              <div className="admin-data-table min-w-[920px]">
                <div className="admin-table-head grid-cols-[1.2fr_1.1fr_1fr_0.8fr_1fr_0.8fr_1.1fr]">
                  <span>报价 ID</span>
                  <span>目的地</span>
                  <span>来源地</span>
                  <span>区域</span>
                  <span>报价金额</span>
                  <span>状态</span>
                  <span>报价时间</span>
                </div>
                {quoteHistoryRows.slice(0, 10).map((audit) => (
                  <button
                    key={audit.id}
                    className="admin-table-row grid-cols-[1.2fr_1.1fr_1fr_0.8fr_1fr_0.8fr_1.1fr]"
                    type="button"
                    onClick={() => navigate("/audit")}
                  >
                    <span className="font-mono font-semibold text-teal-700">{audit.quote_id}</span>
                    <span>{[audit.city, audit.province].filter(Boolean).join(", ") || "未返回"}</span>
                    <span>{audit.origin || audit.postal_prefix || audit.postal_code || "-"}</span>
                    <span>{audit.zone === null ? "-" : `Zone ${audit.zone}`}</span>
                    <span className="font-mono font-semibold text-slate-950">{formatMoneyValue(audit.total_price_usd)}</span>
                    <span>
                      <AdminStatusPill tone={audit.manual_review_required ? "warn" : "success"}>
                        {audit.manual_review_required ? "需人工" : "成功"}
                      </AdminStatusPill>
                    </span>
                    <span>{audit.created_at ? formatDateTime(audit.created_at) : "-"}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="px-5 py-6 text-sm text-slate-600">
              暂无报价历史。产生报价后，这里会显示最近审计记录。
            </div>
          )}
          <div className="admin-pagination">
            <span>共 {summary?.daily_total_audit_count ?? quoteHistoryRows.length} 条</span>
            <button type="button" disabled>‹</button>
            <button className="active" type="button">1</button>
            <button type="button">2</button>
            <button type="button">3</button>
            <button type="button">4</button>
            <button type="button">5</button>
            <span>...</span>
            <button type="button">126</button>
            <button type="button">›</button>
            <select aria-label="每页条数">
              <option>10 条/页</option>
              <option>20 条/页</option>
            </select>
          </div>
        </section>

        <aside className="admin-right-stack">
          <section className="panel p-5">
            <div className="admin-card-header px-0 pt-0">
              <h2>待处理队列</h2>
              <button className="admin-link-button" type="button" onClick={() => navigate("/manual-tasks")}>
                查看全部
              </button>
            </div>
            <div className="mt-4 grid gap-3">
              <QueueCard
                count={summary?.pending_manual_task_count}
                description="地址解析异常 / 价格缺失 / 需人工确认"
                icon="user"
                label="人工报价任务"
                tone="warn"
                onClick={() => navigate("/manual-tasks")}
              />
              <QueueCard
                count={summary?.pending_learning_candidate_count}
                description="待审核学习的报价记录"
                icon="box"
                label="Hermes 学习候选"
                tone="purple"
                onClick={() => navigate("/learning-candidates")}
              />
              <QueueCard
                count={summary?.ai_issue_task_count}
                description="AI 解析或检索异常需要处理"
                icon="alert"
                label="AI 问题记录"
                tone="danger"
                onClick={() => navigate("/manual-tasks")}
              />
            </div>
          </section>

          <RiskDistribution items={riskItems} />
        </aside>
      </div>
    </div>
  );
}

function AdminQuickActions({ navigate }: { navigate: (path: RoutePath) => void }) {
  const actions: Array<{
    description: string;
    icon: AdminIconName;
    label: string;
    path: RoutePath;
  }> = [
    {
      description: "查看待确认报价、补录规则并回写客户回复",
      icon: "user",
      label: "人工任务",
      path: "/manual-tasks",
    },
    {
      description: "维护 Zone 价格、附加费和计费托数规则",
      icon: "calculator",
      label: "价格矩阵",
      path: "/settings/pricing",
    },
    {
      description: "配置模型、搜索验证和邮件通知链路",
      icon: "settings",
      label: "系统配置",
      path: "/settings/ai",
    },
    {
      description: "按 Quote ID、地址和风险标签追踪报价记录",
      icon: "search",
      label: "审计查询",
      path: "/audit",
    },
  ];

  return (
    <section className="admin-command-strip" aria-label="后台快捷操作">
      {actions.map((action) => (
        <button key={action.path} type="button" onClick={() => navigate(action.path)}>
          <span>
            <AdminIcon name={action.icon} />
          </span>
          <strong>{action.label}</strong>
          <small>{action.description}</small>
        </button>
      ))}
    </section>
  );
}

function AdminOverviewMetric({
  icon,
  label,
  note,
  tone = "teal",
  trend,
  value,
}: {
  icon: AdminIconName;
  label: string;
  note?: string;
  tone?: "danger" | "purple" | "success" | "teal" | "warn";
  trend?: string;
  value: number | undefined;
}) {
  return (
    <div className="admin-overview-card">
      <div className={`admin-metric-icon admin-metric-${tone}`}>
        <AdminIcon name={icon} />
      </div>
      <div>
        <p>{label}</p>
        <strong>{value ?? "-"}</strong>
      </div>
      {note && <span>{note}</span>}
      {trend && <small>较昨日 {trend}</small>}
    </div>
  );
}

function AdminStatusPill({
  children,
  tone,
}: {
  children: ReactNode;
  tone: "danger" | "success" | "warn";
}) {
  return <span className={`admin-status-pill admin-status-${tone}`}>{children}</span>;
}

function QueueCard({
  count,
  description,
  icon,
  label,
  onClick,
  tone,
}: {
  count: number | undefined;
  description: string;
  icon: AdminIconName;
  label: string;
  onClick: () => void;
  tone: "danger" | "purple" | "warn";
}) {
  return (
    <button className="admin-queue-card" type="button" onClick={onClick}>
      <span className={`admin-queue-icon admin-metric-${tone}`}>
        <AdminIcon name={icon} />
      </span>
      <span className="min-w-0">
        <strong>{label}</strong>
        <small>{description}</small>
      </span>
      <b>{count ?? "-"}</b>
      <span className="text-slate-400">›</span>
    </button>
  );
}

function RiskDistribution({
  items,
}: {
  items: NonNullable<QuoteErrorSummary["risk_tag_counts"]>;
}) {
  const total = items.reduce((sum, item) => sum + item.count, 0);
  const colors = ["#ef4444", "#f59e0b", "#0ea5e9", "#22c55e", "#94a3b8"];
  let cursor = 0;
  const gradient =
    total > 0
      ? items.slice(0, 5).map((item, index) => {
          const start = cursor;
          cursor += (item.count / total) * 100;
          return `${colors[index]} ${start}% ${cursor}%`;
        }).join(", ")
      : "#e2e8f0 0% 100%";

  return (
    <section className="panel p-5">
      <div className="admin-card-header px-0 pt-0">
        <h2>风险标签分布（近24h）</h2>
        <span className="admin-link-button">
          查看全部
        </span>
      </div>
      <div className="admin-risk-body">
        <div className="admin-risk-donut" style={{ background: `conic-gradient(${gradient})` }}>
          <div>
            <strong>{total || "-"}</strong>
            <span>总风险数</span>
          </div>
        </div>
        <div className="admin-risk-list">
          {items.slice(0, 5).map((item, index) => (
            <div key={item.tag}>
              <span style={{ background: colors[index] }} />
              <p>{item.label || item.tag}</p>
              <strong>
                {item.count}
                {total > 0 ? ` (${Math.round((item.count / total) * 1000) / 10}%)` : ""}
              </strong>
            </div>
          ))}
          {!items.length && <p className="text-sm text-slate-500">暂无风险标签</p>}
        </div>
      </div>
      <p className="mt-4 text-xs leading-5 text-slate-500">
        仅统计状态为“成功”或“需人工”的报价。
      </p>
    </section>
  );
}

function formatAuditSource(value: string): string {
  const labels: Record<string, string> = {
    zone_matrix: "Zone 矩阵",
    manual_required: "人工复核",
    learned_manual_quote: "学习库",
    llm_auxiliary_advice: "LLM 建议",
    hermes_agent_correction: "LLM 建议",
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
