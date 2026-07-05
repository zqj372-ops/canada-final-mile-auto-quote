import { useEffect, useMemo, useState } from "react";
import { getApiBaseUrl } from "./api/client";
import AuditPage from "./pages/AuditPage";
import ManualTasksPage from "./pages/ManualTasksPage";
import QuotePage from "./pages/QuotePage";

type RoutePath = "/quote" | "/manual-tasks" | "/audit";

const routes: Array<{ path: RoutePath; label: string; description: string }> = [
  { path: "/quote", label: "报价", description: "Zone 计算" },
  { path: "/manual-tasks", label: "人工池", description: "Manual review" },
  { path: "/audit", label: "审计", description: "Quote log" },
];

export default function App() {
  const [path, setPath] = useState<RoutePath>(() =>
    normalizePath(window.location.pathname),
  );

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
    if (path === "/manual-tasks") {
      return <ManualTasksPage />;
    }
    if (path === "/audit") {
      return <AuditPage />;
    }
    return <QuotePage />;
  }, [path]);

  function navigate(nextPath: RoutePath) {
    if (nextPath === path) {
      return;
    }
    window.history.pushState({}, "", nextPath);
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

          <nav className="flex flex-wrap gap-2" aria-label="主导航">
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
                  href={route.path}
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
      </header>

      <main id="main-content" tabIndex={-1}>
        {page}
      </main>
    </div>
  );
}

function normalizePath(pathname: string): RoutePath {
  if (pathname === "/manual-tasks") {
    return "/manual-tasks";
  }
  if (pathname === "/audit") {
    return "/audit";
  }
  return "/quote";
}
