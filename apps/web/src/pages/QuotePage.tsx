import { useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";
import {
  calculateAIAutoQuote,
  clearStoredApiKey,
  getStoredApiKey,
  getQuoteWorkbenchConfig,
  listEmailConfigs,
  setStoredApiKey,
  type AIExtractedQuoteDraft,
  type AIAutoQuoteResponse,
  type AddressType,
  type EmailConfigPublic,
  type PackagingType,
  type QuoteSearchContext,
  type QuoteWorkbenchConfig,
  type ZoneQuoteResult,
} from "../api/client";
import AiQuoteInputPanel from "../components/AiQuoteInputPanel";
import ParsedAddressCard from "../components/ParsedAddressCard";
import ParsedCargoTable from "../components/ParsedCargoTable";
import QuoteCalculationPanel from "../components/QuoteCalculationPanel";
import QuoteRiskPanel from "../components/QuoteRiskPanel";
import { parseQuoteInput, type ParsedQuoteInput } from "../utils/quoteParser";

type WorkbenchStatus =
  | "idle"
  | "parsing"
  | "parsed"
  | "quoting"
  | "quoted"
  | "manual_required";

type QuoteThemeMode = "dark" | "light";

const QUOTE_THEME_STORAGE_KEY = "canada-final-mile-quote-theme-v2";

export default function QuotePage({ adminHref }: { adminHref: string }) {
  const [config, setConfig] = useState<QuoteWorkbenchConfig | null>(null);
  const [rawInput, setRawInput] = useState("");
  const [result, setResult] = useState<ZoneQuoteResult | null>(null);
  const [aiResult, setAiResult] = useState<AIAutoQuoteResponse | null>(null);
  const [status, setStatus] = useState<WorkbenchStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [packagingType, setPackagingType] = useState<PackagingType | "">("");
  const [addressType, setAddressType] = useState<AddressType | "">("");
  const [services, setServices] = useState<Record<string, boolean>>({});
  const [detentionMinutes, setDetentionMinutes] = useState(0);
  const [emailConfigs, setEmailConfigs] = useState<EmailConfigPublic[]>([]);
  const [notifyEmail, setNotifyEmail] = useState(false);
  const [selectedEmailConfigId, setSelectedEmailConfigId] = useState("");
  const [apiKeyInput, setApiKeyInput] = useState(() => getStoredApiKey("quote"));
  const [hasApiKey, setHasApiKey] = useState(() => Boolean(getStoredApiKey("quote")));
  const [themeMode, setThemeMode] = useState<QuoteThemeMode>(() => readQuoteThemeMode());

  useEffect(() => {
    void loadConfig();
    void loadEmailConfigs();
  }, []);

  useEffect(() => {
    window.localStorage.setItem(QUOTE_THEME_STORAGE_KEY, themeMode);
  }, [themeMode]);

  async function loadConfig() {
    setError(null);
    try {
      const nextConfig = await getQuoteWorkbenchConfig("quote");
      setConfig(nextConfig);
      setPackagingType(nextConfig.defaults.packaging_type);
      setAddressType(nextConfig.defaults.address_type);
      setDetentionMinutes(nextConfig.defaults.detention_minutes);
      setNotifyEmail(nextConfig.defaults.notify_wecom);
      setServices(
        Object.fromEntries(
          nextConfig.service_options.map((option) => [
            option.value,
            Boolean(
              nextConfig.defaults[
                option.value as keyof typeof nextConfig.defaults
              ],
            ),
          ]),
        ),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "报价工作台配置加载失败");
    }
  }

  async function loadEmailConfigs() {
    try {
      setEmailConfigs(await listEmailConfigs("quote"));
    } catch {
      setEmailConfigs([]);
    }
  }

  const parsed = useMemo(
    () => (config ? parseQuoteInput(rawInput, config) : null),
    [config, rawInput],
  );
  const effectiveParsed = useMemo(
    () =>
      config
        ? aiResult && parsed
          ? mergeParsedWithAIExtraction(parsed, aiResult.extraction, config)
          : buildEmptyParsedQuoteInput(config)
        : parsed,
    [aiResult, config, parsed],
  );

  const statusLabel = config?.status_labels[status] ?? status;
  const manualRequired = Boolean(result?.manual_review_required) || status === "manual_required";
  const riskMessages = useMemo(
    () =>
      config && effectiveParsed
        ? buildRiskMessages(config, effectiveParsed, result, manualRequired, aiResult)
        : [],
    [aiResult, config, effectiveParsed, result, manualRequired],
  );
  const salesText = useMemo(
    () =>
      aiResult?.customer_reply && aiResult.manual_review_required === false
        ? aiResult.customer_reply
        : aiResult && config && effectiveParsed
          ? buildSalesText(config, effectiveParsed, result)
          : "",
    [aiResult, config, effectiveParsed, result],
  );

  function updateRawInput(value: string) {
    setRawInput(value);
    setResult(null);
    setAiResult(null);
    setNotice(null);
    setError(null);
    setStatus("idle");
  }

  async function handleSmartQuote() {
    if (!config) {
      setError("后台配置尚未加载完成");
      return;
    }
    if (!rawInput.trim()) {
      setError("请先粘贴报价信息");
      setStatus("idle");
      return;
    }

    setStatus("parsing");
    setError(null);
    setNotice(null);

    setIsSubmitting(true);
    setStatus("quoting");
    try {
      const response = await calculateAIAutoQuote(
        {
          customer_message: buildAugmentedAIMessage(rawInput.trim(), {
            packagingType,
            addressType,
            services,
            detentionMinutes,
          }),
          auto_submit_when_complete: true,
          notify_email: notifyEmail,
          email_config_id: selectedEmailConfigId ? Number(selectedEmailConfigId) : null,
          enable_search_context: true,
        },
        "quote",
      );
      setAiResult(response);
      applyAIExtractionToControls(response.extraction, {
        setPackagingType,
        setAddressType,
        setServices,
        setDetentionMinutes,
      });
      setResult(response.quote_result);
      if (response.manual_review_required || response.quote_result?.manual_review_required) {
        setStatus("manual_required");
        setNotice(
          response.missing_fields.length
            ? `AI 已解析，但缺少 ${formatMissingFields(response.missing_fields).join("、")}；已进入人工任务池。`
            : "该票已进入人工确认流程，请勿直接发送客户报价。",
        );
      } else {
        setStatus("quoted");
      }
    } catch (caught) {
      setStatus("manual_required");
      setError(
        caught instanceof Error
          ? `${caught.message}。请检查后台 AI 模型配置和搜索配置，或进入人工任务池处理。`
          : "AI 智能报价请求失败，请进入人工任务池处理。",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  function clearInput() {
    setRawInput("");
    setResult(null);
    setAiResult(null);
    setError(null);
    setNotice(null);
    setStatus("idle");
  }

  function handleImportText(value: string) {
    if (!value) {
      setError("Excel 文件请走后台导入模块；当前工作台只读取文本或 CSV 内容。");
      return;
    }
    updateRawInput(value);
  }

  function exportQuote() {
    if (!salesText.trim()) {
      return;
    }
    const blob = new Blob([salesText], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `canada-final-mile-quote-${result?.quote_id ?? "draft"}.txt`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  async function saveAccessKeyAndRetry() {
    setStoredApiKey("quote", apiKeyInput);
    setHasApiKey(Boolean(apiKeyInput.trim()));
    await loadConfig();
    void loadEmailConfigs();
  }

  function clearAccessKey() {
    clearStoredApiKey("quote");
    setApiKeyInput("");
    setHasApiKey(false);
    setConfig(null);
  }

  if (!config || !parsed) {
    return (
      <div className={`ai-quote-workbench ai-quote-compact ai-theme-${themeMode} min-h-dvh px-3 py-3 sm:px-4`}>
        <section className="ai-glass-panel mx-auto grid max-w-3xl gap-4 p-5">
          <div className="flex items-start justify-between gap-3">
            <h1 className="text-2xl font-semibold text-white">加拿大尾端 AI 报价系统</h1>
            <ThemeToggle
              themeMode={themeMode}
              onToggle={() => setThemeMode((current) => (current === "dark" ? "light" : "dark"))}
            />
          </div>
          <p className="mt-3 text-sm leading-6 text-slate-300">
            {error ? `配置加载失败：${error}` : "正在读取后台配置..."}
          </p>
          {error?.includes("X-API-Key") && (
            <div className="rounded-md border border-amber-300/40 bg-amber-300/10 px-4 py-3 text-sm leading-6 text-amber-50">
              请先输入访问密钥。保存后系统会自动重新读取后台配置。
            </div>
          )}
          <AccessKeyBox
            apiKeyInput={apiKeyInput}
            hasApiKey={hasApiKey}
            onChange={setApiKeyInput}
            onSave={() => {
              void saveAccessKeyAndRetry();
            }}
            onClear={clearAccessKey}
            title="前台访问密钥"
            placeholder={hasApiKey ? "前台 Key 已保存" : "输入前台 API Key"}
            forceOpen
          />
          <div className="flex flex-wrap gap-3">
            <button className="ai-primary-button" type="button" onClick={loadConfig}>
              重新加载配置
            </button>
            <a className="ai-secondary-button" href={adminHref}>
              后台登录
            </a>
          </div>
        </section>
      </div>
    );
  }

  const displayParsed = effectiveParsed ?? parsed;

  return (
    <div className={`logistics-site ai-quote-workbench ai-quote-compact ai-theme-${themeMode} min-h-dvh`}>
      <main id="top">
        <section className="logistics-quote-section logistics-quote-section-direct" id="quote-workbench">
          <div className="logistics-section-heading">
            <p>AI Quote Workbench</p>
            <h2>{config.title}</h2>
            <span>{config.subtitle}</span>
          </div>

          <div className="logistics-workbench-toolbar">
            <AccessKeyBox
              apiKeyInput={apiKeyInput}
              hasApiKey={hasApiKey}
              onChange={setApiKeyInput}
              onSave={() => {
                void saveAccessKeyAndRetry();
              }}
              onClear={clearAccessKey}
              title="前台访问密钥"
              placeholder={hasApiKey ? "前台 Key 已保存" : "输入前台 API Key"}
            />
            <a className="ai-secondary-button" href={adminHref}>
              后台登录
            </a>
            <ThemeToggle
              themeMode={themeMode}
              onToggle={() => setThemeMode((current) => (current === "dark" ? "light" : "dark"))}
            />
            <span
              className={`logistics-status-pill ${
                manualRequired ? "logistics-status-warning" : "logistics-status-ready"
              }`}
            >
              {statusLabel}
            </span>
          </div>

          {error && (
            <div className="logistics-alert logistics-alert-error" role="alert">
              {error}
            </div>
          )}
          {notice && (
            <div className="logistics-alert logistics-alert-warning" role="status">
              {notice}
            </div>
          )}

          <div className="logistics-workbench-grid">
            <div className="grid min-w-0 content-start gap-3">
              <AiQuoteInputPanel
                config={config}
                value={rawInput}
                statusLabel={statusLabel}
                isQuoting={isSubmitting}
                onChange={updateRawInput}
                onSubmit={handleSmartQuote}
                onClear={clearInput}
                onImportText={handleImportText}
              />
              <NotificationPanel
                configs={emailConfigs}
                notifyEmail={notifyEmail}
                selectedConfigId={selectedEmailConfigId}
                onNotifyChange={setNotifyEmail}
                onConfigChange={setSelectedEmailConfigId}
              />
            </div>

            <div className="grid min-w-0 content-start gap-3">
              <QuotePipelinePanel
                hasAIResult={Boolean(aiResult)}
                hasSearchContext={Boolean(aiResult?.search_context)}
                manualRequired={manualRequired}
                extractionConfidence={aiResult?.extraction.confidence ?? displayParsed.confidence}
              />
              <div className="grid min-w-0 items-start gap-3 xl:grid-cols-[minmax(0,1.08fr)_minmax(300px,0.92fr)]">
                <div className="grid min-w-0 content-start gap-3">
                  <ParsedCargoTable parsed={displayParsed} isAwaitingAI={!aiResult} />
                  <ParsedAddressCard
                    parsed={displayParsed}
                    config={config}
                    packagingType={packagingType}
                    onPackagingTypeChange={(value) => setPackagingType(value as PackagingType)}
                    addressType={addressType}
                    onAddressTypeChange={(value) => setAddressType(value as AddressType)}
                    services={services}
                    onServiceChange={(key, checked) =>
                      setServices((current) => ({ ...current, [key]: checked }))
                    }
                    detentionMinutes={detentionMinutes}
                    onDetentionMinutesChange={setDetentionMinutes}
                  />
                </div>

                <div className="grid min-w-0 content-start gap-3">
                  <QuoteCalculationPanel
                    config={config}
                    parsed={displayParsed}
                    result={result}
                    aiParsed={Boolean(aiResult)}
                    salesText={salesText}
                    onExport={exportQuote}
                  />
                  <QuoteRiskPanel risks={riskMessages} manualRequired={manualRequired} />
                  {aiResult?.search_context && (
                    <SearchVerificationPanel searchContext={aiResult.search_context} />
                  )}
                </div>
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}

function QuotePipelinePanel({
  hasAIResult,
  hasSearchContext,
  manualRequired,
  extractionConfidence,
}: {
  hasAIResult: boolean;
  hasSearchContext: boolean;
  manualRequired: boolean;
  extractionConfidence: number;
}) {
  const steps = [
    { label: "本地预览", status: "已启用" },
    { label: "AI 解析", status: hasAIResult ? `完成 ${extractionConfidence}%` : "待提交" },
    { label: "搜索验证", status: hasAIResult ? (hasSearchContext ? "已返回参考" : "未返回参考") : "提交后验证" },
    { label: "规则报价", status: hasAIResult ? (manualRequired ? "需人工复核" : "已完成") : "待执行" },
  ];

  return (
    <section className="ai-glass-panel p-4">
      <div className="grid grid-cols-2 gap-2 xl:grid-cols-4">
        {steps.map((step) => (
          <div key={step.label} className="rounded-md border border-white/10 bg-white/[0.04] px-2.5 py-2">
            <p className="text-xs font-semibold text-slate-400">{step.label}</p>
            <p className="mt-1 text-sm font-semibold text-cyan-100">{step.status}</p>
          </div>
        ))}
      </div>
      <p className="mt-2 text-xs leading-5 text-slate-400">
        搜索结果只用于确认地址情况，不能覆盖 Zone 价格表和 Quote Engine 金额。
      </p>
    </section>
  );
}

function ThemeToggle({
  themeMode,
  onToggle,
}: {
  themeMode: QuoteThemeMode;
  onToggle: () => void;
}) {
  return (
    <button
      className="ai-theme-toggle"
      type="button"
      onClick={onToggle}
      aria-label={themeMode === "dark" ? "切换到白色主题" : "切换到黑色主题"}
    >
      {themeMode === "dark" ? "白色模式" : "黑色模式"}
    </button>
  );
}

function AccessKeyBox({
  apiKeyInput,
  hasApiKey,
  onChange,
  onSave,
  onClear,
  title = "访问密钥",
  placeholder,
  forceOpen = false,
}: {
  apiKeyInput: string;
  hasApiKey: boolean;
  onChange: (value: string) => void;
  onSave: () => void;
  onClear: () => void;
  title?: string;
  placeholder?: string;
  forceOpen?: boolean;
}) {
  return (
    <details
      className="ai-access-key rounded-md border border-white/15 bg-white/[0.05] p-2 text-sm text-slate-100"
      open={forceOpen || undefined}
    >
      <summary className="flex min-h-9 cursor-pointer list-none items-center justify-between gap-3 px-2 font-semibold">
        {title}
        <span className="text-xs text-cyan-100/70">{hasApiKey ? "已保存" : "未保存"}</span>
      </summary>
      <form
        className="mt-3 grid gap-2 sm:min-w-72"
        onSubmit={(event) => {
          event.preventDefault();
          onSave();
        }}
      >
        <label>
          <span className="sr-only">X-API-Key</span>
          <input
            className="ai-input"
            type="password"
            value={apiKeyInput}
            onChange={(event) => onChange(event.target.value)}
            placeholder={placeholder ?? (hasApiKey ? "已保存" : "输入 X-API-Key")}
            autoComplete="off"
          />
        </label>
        <div className="grid grid-cols-2 gap-2">
          <button className="ai-primary-button min-h-10 py-1" type="submit">
            保存
          </button>
          <button className="ai-secondary-button min-h-10 py-1" type="button" onClick={onClear}>
            清除
          </button>
        </div>
      </form>
    </details>
  );
}

function NotificationPanel({
  configs,
  notifyEmail,
  selectedConfigId,
  onNotifyChange,
  onConfigChange,
}: {
  configs: EmailConfigPublic[];
  notifyEmail: boolean;
  selectedConfigId: string;
  onNotifyChange: (value: boolean) => void;
  onConfigChange: (value: string) => void;
}) {
  return (
    <section className="ai-glass-panel p-4">
      <label className="flex min-h-11 items-center gap-3 text-sm font-semibold text-slate-100">
        <input
          className="h-4 w-4 rounded border-cyan-200 bg-slate-950 text-cyan-400 focus:ring-cyan-300"
          type="checkbox"
          checked={notifyEmail}
          onChange={(event) => onNotifyChange(event.target.checked)}
        />
        报价完成后发送邮件
      </label>
      <label className="mt-3 block">
        <span className="text-xs font-semibold text-slate-300">邮件通知配置</span>
        <select
          className="ai-select mt-2"
          value={selectedConfigId}
          onChange={(event) => onConfigChange(event.target.value)}
          disabled={!notifyEmail}
        >
          <option value="">使用后台默认邮箱</option>
          {configs.map((config) => (
            <option key={config.id} value={config.id}>
              {config.name} / {config.purpose}
              {config.is_default ? " / 默认" : ""}
            </option>
          ))}
        </select>
      </label>
    </section>
  );
}

function buildEmptyParsedQuoteInput(config: QuoteWorkbenchConfig): ParsedQuoteInput {
  return {
    cargo_items: [],
    piece_count: 0,
    total_cbm: 0,
    total_weight_kg: 0,
    density_kg_per_cbm: null,
    max_dimensions_cm: null,
    longest_side_cm: null,
    heaviest_piece_kg: null,
    address: {
      address_line: null,
      city: null,
      province_code: null,
      province_name: null,
      postal_code: null,
      country: config.parser.default_country,
    },
    missing_fields: [],
    risk_hints: [],
    confidence: 0,
  };
}

function buildRiskMessages(
  config: QuoteWorkbenchConfig,
  parsed: ParsedQuoteInput,
  result: ZoneQuoteResult | null,
  manualRequired: boolean,
  aiResult: AIAutoQuoteResponse | null,
): string[] {
  if (!aiResult) {
    return ["待提交给后台大模型解析；本地预览不再作为最终字段来源。"];
  }
  const backendRisks =
    result?.risk_tags.map((tag) => config.backend_risk_tag_labels[tag] || tag) ?? [];
  const manualRisk = manualRequired ? ["需要人工确认，不要直接发客户。"] : [];
  const aiMissingRisks =
    aiResult?.missing_fields.map((field) => `AI 解析缺少：${formatMissingField(field)}`) ?? [];
  const searchRisks = aiResult ? searchContextToRiskMessages(aiResult.search_context) : [];
  return Array.from(new Set([...manualRisk, ...parsed.risk_hints, ...backendRisks, ...aiMissingRisks, ...searchRisks]));
}

function buildSalesText(
  config: QuoteWorkbenchConfig,
  parsed: ParsedQuoteInput,
  result: ZoneQuoteResult | null,
): string {
  const destination = [
    parsed.address.address_line,
    parsed.address.city,
    parsed.address.province_name || parsed.address.province_code,
    parsed.address.country,
    parsed.address.postal_code,
  ]
    .filter(Boolean)
    .join(", ");
  const maxDimensions = parsed.max_dimensions_cm
    ? `${parsed.max_dimensions_cm.join(" × ")} cm`
    : "待确认";
  const totalPrice =
    result?.total_price_usd && !result.manual_review_required
      ? `${config.copy_template.currency_code} ${Number(result.total_price_usd).toFixed(2)}`
      : config.copy_template.manual_price_text;

  return [
    "加拿大尾端派送报价如下：",
    `目的地：${destination || "待确认"}`,
    `货物数据：共 ${parsed.piece_count || "待确认"} 件，约 ${parsed.total_cbm ? parsed.total_cbm.toFixed(3) : "待确认"} CBM，${parsed.total_weight_kg ? parsed.total_weight_kg.toFixed(1) : "待确认"} KG`,
    `最大单件：${maxDimensions}`,
    `计费密度：${parsed.density_kg_per_cbm !== null ? `约 ${parsed.density_kg_per_cbm.toFixed(1)} KG/CBM` : "待确认"}`,
    `报价合计：${totalPrice}`,
    "费用包含：",
    ...config.copy_template.included_items.map((item) => `- ${item}`),
    "费用不含：",
    ...config.copy_template.excluded_items.map((item) => `- ${item}`),
    "备注：",
    config.copy_template.remark,
    `报价有效期：${config.copy_template.valid_days} 天`,
  ].join("\n");
}

function buildAugmentedAIMessage(
  rawInput: string,
  options: {
    packagingType: PackagingType | "";
    addressType: AddressType | "";
    services: Record<string, boolean>;
    detentionMinutes: number;
  },
): string {
  const confirmedLines = [
    "前台已确认字段，仅用于字段提取，不允许 AI 计算价格：",
    options.packagingType ? `packaging_type=${options.packagingType}` : "",
    options.addressType ? `address_type=${options.addressType}` : "",
    `requires_liftgate=${Boolean(options.services.requires_liftgate)}`,
    `requires_pallet_jack=${Boolean(options.services.requires_pallet_jack)}`,
    `requires_appointment=${Boolean(options.services.requires_appointment)}`,
    `detention_minutes=${Math.max(0, options.detentionMinutes || 0)}`,
  ].filter(Boolean);
  return `${rawInput}\n\n---\n${confirmedLines.join("\n")}`;
}

function mergeParsedWithAIExtraction(
  parsed: ParsedQuoteInput,
  extraction: AIExtractedQuoteDraft | null,
  config: QuoteWorkbenchConfig,
): ParsedQuoteInput {
  if (!extraction) {
    return parsed;
  }
  const totalCbm = toNumber(extraction.cbm) ?? parsed.total_cbm;
  const totalWeight = toNumber(extraction.weight_kg) ?? parsed.total_weight_kg;
  const density = totalCbm > 0 && totalWeight > 0 ? round1(totalWeight / totalCbm) : parsed.density_kg_per_cbm;
  const provinceCode = extraction.province || parsed.address.province_code;
  const province = config.provinces.find((item) => item.code.toLowerCase() === String(provinceCode ?? "").toLowerCase());

  return {
    ...parsed,
    piece_count: extraction.piece_count ?? parsed.piece_count,
    total_cbm: totalCbm,
    total_weight_kg: totalWeight,
    density_kg_per_cbm: density,
    longest_side_cm: toNumber(extraction.longest_side_cm) ?? parsed.longest_side_cm,
    max_dimensions_cm: parsed.max_dimensions_cm,
    address: {
      address_line: extraction.address_line || parsed.address.address_line,
      city: extraction.city || parsed.address.city,
      province_code: province?.code ?? provinceCode ?? parsed.address.province_code,
      province_name: province?.name ?? parsed.address.province_name,
      postal_code: extraction.postal_code || parsed.address.postal_code,
      country: parsed.address.country,
    },
    missing_fields: extraction.missing_fields.length
      ? formatMissingFields(extraction.missing_fields)
      : parsed.missing_fields,
    confidence: extraction.confidence || parsed.confidence,
  };
}

function applyAIExtractionToControls(
  extraction: AIExtractedQuoteDraft,
  setters: {
    setPackagingType: (value: PackagingType | "") => void;
    setAddressType: (value: AddressType | "") => void;
    setServices: Dispatch<SetStateAction<Record<string, boolean>>>;
    setDetentionMinutes: (value: number) => void;
  },
) {
  if (isPackagingType(extraction.packaging_type)) {
    setters.setPackagingType(extraction.packaging_type);
  }
  if (isAddressType(extraction.address_type)) {
    setters.setAddressType(extraction.address_type);
  }
  setters.setServices((current) => ({
    ...current,
    requires_liftgate: extraction.requires_liftgate || current.requires_liftgate,
    requires_pallet_jack: extraction.requires_pallet_jack || current.requires_pallet_jack,
    requires_appointment: extraction.requires_appointment || current.requires_appointment,
  }));
  setters.setDetentionMinutes(extraction.detention_minutes || 0);
}

function SearchVerificationPanel({ searchContext }: { searchContext: QuoteSearchContext }) {
  const summary = summarizeAddressSearch(searchContext);

  return (
    <section className="ai-glass-panel p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase text-cyan-200">搜索验证</p>
          <h2 className="mt-1 text-lg font-semibold text-white">地址情况确认</h2>
        </div>
        <span className="shrink-0 rounded-full border border-cyan-300/40 bg-cyan-300/10 px-2.5 py-1 text-xs font-semibold text-cyan-100">
          {searchContext.provider}
        </span>
      </div>
      <p className="mt-2 text-xs leading-5 text-slate-400">
        {searchContext.note}
      </p>
      <div className="mt-3 rounded-md border border-white/10 bg-white/[0.04] p-3">
        <h3 className="text-sm font-semibold text-white">地址情况</h3>
        {summary.error ? (
          <p className="mt-2 rounded-md border border-red-300/40 bg-red-500/10 p-2 text-sm leading-6 text-red-100">
            {summary.text}
          </p>
        ) : (
          <p className="mt-2 text-sm leading-6 text-slate-300">
            {summary.text}
          </p>
        )}
        <p className="mt-2 text-xs leading-5 text-slate-400">
          搜索结果只作为人工判断线索，不会改变系统报价金额。
        </p>
      </div>
    </section>
  );
}

function summarizeAddressSearch(searchContext: QuoteSearchContext): { text: string; error: boolean } {
  const evidence = searchContext.address_research;
  if (!evidence) {
    return { text: "后台未返回地址搜索验证，请人工确认地址类型和派送条件。", error: false };
  }
  if (evidence.error) {
    return { text: `搜索失败：${evidence.error}`, error: true };
  }
  return {
    text:
      evidence.summary_zh ||
      evidence.answer ||
      "搜索已返回，但未生成明确中文结论，请人工确认地址类型、偏远情况和卸货条件。",
    error: false,
  };
}

function searchContextToRiskMessages(searchContext: QuoteSearchContext | null): string[] {
  if (!searchContext) {
    return ["后台未返回地址搜索验证；如需地址确认，请检查搜索 API 配置。"];
  }
  const risks: string[] = ["已调用地址搜索验证，结果只作为地址确认参考，不参与金额计算。"];
  if (searchContext.address_research?.error) {
    risks.push("地址搜索验证失败，请人工确认地址类型和偏远情况。");
  }
  return risks;
}

function formatMissingFields(fields: string[]): string[] {
  return fields.map(formatMissingField);
}

function formatMissingField(field: string): string {
  const labels: Record<string, string> = {
    postal_code: "加拿大邮编",
    cbm: "总体积 CBM",
    weight_kg: "总重量 KG",
    piece_count: "件数",
    packaging_type: "包装类型",
    address_type: "地址类型",
    city: "城市",
    province: "省份",
  };
  return labels[field] || field;
}

function isPackagingType(value: string | null): value is PackagingType {
  return Boolean(
    value &&
      ["carton", "wooden_crate", "pallet", "woven_bag", "flexible_packaging", "unknown"].includes(value),
  );
}

function isAddressType(value: string | null): value is AddressType {
  return Boolean(value && ["commercial", "residential", "private", "rural_residential"].includes(value));
}

function toNumber(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : null;
}

function round1(value: number): number {
  return Math.round(value * 10) / 10;
}

function readQuoteThemeMode(): QuoteThemeMode {
  if (typeof window === "undefined") {
    return "light";
  }
  const stored = window.localStorage.getItem(QUOTE_THEME_STORAGE_KEY);
  return stored === "dark" ? "dark" : "light";
}
