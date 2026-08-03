export type AppSurface = "sales" | "admin" | "not-found";

export function normalizeBasePath(value: string | undefined | null): string {
  const path = (value ?? "").trim();
  if (!path || path === "/") return "";
  return `/${path.replace(/^\/+|\/+$/g, "")}`;
}

export function stripBasePath(pathname: string, basePath: string | undefined | null): string {
  const path = pathname || "/";
  const base = normalizeBasePath(basePath);
  if (!base) return path;
  if (path === base) return "/";
  if (path.startsWith(`${base}/`)) return path.slice(base.length) || "/";
  return path;
}

export function classifyAppSurface(pathname: string, basePath = import.meta.env.VITE_APP_BASE_PATH ?? ""): AppSurface {
  const path = stripBasePath(pathname, basePath);
  if (path === "/quote" || path.startsWith("/quote/")) return "sales";
  if (path === "/admin" || path.startsWith("/admin/")) return "admin";
  return "not-found";
}

export function navigateTo(pathname: string, basePath = import.meta.env.VITE_APP_BASE_PATH ?? ""): string {
  const base = normalizeBasePath(basePath);
  const path = pathname.startsWith("/") ? pathname : `/${pathname}`;
  return `${base}${path}` || "/";
}
