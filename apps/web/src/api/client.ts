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
  notify_email?: boolean;
  email_config_id?: number | null;
  notify_wecom?: boolean;
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
  pallet_breakdown: Record<string, number>;
  base_price_usd: MoneyValue;
  fuel_usd: MoneyValue;
  accessorials: Record<string, MoneyValue>;
  total_price_usd: MoneyValue;
  risk_tags: string[];
  manual_review_required: boolean;
  matched_rule: string;
  matched_by: string | null;
  candidate_count: number;
  match_trace: Record<string, JsonValue>;
  sales_note: string | null;
  internal_note: string | null;
}

export interface CurrentActor {
  user_id: number | null;
  api_key_id: number | null;
  name: string;
  role: string;
}

export interface AuthLoginRequest {
  username: string;
  password: string;
}

export interface AuthLoginResponse {
  access_token: string;
  token_type: "bearer";
  expires_in_seconds: number;
  actor: CurrentActor;
}

export type UserRole = "admin" | "operator" | "sales" | "viewer";

export interface UserPublic {
  id: number;
  username: string;
  display_name: string;
  role: UserRole;
  enabled: boolean;
  created_at: string | null;
  updated_at: string | null;
  last_login_at: string | null;
}

export interface UserPayload {
  username?: string;
  password?: string;
  display_name?: string | null;
  role?: UserRole;
  enabled?: boolean;
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
  cargo_items: AIExtractedCargoItem[];
  cargo_agent: Record<string, JsonValue> | null;
  address_agent: Record<string, JsonValue> | null;
  validation_notes: string[];
}

export interface AIExtractedCargoItem {
  quantity: number;
  length_cm: MoneyValue;
  width_cm: MoneyValue;
  height_cm: MoneyValue;
  weight_kg: MoneyValue;
  cbm: MoneyValue;
  total_weight_kg: MoneyValue;
  total_cbm: MoneyValue;
  source_span: string | null;
}

export interface AIAutoQuoteRequest {
  customer_message: string;
  ai_config_id?: number | null;
  auto_submit_when_complete: boolean;
  notify_email?: boolean;
  email_config_id?: number | null;
  notify_wecom?: boolean;
  wecom_bot_id?: number | null;
  enable_search_context?: boolean;
  search_config_id?: number | null;
}

