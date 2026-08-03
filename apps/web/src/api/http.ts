export type ApiScope = "quote" | "admin";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "/api").replace(/\/$/, "");
const API_KEY_STORAGE_KEYS: Record<ApiScope, string> = {
  quote: "canada-final-mile-quote-api-key",
  admin: "canada-final-mile-admin-api-key",
};
const AUTH_TOKEN_STORAGE_KEY = "canada-final-mile-auth-token";

export class ApiError extends Error {
  readonly status: number;
  readonly details: unknown;

  constructor(message: string, status: number, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

export async function request<T>(path: string, options: RequestInit = {}, scope: ApiScope = "admin"): Promise<T> {
  const apiKey = localStorage.getItem(API_KEY_STORAGE_KEYS[scope]);
  const authToken = localStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers: {
        ...(isFormData ? {} : { "Content-Type": "application/json" }),
        ...(authToken ? { Authorization: `Bearer ${authToken}` } : apiKey ? { "X-API-Key": apiKey } : {}),
        ...(options.headers ?? {}),
      },
    });
  } catch (error) {
    throw new ApiError(error instanceof Error ? error.message : "Network request failed", 0, error);
  }

  const contentType = response.headers.get("content-type") ?? "";
  const data: unknown = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    if (response.status === 401) localStorage.removeItem(API_KEY_STORAGE_KEYS[scope]);
    const details = data && typeof data === "object" && "detail" in data ? (data as { detail: unknown }).detail : data;
    throw new ApiError(formatError(details, response.statusText), response.status, details);
  }
  return data as T;
}

function formatError(details: unknown, fallback: string): string {
  if (typeof details === "string" && details.trim()) return details.trim();
  if (details !== undefined && details !== null) return JSON.stringify(details);
  return fallback || "Request failed";
}
