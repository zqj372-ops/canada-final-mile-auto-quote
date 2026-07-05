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

export interface ZoneQuoteWithNotifyRequest {
  quote: ZoneQuoteRequest;
  notify_wecom: boolean;
  wecom_bot_id?: number | null;
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

export interface AIExtractedQuoteDraft {
  address_line: string | null;
  postal_code: string | null;
  city: string | null;
  province: string | null;
  cbm: MoneyValue;
  weight_kg: MoneyValue;
  piece_count: number | null;
  packaging_type: string | null;
  longest_side_cm: MoneyValue;
  explicit_pallet_count: number | null;
  is_stackable: boolean | null;
  address_type: string | null;
  requires_liftgate: boolean;
  requires_pallet_jack: boolean;
  requires_appointment: boolean;
  detention_minutes: number;
  missing_fields: string[];
  confidence: number;
  extraction_notes: string | null;
}

export interface AIAutoQuoteRequest {
  customer_message: string;
  ai_config_id?: number | null;
  auto_submit_when_complete: boolean;
  notify_wecom?: boolean;
  wecom_bot_id?: number | null;
}

export interface AIAutoQuoteResponse {
  extraction: AIExtractedQuoteDraft;
  quote_result: ZoneQuoteResult | null;
  customer_reply: string | null;
  internal_note: string | null;
  missing_fields: string[];
  manual_review_required: boolean;
}

export interface AIModelConfigPublic {
  id: number;
  name: string;
  provider: string;
  base_url: string | null;
  masked_api_key: string | null;
  model_name: string;
  temperature: number;
  max_tokens: number;
  timeout_seconds: number;
  is_default: boolean;
  enabled: boolean;
  purpose: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface AIModelConfigPayload {
  name?: string;
  provider?: string;
  base_url?: string | null;
  api_key?: string | null;
  model_name?: string;
  temperature?: number;
  max_tokens?: number;
  timeout_seconds?: number;
  is_default?: boolean;
  enabled?: boolean;
  purpose?: string;
}

export interface AIConfigTestResult {
  success: boolean;
  error: string | null;
  latency_ms: number;
  preview?: string;
}

export interface WeComBotConfigPublic {
  id: number;
  name: string;
  masked_webhook_url: string | null;
  bot_type: string;
  purpose: string;
  enabled: boolean;
  is_default: boolean;
  mention_all_on_manual_required: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface WeComBotConfigPayload {
  name?: string;
  webhook_url?: string | null;
  bot_type?: string;
  purpose?: string;
  enabled?: boolean;
  is_default?: boolean;
  mention_all_on_manual_required?: boolean;
}

export interface WeComTestResult {
  success: boolean;
  error: string | null;
  latency_ms: number;
  status_code: number | null;
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
  notify_wecom?: boolean;
  wecom_bot_id?: number | null;
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

export interface WorkbenchOption {
  value: string;
  label: string;
}

export interface ProvinceAlias {
  code: string;
  name: string;
  aliases: string[];
}

export interface WorkbenchParserConfig {
  dimension_separators: string[];
  allow_space_dimension_separator: boolean;
  weight_units: string[];
  postal_code_pattern: string;
  country_aliases: string[];
  default_country: string;
}

export interface WorkbenchQuoteDefaults {
  packaging_type: PackagingType;
  address_type: AddressType;
  is_stackable: boolean | null;
  explicit_pallet_count: number | null;
  requires_liftgate: boolean;
  requires_pallet_jack: boolean;
  requires_appointment: boolean;
  detention_minutes: number;
  notify_wecom: boolean;
}

export interface WorkbenchRiskConfig {
  dense_density_kg_per_cbm: number;
  light_density_kg_per_cbm: number;
  oversized_longest_side_cm: number;
  heavy_single_piece_kg: number;
  core_city_names: string[];
}

export interface WorkbenchCopyTemplateConfig {
  currency_code: string;
  valid_days: number;
  manual_price_text: string;
  included_items: string[];
  excluded_items: string[];
  remark: string;
}

export interface QuoteWorkbenchConfig {
  title: string;
  subtitle: string;
  input_title: string;
  input_label: string;
  primary_button_label: string;
  clear_button_label: string;
  import_button_label: string;
  status_labels: Record<string, string>;
  sample_input: string;
  format_hints: string[];
  packaging_options: WorkbenchOption[];
  address_type_options: WorkbenchOption[];
  service_options: WorkbenchOption[];
  accessorial_labels: Record<string, string>;
  backend_risk_tag_labels: Record<string, string>;
  provinces: ProvinceAlias[];
  parser: WorkbenchParserConfig;
  defaults: WorkbenchQuoteDefaults;
  risks: WorkbenchRiskConfig;
  copy_template: WorkbenchCopyTemplateConfig;
}

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000"
).replace(/\/$/, "");
const API_KEY_STORAGE_KEY = "canada-final-mile-api-key";

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
  const apiKey = getStoredApiKey();
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(apiKey ? { "X-API-Key": apiKey } : {}),
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
  payload: ZoneQuoteRequest | ZoneQuoteWithNotifyRequest,
): Promise<ZoneQuoteResult> {
  return request<ZoneQuoteResult>("/quotes/zone-calculate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function calculateAIAutoQuote(
  payload: AIAutoQuoteRequest,
): Promise<AIAutoQuoteResponse> {
  return request<AIAutoQuoteResponse>("/quotes/ai-auto-quote", {
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

export function getQuoteWorkbenchConfig(): Promise<QuoteWorkbenchConfig> {
  return request<QuoteWorkbenchConfig>("/quote-configs/workbench");
}

export function updateQuoteWorkbenchConfig(
  payload: QuoteWorkbenchConfig,
): Promise<QuoteWorkbenchConfig> {
  return request<QuoteWorkbenchConfig>("/quote-configs/workbench", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function listAIConfigs(): Promise<AIModelConfigPublic[]> {
  return request<AIModelConfigPublic[]>("/ai-configs");
}

export function createAIConfig(
  payload: Required<Pick<AIModelConfigPayload, "name" | "model_name">> & AIModelConfigPayload,
): Promise<AIModelConfigPublic> {
  return request<AIModelConfigPublic>("/ai-configs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateAIConfig(
  configId: number,
  payload: AIModelConfigPayload,
): Promise<AIModelConfigPublic> {
  return request<AIModelConfigPublic>(`/ai-configs/${configId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteAIConfig(configId: number): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/ai-configs/${configId}`, {
    method: "DELETE",
  });
}

export function setDefaultAIConfig(configId: number): Promise<AIModelConfigPublic> {
  return request<AIModelConfigPublic>(`/ai-configs/${configId}/set-default`, {
    method: "POST",
  });
}

export function testAIConfig(configId: number): Promise<AIConfigTestResult> {
  return request<AIConfigTestResult>(`/ai-configs/${configId}/test`, {
    method: "POST",
  });
}

export function listWeComBots(): Promise<WeComBotConfigPublic[]> {
  return request<WeComBotConfigPublic[]>("/wecom/bots");
}

export function createWeComBot(
  payload: Required<Pick<WeComBotConfigPayload, "name" | "webhook_url">> & WeComBotConfigPayload,
): Promise<WeComBotConfigPublic> {
  return request<WeComBotConfigPublic>("/wecom/bots", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateWeComBot(
  botId: number,
  payload: WeComBotConfigPayload,
): Promise<WeComBotConfigPublic> {
  return request<WeComBotConfigPublic>(`/wecom/bots/${botId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteWeComBot(botId: number): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/wecom/bots/${botId}`, {
    method: "DELETE",
  });
}

export function setDefaultWeComBot(botId: number): Promise<WeComBotConfigPublic> {
  return request<WeComBotConfigPublic>(`/wecom/bots/${botId}/set-default`, {
    method: "POST",
  });
}

export function testWeComBot(botId: number): Promise<WeComTestResult> {
  return request<WeComTestResult>(`/wecom/bots/${botId}/test`, {
    method: "POST",
  });
}

export function getApiBaseUrl(): string {
  return API_BASE_URL;
}

export function getStoredApiKey(): string {
  try {
    return window.localStorage.getItem(API_KEY_STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setStoredApiKey(apiKey: string): void {
  window.localStorage.setItem(API_KEY_STORAGE_KEY, apiKey.trim());
}

export function clearStoredApiKey(): void {
  window.localStorage.removeItem(API_KEY_STORAGE_KEY);
}
