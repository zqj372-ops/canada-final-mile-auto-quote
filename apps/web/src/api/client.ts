export type PackagingType =
  | "carton"
  | "wooden_crate"
  | "pallet"
  | "woven_bag"
  | "flexible_packaging"
  | "unknown";

export type AddressType =
  | "commercial"
  | "residential"
  | "private"
  | "rural_residential";

export type MoneyValue = string | number | null;

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export interface ZoneQuoteRequest {
  address_line: string | null;
  postal_code: string;
  city: string | null;
  province: string | null;
  cbm: number;
  weight_kg: number;
  piece_count: number;
  packaging_type: PackagingType;
  longest_side_cm: number | null;
  explicit_pallet_count: number | null;
  is_stackable: boolean | null;
  address_type: AddressType;
  requires_liftgate: boolean;
  requires_pallet_jack: boolean;
  requires_appointment: boolean;
  detention_minutes: number;
}

export interface ZoneQuoteResult {
  quote_id: string;
  source_type: "zone_matrix" | "manual_required" | string;
  confidence: number;
  postal_code: string | null;
  preferred_city: string | null;
  postal_prefix: string | null;
  city: string | null;
  province: string | null;
  origin: string | null;
  zone: number | null;
  billing_pallets: number | null;
  base_price_usd: MoneyValue;
  fuel_usd: MoneyValue;
  accessorials: Record<string, MoneyValue>;
  total_price_usd: MoneyValue;
  risk_tags: string[];
  manual_review_required: boolean;
  matched_rule: string;
  sales_note: string | null;
  internal_note: string | null;
}

export interface ManualQuoteTask {
  id: number;
  quote_id: string;
  reason: string;
  risk_tags: string[];
  request_json: JsonValue;
  result_json: JsonValue;
  status: string;
  assigned_to: string | null;
  resolved_price_usd: MoneyValue;
  resolved_note: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ManualQuoteTaskUpdate {
  status?: string | null;
  assigned_to?: string | null;
  resolved_price_usd?: number | null;
  resolved_note?: string | null;
}

export interface QuoteAuditLog {
  id: number;
  quote_id: string;
  request_json: JsonValue;
  result_json: JsonValue;
  source_type: string;
  postal_code: string | null;
  postal_prefix: string | null;
  city: string | null;
  province: string | null;
  origin: string | null;
  zone: number | null;
  billing_pallets: number | null;
  base_price_usd: MoneyValue;
  total_price_usd: MoneyValue;
  manual_review_required: boolean;
  risk_tags: string[];
  created_at: string | null;
}

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000"
).replace(/\/$/, "");

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers ?? {}),
    },
  });

  const contentType = response.headers.get("content-type") ?? "";
  const data = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    throw new ApiError(formatApiError(data, response.statusText), response.status);
  }

  return data as T;
}

function formatApiError(data: unknown, fallback: string): string {
  if (typeof data === "string" && data.trim()) {
    return data;
  }
  if (data && typeof data === "object" && "detail" in data) {
    const detail = (data as { detail: unknown }).detail;
    if (typeof detail === "string") {
      return detail;
    }
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (item && typeof item === "object" && "msg" in item) {
            const location = "loc" in item ? String((item as { loc: unknown }).loc) : "";
            return `${location ? `${location}: ` : ""}${String((item as { msg: unknown }).msg)}`;
          }
          return JSON.stringify(item);
        })
        .join("; ");
    }
    return JSON.stringify(detail);
  }
  return fallback || "Request failed";
}

export function calculateZoneQuote(
  payload: ZoneQuoteRequest,
): Promise<ZoneQuoteResult> {
  return request<ZoneQuoteResult>("/quotes/zone-calculate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listManualTasks(): Promise<ManualQuoteTask[]> {
  return request<ManualQuoteTask[]>("/quotes/manual-tasks");
}

export function updateManualTask(
  taskId: number,
  payload: ManualQuoteTaskUpdate,
): Promise<ManualQuoteTask> {
  return request<ManualQuoteTask>(`/quotes/manual-tasks/${taskId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function getQuoteAudit(quoteId: string): Promise<QuoteAuditLog> {
  return request<QuoteAuditLog>(`/quotes/audit/${encodeURIComponent(quoteId)}`);
}

export function getApiBaseUrl(): string {
  return API_BASE_URL;
}