export interface AIAutoQuoteResponse {
  extraction: AIExtractedQuoteDraft;
  quote_result: ZoneQuoteResult | null;
  customer_reply: string | null;
  internal_note: string | null;
  missing_fields: string[];
  manual_review_required: boolean;
  search_context: QuoteSearchContext | null;
  address_validation: LocalAddressValidation | null;
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

export interface AIAgentModelAssignment {
  agent_key: string;
  config: AIModelConfigPublic | null;
}

export interface AIProviderPreset {
  provider: string;
  label: string;
  base_url: string;
  models_path: string;
  chat_path: string;
  api_key_hint: string;
  recommended_models: string[];
  notes: string | null;
}

export interface DiscoveredModel {
  id: string;
  display_name: string | null;
  owned_by: string | null;
  context_length: number | null;
  source: string;
}

export interface ModelDiscoveryRequest {
  provider: string;
  base_url?: string | null;
  api_key: string;
  timeout_seconds?: number;
}

export interface ModelDiscoveryResult {
  provider: string;
  base_url: string;
  models: DiscoveredModel[];
  latency_ms: number | null;
  error: string | null;
}

export interface WeComBotConfigPublic {
  id: number;
  name: string;
  masked_webhook_url: string | null;
  masked_bot_id: string | null;
  has_secret: boolean;
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
  bot_id?: string | null;
  secret?: string | null;
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

export interface EmailConfigPublic {
  id: number;
  name: string;
  smtp_host: string;
  smtp_port: number;
  masked_username: string | null;
  has_password: boolean;
  from_email: string;
  from_name: string | null;
  recipient_emails: string[];
  use_tls: boolean;
  use_ssl: boolean;
  purpose: string;
  enabled: boolean;
  is_default: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface EmailConfigPayload {
  name?: string;
  smtp_host?: string;
  smtp_port?: number;
  username?: string | null;
  password?: string | null;
  from_email?: string;
  from_name?: string | null;
  recipient_emails?: string[];
  use_tls?: boolean;
  use_ssl?: boolean;
  purpose?: string;
  enabled?: boolean;
  is_default?: boolean;
}

export interface EmailTestResult {
  success: boolean;
  error: string | null;
  latency_ms: number;
  status_code: number | null;
}

export interface SearchApiConfigPublic {
  id: number;
  name: string;
  provider: string;
  base_url: string | null;
  masked_api_key: string | null;
  purpose: string;
  enabled: boolean;
  is_default: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface SearchApiConfigPayload {
  name?: string;
  provider?: string;
  base_url?: string | null;
  api_key?: string | null;
  purpose?: string;
  enabled?: boolean;
  is_default?: boolean;
}

export interface SearchConfigTestResult {
  success: boolean;
  error: string | null;
  latency_ms: number;
  result_count: number;
  preview: string | null;
}

export interface SearchResultItem {
  title: string;
  url: string;
  content: string | null;
  score: number | null;
}

export interface SearchEvidence {
  query: string;
  answer: string | null;
  summary_zh?: string | null;
  results: SearchResultItem[];
  error: string | null;
}

export interface QuoteSearchContext {
  provider: string;
  address_research: SearchEvidence | null;
  market_research: SearchEvidence | null;
  note: string;
}

export interface LocalAddressValidation {
  provider: string;
  status:
    | "missing_postal_code"
    | "invalid_postal_code"
    | "postal_not_found"
    | "postal_verified"
    | "verified"
    | "corrected_by_postal_lookup";
  matched: boolean;
  confidence: number;
  address_line: string | null;
  postal_code: string | null;
  postal_prefix: string | null;
  input_city: string | null;
  input_province: string | null;
  preferred_city: string | null;
  official_city: string | null;
  municipality: string | null;
  province: string | null;
  corrected_city: string | null;
  corrected_province: string | null;
  city_consistent: boolean | null;
  province_consistent: boolean | null;
  latitude: number | null;
  longitude: number | null;
  source: string | null;
  risk_tags: string[];
  note_zh: string;
}

export interface ManualQuoteTask {
  id: number;
  quote_id: string;
  reason: string;
  reason_zh?: string | null;
  risk_tags: string[];
  risk_tag_labels?: string[];
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
  notify_email?: boolean;
  email_config_id?: number | null;
  notify_wecom?: boolean;
  wecom_bot_id?: number | null;
}

export interface QuoteAuditLog {
  id: number;
  quote_id: string;
  request_json: JsonValue;
  result_json: JsonValue;
  quote_logic?: JsonValue;
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
  risk_tag_labels?: string[];
  created_at: string | null;
}

export interface SalesQuoteRecord {
  id: number;
  quote_id: string | null;
  actor_user_id: number | null;
  actor_api_key_id: number | null;
  actor_name: string | null;
  actor_role: string | null;
  status: "quoted" | "manual_required" | string;
  customer_message: string;
  customer_reply: string | null;
  destination: string;
  cargo_summary: string;
  total_price_usd: MoneyValue;
  currency_code: string;
  zone: number | null;
  billing_pallets: number | null;
  confidence: number;
  source_type: string;
  postal_code: string | null;
  city: string | null;
  province: string | null;
  risk_tags: string[];
  risk_tag_labels?: string[];
  missing_fields: string[];
  manual_reason: string | null;
  created_at: string | null;
  request_json: JsonValue;
  result_json: JsonValue;
}

export interface SalesQuoteManualPricePayload {
  total_price_usd: number;
  override_note: string;
  customer_reply?: string | null;
  confirmed: boolean;
}

export interface RiskTagCount {
  tag: string;
  label?: string;
  count: number;
}

export interface QuoteErrorSummary {
  window_label?: string;
  window_started_at?: string;
  daily_total_audit_count?: number;
  daily_successful_quote_count?: number;
  daily_manual_required_audit_count?: number;
  daily_created_manual_task_count?: number;
  daily_pending_manual_task_count?: number;
  daily_ai_issue_task_count?: number;
  daily_risk_tag_counts?: RiskTagCount[];
  total_audit_count: number;
  successful_quote_count: number;
  manual_required_audit_count: number;
  pending_manual_task_count: number;
  resolved_manual_task_count: number;
  ai_issue_task_count: number;
  active_learning_rule_count?: number;
  pending_learning_candidate_count?: number;
  approved_learning_candidate_count?: number;
  rejected_learning_candidate_count?: number;
  learning_rule_usage_count?: number;
  risk_tag_counts: RiskTagCount[];
  recent_manual_tasks: ManualQuoteTask[];
  recent_audits?: QuoteAuditLog[];
  recent_manual_audits: QuoteAuditLog[];
  recent_learning_rules?: LearnedQuoteRule[];
  recent_learning_candidates?: HermesLearningCandidate[];
}

export interface LearnedQuoteRule {
  id: number;
  source_task_id: number | null;
  quote_id: string | null;
  scope: string;
  postal_code: string | null;
  postal_prefix: string | null;
  city: string | null;
  province: string | null;
  origin: string | null;
  zone: number | null;
  billing_pallets: number;
  total_price_usd: MoneyValue;
  base_price_usd: MoneyValue;
  confidence: number;
  status: string;
  usage_count: number;
  note: string | null;
  created_at: string | null;
  updated_at: string | null;
  last_used_at: string | null;
}

export interface HermesLearningCandidate {
  id: number;
  source_task_id: number | null;
  quote_id: string | null;
  candidate_type: string;
  scope: string;
  postal_code: string | null;
  postal_prefix: string | null;
  city: string | null;
  province: string | null;
  origin: string | null;
  zone: number | null;
  billing_pallets: number;
  resolved_total_price_usd: MoneyValue;
  resolved_base_price_usd: MoneyValue;
  confidence: number;
  support_count: number;
  status: string;
  duplicate_key: string;
  proposal_json: JsonValue;
  evidence_json: JsonValue;
  risk_tags: string[];
  review_note: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  promoted_rule_id: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface HermesDiagnosticRecord {
  id: number;
  quote_id: string;
  quote_status: string;
  source_type: string;
  status: string;
  diagnostic_package: Record<string, JsonValue>;
  agent_suggestion: Record<string, JsonValue> | null;
  agent_error: string | null;
  suggested_action: string | null;
  confidence: number | null;
  recommend_manual_review: boolean | null;
  recommend_learning_candidate: boolean | null;
  learning_candidate_id: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface HermesDiagnosticSuggestionPayload {
  suggested_action?: string;
  can_auto_correct?: boolean;
  confidence?: number;
  reason_zh: string;
  suggested_origin?: string | null;
  suggested_zone?: number | null;
  missing_table?: string | null;
  recommend_manual_review?: boolean;
  recommend_learning_candidate?: boolean;
  evidence_ids?: string[];
  notes?: string[];
}

export interface BatchDiagnosticReportSummary {
  batch_id: string;
  generated_at: string | null;
  source: string;
  report_available: boolean;
  requested_sample_size: number | null;
  actual_sample_size: number | null;
  quoted: number | null;
  manual_required: number | null;
  anomalies: number | null;
  quote_success_rate: string | null;
  manual_required_rate: string | null;
  learning_suggestion_count: number;
  persisted_diagnostic_count: number | null;
  diagnostic_count: number;
  profiles: JsonValue[];
}

export interface BatchDiagnosticReportDetail extends BatchDiagnosticReportSummary {
  file_path?: string;
  counters: Record<string, Record<string, number>>;
  top_manual_clusters: JsonValue[];
  top_fallback_clusters: JsonValue[];
  top_expected_origin_clusters: JsonValue[];
  top_price_gap_clusters: JsonValue[];
  learning_suggestions: JsonValue[];
  sample_anomalies: JsonValue[];
  sample_observations: JsonValue[];
  policy: Record<string, JsonValue>;
}

export interface HermesCandidateReviewPayload {
  review_note?: string | null;
}

export interface HermesApproveResponse {
  candidate: HermesLearningCandidate;
  learned_rule: LearnedQuoteRule;
}

export interface LearnedRuleUpdatePayload {
  status: string;
  note?: string | null;
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

export interface ZonePricingConfig {
  fuel_percent: MoneyValue;
  fuel_percent_by_zone: Record<string, MoneyValue>;
  zone_price_enabled: boolean;
  max_auto_quote_zone: number | null;
  zone_price_enabled_by_zone: Record<string, boolean>;
  residential_fee_usd: MoneyValue;
  liftgate_fee_usd: MoneyValue;
  pallet_jack_fee_usd: MoneyValue;
  appointment_fee_usd: MoneyValue;
  detention_half_hour_fee_usd: MoneyValue;
  detention_free_minutes: number;
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
  zone_pricing: ZonePricingConfig;
}

export interface ZonePriceMatrixRecord {
  id: number;
  origin: string;
  zone: number;
  billing_pallets: number;
  base_price_usd: MoneyValue;
  source: string | null;
  last_updated: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ZonePriceMatrixListResponse {
  records: ZonePriceMatrixRecord[];
  total: number;
  origins: string[];
  zones: number[];
  billing_pallets: number[];
}

export interface ZonePriceMatrixPayload {
  origin: string;
  zone: number;
  billing_pallets: number;
  base_price_usd: MoneyValue;
  source?: string | null;
  last_updated?: string | null;
}

export interface ZonePriceImportIssue {
  row: number | null;
  field: string | null;
  message: string;
}

export interface ZonePriceImportPreviewRow {
  row: number;
  origin: string;
  zone: number;
  billing_pallets: number;
  base_price_usd: MoneyValue;
  fuel_percent: MoneyValue;
  action: "insert" | "update";
}

export interface ZonePriceImportPreview {
  status: "valid" | "invalid";
  can_import: boolean;
  filename: string;
  source_row_count: number;
  row_count: number;
  invalid_row_count: number;
  inserted_count: number;
  updated_count: number;
  fuel_override_count: number;
  fuel_updated_count: number;
  preview_rows: ZonePriceImportPreviewRow[];
  errors: ZonePriceImportIssue[];
  warnings: ZonePriceImportIssue[];
}

export interface ZonePriceImportResult {
  status: "imported";
  resource: "zone_price_matrix";
  filename: string;
  source_row_count: number;
  row_count: number;
  inserted_count: number;
  updated_count: number;
  skipped_count: number;
  fuel_override_count: number;
  fuel_updated_count: number;
}

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || "/api"
).replace(/\/$/, "");
export type ApiKeyScope = "quote" | "admin";
const AUTH_TOKEN_STORAGE_KEY = "canada-final-mile-auth-token";

const API_KEY_STORAGE_KEYS: Record<ApiKeyScope, string> = {
  quote: "canada-final-mile-quote-api-key",
  admin: "canada-final-mile-admin-api-key",
};

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
  apiKeyScope: ApiKeyScope = "admin",
): Promise<T> {
  const apiKey = getStoredApiKey(apiKeyScope);
  const authToken = getStoredAuthToken();
  const isFormDataBody = typeof FormData !== "undefined" && options.body instanceof FormData;
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      ...(isFormDataBody ? {} : { "Content-Type": "application/json" }),
      ...(authToken ? { Authorization: `Bearer ${authToken}` } : apiKey ? { "X-API-Key": apiKey } : {}),
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
    return sanitizeErrorText(data, fallback);
  }
  if (data && typeof data === "object" && "detail" in data) {
    const detail = (data as { detail: unknown }).detail;
    if (typeof detail === "string") {
      return sanitizeErrorText(detail, fallback);
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

function sanitizeErrorText(value: string, fallback: string): string {
  const compact = value.replace(/\s+/g, " ").trim();
  if (/<html[\s>]/i.test(compact) || /<!doctype html/i.test(compact)) {
    const title = compact.match(/<title>(.*?)<\/title>/i)?.[1]?.replace(/\s+/g, " ").trim();
    if (title) {
      if (/504|gateway\s*time-?out/i.test(title)) {
        return "报价请求超过网关等待时间，系统未生成可靠报价。请稍后重试；如已进入人工任务池，请由人工确认后再发客户。";
      }
      return `外部服务返回错误：${title}`;
    }
    return fallback || "外部服务返回 HTML 错误页";
  }
  if (/504|gateway\s*time-?out/i.test(compact)) {
    return "报价请求超过网关等待时间，系统未生成可靠报价。请稍后重试；如已进入人工任务池，请由人工确认后再发客户。";
  }
  if (/^error code:\s*502/i.test(compact)) {
    return "外部服务或反向代理暂时返回 502，请稍后重试或进入人工复核。";
  }
  return compact.length > 500 ? `${compact.slice(0, 500)}...` : compact;
}

export function calculateZoneQuote(
  payload: ZoneQuoteRequest | ZoneQuoteWithNotifyRequest,
): Promise<ZoneQuoteResult> {
  return request<ZoneQuoteResult>("/quotes/zone-calculate", {
    method: "POST",
    body: JSON.stringify(payload),
  }, "quote");
}

export function getBackofficeActor(): Promise<CurrentActor> {
  return request<CurrentActor>("/auth/backoffice", {}, "admin");
}

export function login(payload: AuthLoginRequest): Promise<AuthLoginResponse> {
  return request<AuthLoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getCurrentActor(apiKeyScope: ApiKeyScope = "quote"): Promise<CurrentActor> {
  return request<CurrentActor>("/auth/me", {}, apiKeyScope);
}

export function listUsers(): Promise<UserPublic[]> {
  return request<UserPublic[]>("/users");
}

export function createUser(
  payload: Required<Pick<UserPayload, "username" | "password" | "role">> & UserPayload,
): Promise<UserPublic> {
  return request<UserPublic>("/users", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateUser(
  userId: number,
  payload: Omit<UserPayload, "username">,
): Promise<UserPublic> {
  return request<UserPublic>(`/users/${userId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function calculateAIAutoQuote(
  payload: AIAutoQuoteRequest,
  apiKeyScope: ApiKeyScope = "admin",
): Promise<AIAutoQuoteResponse> {
  return request<AIAutoQuoteResponse>("/quotes/ai-auto-quote", {
    method: "POST",
    body: JSON.stringify(payload),
  }, apiKeyScope);
}

export function verifyLocalAddress(params: {
  address_line?: string | null;
  postal_code?: string | null;
  city?: string | null;
  province?: string | null;
}): Promise<LocalAddressValidation> {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim()) {
      search.set(key, String(value));
    }
  });
  return request<LocalAddressValidation>(
    `/maps/local-verify${search.toString() ? `?${search.toString()}` : ""}`,
    {},
    "quote",
  );
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

export function listQuoteAudits(params: { limit?: number; query?: string } = {}): Promise<QuoteAuditLog[]> {
  const search = new URLSearchParams();
  if (params.limit) {
    search.set("limit", String(params.limit));
  }
  if (params.query?.trim()) {
    search.set("query", params.query.trim());
  }
  const query = search.toString();
  return request<QuoteAuditLog[]>(`/quotes/audits${query ? `?${query}` : ""}`);
}

export function getQuoteErrorSummary(limit = 20): Promise<QuoteErrorSummary> {
  return request<QuoteErrorSummary>(`/quotes/error-summary?limit=${encodeURIComponent(String(limit))}`);
}

export function listSalesQuoteRecords(params: {
  status?: "quoted" | "manual_required" | "";
  limit?: number;
} = {}): Promise<SalesQuoteRecord[]> {
  const search = new URLSearchParams();
  if (params.status) {
    search.set("status", params.status);
  }
  if (params.limit) {
    search.set("limit", String(params.limit));
  }
  const query = search.toString();
  return request<SalesQuoteRecord[]>(`/quotes/sales-records${query ? `?${query}` : ""}`, {}, "quote");
}

export function updateSalesQuoteManualPrice(
  recordId: number,
  payload: SalesQuoteManualPricePayload,
): Promise<SalesQuoteRecord> {
  return request<SalesQuoteRecord>(`/quotes/sales-records/${recordId}/manual-price`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function updateSalesQuoteManualPriceByQuoteId(
  quoteId: string,
  payload: SalesQuoteManualPricePayload,
): Promise<SalesQuoteRecord> {
  return request<SalesQuoteRecord>(
    `/quotes/sales-records/by-quote/${encodeURIComponent(quoteId)}/manual-price`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}

export function listHermesLearningCandidates(params: {
  status?: string;
  postal_prefix?: string;
  city?: string;
  province?: string;
  billing_pallets?: number | "";
  limit?: number;
} = {}): Promise<HermesLearningCandidate[]> {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  });
  const query = search.toString();
  return request<HermesLearningCandidate[]>(
    `/quotes/learning-candidates${query ? `?${query}` : ""}`,
  );
}

export function getHermesLearningCandidate(candidateId: number): Promise<HermesLearningCandidate> {
  return request<HermesLearningCandidate>(`/quotes/learning-candidates/${candidateId}`);
}

export function listHermesDiagnostics(params: {
  status?: string;
  quote_id?: string;
  limit?: number;
} = {}): Promise<HermesDiagnosticRecord[]> {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  });
  const query = search.toString();
  return request<HermesDiagnosticRecord[]>(
    `/quotes/hermes-diagnostics${query ? `?${query}` : ""}`,
  );
}

export function getHermesDiagnostic(diagnosticId: number): Promise<HermesDiagnosticRecord> {
  return request<HermesDiagnosticRecord>(`/quotes/hermes-diagnostics/${diagnosticId}`);
}

export function submitHermesDiagnosticSuggestion(
  diagnosticId: number,
  payload: HermesDiagnosticSuggestionPayload,
): Promise<HermesDiagnosticRecord> {
  return request<HermesDiagnosticRecord>(`/quotes/hermes-diagnostics/${diagnosticId}/suggestion`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function runHermesDiagnostic(diagnosticId: number): Promise<HermesDiagnosticRecord> {
  return request<HermesDiagnosticRecord>(`/quotes/hermes-diagnostics/${diagnosticId}/run`, {
    method: "POST",
  });
}

export function listBatchDiagnosticReports(): Promise<BatchDiagnosticReportSummary[]> {
  return request<BatchDiagnosticReportSummary[]>("/quotes/batch-diagnostic-reports");
}

export function getBatchDiagnosticReport(batchId: string): Promise<BatchDiagnosticReportDetail> {
  return request<BatchDiagnosticReportDetail>(
    `/quotes/batch-diagnostic-reports/${encodeURIComponent(batchId)}`,
  );
}

export function approveHermesLearningCandidate(
  candidateId: number,
  payload: HermesCandidateReviewPayload,
): Promise<HermesApproveResponse> {
  return request<HermesApproveResponse>(`/quotes/learning-candidates/${candidateId}/approve`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function rejectHermesLearningCandidate(
  candidateId: number,
  payload: HermesCandidateReviewPayload,
): Promise<HermesLearningCandidate> {
  return request<HermesLearningCandidate>(`/quotes/learning-candidates/${candidateId}/reject`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateLearnedQuoteRule(
  ruleId: number,
  payload: LearnedRuleUpdatePayload,
): Promise<LearnedQuoteRule> {
  return request<LearnedQuoteRule>(`/quotes/learned-rules/${ruleId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function getQuoteWorkbenchConfig(
  apiKeyScope: ApiKeyScope = "admin",
): Promise<QuoteWorkbenchConfig> {
  return request<QuoteWorkbenchConfig>("/quote-configs/workbench", {}, apiKeyScope);
}

export function updateQuoteWorkbenchConfig(
  payload: QuoteWorkbenchConfig,
): Promise<QuoteWorkbenchConfig> {
  return request<QuoteWorkbenchConfig>("/quote-configs/workbench", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function getZonePricingConfig(): Promise<ZonePricingConfig> {
  return request<ZonePricingConfig>("/quote-configs/zone-pricing");
}

export function updateZonePricingConfig(
  payload: ZonePricingConfig,
): Promise<ZonePricingConfig> {
  return request<ZonePricingConfig>("/quote-configs/zone-pricing", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function listZonePriceMatrix(params: {
  origin?: string;
  zone?: number | "";
  billing_pallets?: number | "";
  limit?: number;
  offset?: number;
} = {}): Promise<ZonePriceMatrixListResponse> {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  });
  const query = search.toString();
  return request<ZonePriceMatrixListResponse>(
    `/quote-configs/zone-price-matrix${query ? `?${query}` : ""}`,
  );
}

export function upsertZonePriceMatrix(
  payload: ZonePriceMatrixPayload,
): Promise<ZonePriceMatrixRecord> {
  return request<ZonePriceMatrixRecord>("/quote-configs/zone-price-matrix", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateZonePriceMatrix(
  recordId: number,
  payload: Partial<Pick<ZonePriceMatrixPayload, "base_price_usd" | "source" | "last_updated">>,
): Promise<ZonePriceMatrixRecord> {
  return request<ZonePriceMatrixRecord>(`/quote-configs/zone-price-matrix/${recordId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function previewZonePriceMatrixImport(file: File): Promise<ZonePriceImportPreview> {
  const body = new FormData();
  body.append("file", file);
  return request<ZonePriceImportPreview>("/imports/zone-price-matrix/preview", {
    method: "POST",
    body,
  });
}

export function importZonePriceMatrixSpreadsheet(file: File): Promise<ZonePriceImportResult> {
  const body = new FormData();
  body.append("file", file);
  return request<ZonePriceImportResult>("/imports/zone-price-matrix", {
    method: "POST",
    body,
  });
}

export function listAIConfigs(): Promise<AIModelConfigPublic[]> {
  return request<AIModelConfigPublic[]>("/ai-configs");
}

export function listAIProviderPresets(): Promise<AIProviderPreset[]> {
  return request<AIProviderPreset[]>("/ai-configs/provider-presets");
}

export function getAIAgentModelAssignment(
  agentKey: string,
): Promise<AIAgentModelAssignment> {
  return request<AIAgentModelAssignment>(`/ai-configs/agents/${agentKey}`);
}

export function setAIAgentModelAssignment(
  agentKey: string,
  configId: number,
): Promise<AIAgentModelAssignment> {
  return request<AIAgentModelAssignment>(`/ai-configs/agents/${agentKey}`, {
    method: "PUT",
    body: JSON.stringify({ config_id: configId }),
  });
}

export function createAIAgentModelConfig(
  agentKey: string,
  payload: Required<Pick<AIModelConfigPayload, "name" | "model_name">> & AIModelConfigPayload,
): Promise<AIAgentModelAssignment> {
  return request<AIAgentModelAssignment>(`/ai-configs/agents/${agentKey}/configs`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function discoverAIModels(
  payload: ModelDiscoveryRequest,
): Promise<ModelDiscoveryResult> {
  return request<ModelDiscoveryResult>("/ai-configs/discover-models", {
    method: "POST",
    body: JSON.stringify(payload),
  });
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

export function listWeComBots(
  apiKeyScope: ApiKeyScope = "admin",
): Promise<WeComBotConfigPublic[]> {
  return request<WeComBotConfigPublic[]>("/wecom/bots", {}, apiKeyScope);
}

export function createWeComBot(
  payload: Required<Pick<WeComBotConfigPayload, "name">> & WeComBotConfigPayload,
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

export function listEmailConfigs(
  apiKeyScope: ApiKeyScope = "admin",
): Promise<EmailConfigPublic[]> {
  return request<EmailConfigPublic[]>("/email/configs", {}, apiKeyScope);
}

export function createEmailConfig(
  payload: Required<Pick<EmailConfigPayload, "name" | "smtp_host" | "from_email" | "recipient_emails">> & EmailConfigPayload,
): Promise<EmailConfigPublic> {
  return request<EmailConfigPublic>("/email/configs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateEmailConfig(
  configId: number,
  payload: EmailConfigPayload,
): Promise<EmailConfigPublic> {
  return request<EmailConfigPublic>(`/email/configs/${configId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteEmailConfig(configId: number): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/email/configs/${configId}`, {
    method: "DELETE",
  });
}

export function setDefaultEmailConfig(configId: number): Promise<EmailConfigPublic> {
  return request<EmailConfigPublic>(`/email/configs/${configId}/set-default`, {
    method: "POST",
  });
}

export function testEmailConfig(configId: number): Promise<EmailTestResult> {
  return request<EmailTestResult>(`/email/configs/${configId}/test`, {
    method: "POST",
  });
}

export function listSearchConfigs(): Promise<SearchApiConfigPublic[]> {
  return request<SearchApiConfigPublic[]>("/search-configs");
}

export function createSearchConfig(
  payload: Required<Pick<SearchApiConfigPayload, "name" | "api_key">> & SearchApiConfigPayload,
): Promise<SearchApiConfigPublic> {
  return request<SearchApiConfigPublic>("/search-configs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateSearchConfig(
  configId: number,
  payload: SearchApiConfigPayload,
): Promise<SearchApiConfigPublic> {
  return request<SearchApiConfigPublic>(`/search-configs/${configId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteSearchConfig(configId: number): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/search-configs/${configId}`, {
    method: "DELETE",
  });
}

export function setDefaultSearchConfig(configId: number): Promise<SearchApiConfigPublic> {
  return request<SearchApiConfigPublic>(`/search-configs/${configId}/set-default`, {
    method: "POST",
  });
}

export function testSearchConfig(configId: number): Promise<SearchConfigTestResult> {
  return request<SearchConfigTestResult>(`/search-configs/${configId}/test`, {
    method: "POST",
  });
}

export function getApiBaseUrl(): string {
  return API_BASE_URL;
}

export function getStoredApiKey(scope: ApiKeyScope = "quote"): string {
  try {
    return window.localStorage.getItem(API_KEY_STORAGE_KEYS[scope]) ?? "";
  } catch {
    return "";
  }
}

export function setStoredApiKey(scope: ApiKeyScope, apiKey: string): void {
  window.localStorage.setItem(API_KEY_STORAGE_KEYS[scope], apiKey.trim());
}

export function clearStoredApiKey(scope: ApiKeyScope): void {
  window.localStorage.removeItem(API_KEY_STORAGE_KEYS[scope]);
}

export function getStoredAuthToken(): string {
  try {
    return window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setStoredAuthToken(token: string): void {
  window.localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token.trim());
}

export function clearStoredAuthToken(): void {
  window.localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
}
