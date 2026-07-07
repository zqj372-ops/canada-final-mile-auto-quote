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
  type MoneyValue,
  type PackagingType,
  type QuoteSearchContext,
  type QuoteWorkbenchConfig,
  type ZoneQuoteResult,
} from "../api/client";
import AiQuoteInputPanel from "../components/AiQuoteInputPanel";
import ParsedAddressCard from "../components/ParsedAddressCard";
import ParsedCargoTable from "../components/ParsedCargoTable";
import QuoteCopyButton from "../components/QuoteCopyButton";
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
type SalesQuoteTab = "quote" | "records";
type SalesQuoteRecordStatus = "quoted" | "manual_required";
type SalesQuoteRecordFilter = SalesQuoteRecordStatus | "all";

interface SalesQuoteRecord {
  id: string;
  quote_id: string;
  created_at: string;
  status: SalesQuoteRecordStatus;
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
  missing_fields: string[];
  manual_reason: string | null;
}

const QUOTE_THEME_STORAGE_KEY = "canada-final-mile-quote-theme-v2";
const SALES_QUOTE_RECORDS_STORAGE_KEY = "canada-final-mile-sales-quote-records-v1";
const SALES_QUOTE_RECORD_LIMIT = 80;

export default function QuotePage({ adminHref: _adminHref }: { adminHref: string }) {
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
  const [activeSalesTab, setActiveSalesTab] = useState<SalesQuoteTab>("quote");
  const [quoteRecords, setQuoteRecords] = useState<SalesQuoteRecord[]>(() => readSalesQuoteRecords());
  const [recordFilter, setRecordFilter] = useState<SalesQuoteRecordFilter>("all");
  const [recordQuery, setRecordQuery] = useState("");
  const [selectedRecordId, setSelectedRecordId] = useState<string | null>(null);

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
      const nextParsed = mergeParsedWithAIExtraction(
        parseQuoteInput(rawInput.trim(), config),
        response.extraction,
        config,
      );
      const nextRecord = buildSalesQuoteRecord({
        config,
        customerMessage: rawInput.trim(),
        parsed: nextParsed,
        response,
      });
      setQuoteRecords((current) => {
        const nextRecords = upsertSalesQuoteRecord(current, nextRecord);
        persistSalesQuoteRecords(nextRecords);
        return nextRecords;
      });
      setSelectedRecordId(nextRecord.id);
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
          <div className="mb-3 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-wide text-cyan-700">
                销售前台
              </p>
              <h1 className="mt-1 text-2xl font-bold text-slate-950 sm:text-3xl">
                {config.title}
              </h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
                {config.subtitle} 销售端只保留新建报价和本机报价记录；人工复核、规则配置和审计由后台处理。
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
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
          </div>

          <div className="mb-3 flex flex-wrap gap-2">
            <button
              className={activeSalesTab === "quote" ? "ai-primary-button" : "ai-secondary-button"}
              type="button"
              onClick={() => setActiveSalesTab("quote")}
            >
              新建报价
            </button>
            <button
              className={activeSalesTab === "records" ? "ai-primary-button" : "ai-secondary-button"}
              type="button"
              onClick={() => setActiveSalesTab("records")}
            >
              报价记录 ({quoteRecords.length})
            </button>
          </div>

          {activeSalesTab === "quote" && error && (
            <div className="logistics-alert logistics-alert-error" role="alert">
              {error}
            </div>
          )}
          {activeSalesTab === "quote" && notice && (
            <div className="logistics-alert logistics-alert-warning" role="status">
              {notice}
            </div>
          )}

          {activeSalesTab === "quote" ? (
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
          ) : (
            <SalesQuoteRecordsPanel
              filter={recordFilter}
              query={recordQuery}
              records={quoteRecords}
              selectedRecordId={selectedRecordId}
              onClearRecords={() => {
                setQuoteRecords([]);
                setSelectedRecordId(null);
                persistSalesQuoteRecords([]);
              }}
              onFilterChange={setRecordFilter}
              onNewQuote={() => setActiveSalesTab("quote")}
              onQueryChange={setRecordQuery}
              onSelectRecord={setSelectedRecordId}
            />
          )}
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

function SalesQuoteRecordsPanel({
  filter,
  query,
  records,
  selectedRecordId,
  onClearRecords,
  onFilterChange,
  onNewQuote,
  onQueryChange,
  onSelectRecord,
}: {
  filter: SalesQuoteRecordFilter;
  query: string;
  records: SalesQuoteRecord[];
  selectedRecordId: string | null;
  onClearRecords: () => void;
  onFilterChange: (value: SalesQuoteRecordFilter) => void;
  onNewQuote: () => void;
  onQueryChange: (value: string) => void;
  onSelectRecord: (id: string) => void;
}) {
  const visibleRecords = useMemo(
    () => filterSalesQuoteRecords(records, filter, query),
    [filter, query, records],
  );
  const selectedRecord =
    visibleRecords.find((record) => record.id === selectedRecordId) ?? visibleRecords[0] ?? null;
  const counts = countSalesQuoteRecords(records);

  return (
    <section className="ai-glass-panel p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase text-cyan-200">销售记录</p>
          <h2 className="mt-1 text-xl font-semibold text-white">报价记录</h2>
          <p className="mt-1 text-sm leading-6 text-slate-400">
            记录保存在当前浏览器，用于销售回查自己提交过的报价；人工复核状态以后台处理结果为准。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="ai-primary-button" type="button" onClick={onNewQuote}>
            新建报价
          </button>
          <button
            className="ai-secondary-button"
            type="button"
            onClick={onClearRecords}
            disabled={records.length === 0}
          >
            清空记录
          </button>
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(220px,0.8fr)_minmax(0,1.2fr)]">
        <div className="grid gap-3">
          <div className="grid gap-3 rounded-md border border-white/10 bg-white/[0.04] p-3">
            <label>
              <span className="text-xs font-semibold text-slate-300">搜索记录</span>
              <input
                className="ai-input mt-2"
                value={query}
                onChange={(event) => onQueryChange(event.target.value)}
                placeholder="quote_id / 邮编 / 城市 / 原始询价"
              />
            </label>
            <div className="flex flex-wrap gap-2" role="tablist" aria-label="报价记录筛选">
              {(["all", "quoted", "manual_required"] as SalesQuoteRecordFilter[]).map((item) => (
                <button
                  key={item}
                  className={filter === item ? "ai-primary-button" : "ai-secondary-button"}
                  type="button"
                  onClick={() => onFilterChange(item)}
                >
                  {salesRecordFilterLabel(item, counts)}
                </button>
              ))}
            </div>
          </div>

          <div className="max-h-[640px] overflow-auto rounded-md border border-white/10">
            {visibleRecords.length ? (
              visibleRecords.map((record) => {
                const isSelected = selectedRecord?.id === record.id;
                return (
                  <button
                    key={record.id}
                    className={`grid w-full gap-2 border-b border-white/10 px-3 py-3 text-left transition hover:bg-cyan-300/10 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-cyan-200 ${
                      isSelected ? "bg-cyan-300/10" : "bg-white/[0.02]"
                    }`}
                    type="button"
                    onClick={() => onSelectRecord(record.id)}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <span className="min-w-0 break-all text-sm font-semibold text-white">
                        {record.quote_id}
                      </span>
                      <SalesRecordStatusBadge status={record.status} />
                    </div>
                    <p className="line-clamp-2 text-sm leading-5 text-slate-300">
                      {record.destination}
                    </p>
                    <div className="grid grid-cols-2 gap-2 text-xs text-slate-400">
                      <span>{formatRecordDate(record.created_at)}</span>
                      <span className="text-right font-semibold text-cyan-100">
                        {formatRecordMoney(record)}
                      </span>
                    </div>
                  </button>
                );
              })
            ) : (
              <div className="grid min-h-52 place-items-center p-5 text-center">
                <div>
                  <h3 className="text-base font-semibold text-white">暂无报价记录</h3>
                  <p className="mt-2 text-sm leading-6 text-slate-400">
                    完成一次报价后，系统会自动把结果保存到这里。
                  </p>
                  <button className="ai-primary-button mt-4" type="button" onClick={onNewQuote}>
                    去报价
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>

        <SalesQuoteRecordDetail record={selectedRecord} />
      </div>
    </section>
  );
}

function SalesQuoteRecordDetail({ record }: { record: SalesQuoteRecord | null }) {
  if (!record) {
    return (
      <div className="rounded-md border border-white/10 bg-white/[0.04] p-5 text-sm text-slate-400">
        选择左侧记录后查看报价详情。
      </div>
    );
  }

  const canCopyReply = record.status === "quoted" && Boolean(record.customer_reply?.trim());

  return (
    <article className="rounded-md border border-white/10 bg-white/[0.04] p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase text-slate-400">Quote ID</p>
          <h3 className="mt-1 break-all text-lg font-semibold text-white">{record.quote_id}</h3>
          <p className="mt-1 text-sm text-slate-400">{formatRecordDate(record.created_at)}</p>
        </div>
        <SalesRecordStatusBadge status={record.status} />
      </div>

      {record.status === "manual_required" && (
        <div className="mt-4 rounded-md border border-amber-300/50 bg-amber-300/10 px-3 py-2 text-sm font-semibold leading-6 text-amber-50">
          已提交人工复核。{record.manual_reason ? `原因：${record.manual_reason}` : "请等待后台确认后再回复客户金额。"}
        </div>
      )}

      <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        <RecordMetric label="报价金额" value={formatRecordMoney(record)} strong />
        <RecordMetric label="目的地" value={record.destination} wide />
        <RecordMetric label="货物" value={record.cargo_summary} />
        <RecordMetric label="Zone" value={record.zone === null ? "待匹配" : `Zone ${record.zone}`} />
        <RecordMetric label="计费托数" value={record.billing_pallets ? `${record.billing_pallets} 托` : "待计算"} />
        <RecordMetric label="可信度" value={`${record.confidence}%`} />
        <RecordMetric label="来源" value={formatRecordSourceType(record.source_type)} />
      </div>

      {(record.risk_tags.length > 0 || record.missing_fields.length > 0) && (
        <div className="mt-4 rounded-md border border-white/10 bg-white/[0.04] p-3">
          <h4 className="text-sm font-semibold text-cyan-100">风险与缺失字段</h4>
          <div className="mt-3 flex flex-wrap gap-2">
            {[...record.missing_fields, ...record.risk_tags].map((tag) => (
              <span
                key={tag}
                className="rounded-md border border-amber-300/40 bg-amber-300/10 px-2 py-1 text-xs font-semibold text-amber-50"
              >
                {tag}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="mt-4 grid gap-3 xl:grid-cols-2">
        <div className="rounded-md border border-white/10 bg-white/[0.04] p-3">
          <h4 className="text-sm font-semibold text-white">客户原始询价</h4>
          <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-sm leading-6 text-slate-300">
            {record.customer_message}
          </pre>
        </div>
        <div className="rounded-md border border-white/10 bg-white/[0.04] p-3">
          <h4 className="text-sm font-semibold text-white">客户回复</h4>
          <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-sm leading-6 text-slate-300">
            {record.customer_reply || "人工复核单不生成可直接发送的报价话术。"}
          </pre>
          <div className="mt-3">
            <QuoteCopyButton text={record.customer_reply ?? ""} disabled={!canCopyReply} />
          </div>
        </div>
      </div>
    </article>
  );
}

function RecordMetric({
  label,
  value,
  strong = false,
  wide = false,
}: {
  label: string;
  value: string;
  strong?: boolean;
  wide?: boolean;
}) {
  return (
    <div className={`rounded-md border border-white/10 bg-white/[0.04] p-2.5 ${wide ? "sm:col-span-2" : ""}`}>
      <dt className="text-xs font-medium text-slate-400">{label}</dt>
      <dd className={`mt-1 break-words text-sm font-semibold tabular-nums ${strong ? "text-cyan-100" : "text-white"}`}>
        {value}
      </dd>
    </div>
  );
}

function SalesRecordStatusBadge({ status }: { status: SalesQuoteRecordStatus }) {
  return (
    <span
      className={`shrink-0 rounded-md border px-2 py-1 text-xs font-semibold ${
        status === "quoted"
          ? "border-emerald-300/50 bg-emerald-300/10 text-emerald-100"
          : "border-amber-300/50 bg-amber-300/10 text-amber-50"
      }`}
    >
      {status === "quoted" ? "已报价" : "人工复核"}
    </span>
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
  const addressValidationRisks = aiResult ? addressValidationToRiskMessages(aiResult) : [];
  return Array.from(new Set([
    ...manualRisk,
    ...parsed.risk_hints,
    ...backendRisks,
    ...aiMissingRisks,
    ...addressValidationRisks,
    ...searchRisks,
  ]));
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
    return ["外部搜索未返回；本地邮编库验证仍会用于城市、省份和邮编一致性检查。"];
  }
  const risks: string[] = ["已调用地址搜索验证，结果只作为地址确认参考，不参与金额计算。"];
  if (searchContext.address_research?.error) {
    risks.push("地址搜索验证失败，请人工确认地址类型和偏远情况。");
  }
  return risks;
}

function addressValidationToRiskMessages(aiResult: AIAutoQuoteResponse): string[] {
  const validation = aiResult.address_validation;
  if (!validation) {
    return ["本地邮编库验证未返回，请人工确认城市、省份和邮编。"];
  }
  if (validation.status === "verified" || validation.status === "postal_verified") {
    return [validation.note_zh];
  }
  return [
    validation.note_zh,
    ...(validation.corrected_city ? [`建议按本地邮编库城市 ${validation.corrected_city} 做 Zone 匹配。`] : []),
    ...(validation.corrected_province ? [`建议按本地邮编库省份 ${validation.corrected_province} 做 Zone 匹配。`] : []),
  ];
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

function buildSalesQuoteRecord({
  config,
  customerMessage,
  parsed,
  response,
}: {
  config: QuoteWorkbenchConfig;
  customerMessage: string;
  parsed: ParsedQuoteInput;
  response: AIAutoQuoteResponse;
}): SalesQuoteRecord {
  const quote = response.quote_result;
  const status: SalesQuoteRecordStatus =
    response.manual_review_required || quote?.manual_review_required || !quote
      ? "manual_required"
      : "quoted";
  const quoteId = quote?.quote_id ?? `local-${Date.now()}`;
  const missingFields = response.missing_fields.map(formatMissingField);
  const manualReason =
    status === "manual_required"
      ? missingFields.length
        ? `缺少 ${missingFields.join("、")}`
        : quote?.matched_rule || response.internal_note || "价格表未命中或需要人工确认"
      : null;

  return {
    id: quoteId,
    quote_id: quoteId,
    created_at: new Date().toISOString(),
    status,
    customer_message: customerMessage,
    customer_reply:
      response.customer_reply && status === "quoted"
        ? response.customer_reply
        : status === "quoted"
          ? buildSalesText(config, parsed, quote)
          : null,
    destination: formatRecordDestination(parsed, response, quote),
    cargo_summary: formatRecordCargoSummary(parsed, response),
    total_price_usd: quote?.total_price_usd ?? null,
    currency_code: config.copy_template.currency_code,
    zone: quote?.zone ?? null,
    billing_pallets: quote?.billing_pallets ?? null,
    confidence: quote?.confidence ?? response.extraction.confidence ?? parsed.confidence,
    source_type: quote?.source_type ?? "manual_required",
    postal_code: quote?.postal_code ?? response.extraction.postal_code ?? parsed.address.postal_code,
    city: quote?.city ?? response.extraction.city ?? parsed.address.city,
    province: quote?.province ?? response.extraction.province ?? parsed.address.province_code,
    risk_tags: quote?.risk_tags ?? [],
    missing_fields: missingFields,
    manual_reason: manualReason,
  };
}

function formatRecordDestination(
  parsed: ParsedQuoteInput,
  response: AIAutoQuoteResponse,
  quote: ZoneQuoteResult | null,
): string {
  return [
    response.extraction.address_line || parsed.address.address_line,
    quote?.preferred_city || quote?.city || response.extraction.city || parsed.address.city,
    quote?.province || response.extraction.province || parsed.address.province_code,
    response.extraction.postal_code || quote?.postal_code || parsed.address.postal_code,
  ]
    .filter(Boolean)
    .join(", ") || "目的地待确认";
}

function formatRecordCargoSummary(parsed: ParsedQuoteInput, response: AIAutoQuoteResponse): string {
  const pieceCount = response.extraction.piece_count ?? parsed.piece_count;
  const cbm = toNumber(response.extraction.cbm) ?? parsed.total_cbm;
  const weight = toNumber(response.extraction.weight_kg) ?? parsed.total_weight_kg;
  return [
    pieceCount ? `${pieceCount} 件` : "件数待确认",
    cbm ? `${cbm.toFixed(3)} CBM` : "CBM 待确认",
    weight ? `${weight.toFixed(1)} KG` : "重量待确认",
  ].join(" / ");
}

function upsertSalesQuoteRecord(
  records: SalesQuoteRecord[],
  record: SalesQuoteRecord,
): SalesQuoteRecord[] {
  return [
    record,
    ...records.filter((item) => item.id !== record.id && item.quote_id !== record.quote_id),
  ].slice(0, SALES_QUOTE_RECORD_LIMIT);
}

function filterSalesQuoteRecords(
  records: SalesQuoteRecord[],
  filter: SalesQuoteRecordFilter,
  query: string,
): SalesQuoteRecord[] {
  const normalizedQuery = query.trim().toLowerCase();
  return records.filter((record) => {
    if (filter !== "all" && record.status !== filter) {
      return false;
    }
    if (!normalizedQuery) {
      return true;
    }
    return [
      record.quote_id,
      record.destination,
      record.cargo_summary,
      record.customer_message,
      record.postal_code,
      record.city,
      record.province,
    ]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(normalizedQuery));
  });
}

function countSalesQuoteRecords(records: SalesQuoteRecord[]): Record<SalesQuoteRecordFilter, number> {
  return {
    all: records.length,
    quoted: records.filter((record) => record.status === "quoted").length,
    manual_required: records.filter((record) => record.status === "manual_required").length,
  };
}

function salesRecordFilterLabel(
  filter: SalesQuoteRecordFilter,
  counts: Record<SalesQuoteRecordFilter, number>,
): string {
  const labels: Record<SalesQuoteRecordFilter, string> = {
    all: "全部",
    quoted: "已报价",
    manual_required: "人工复核",
  };
  return `${labels[filter]} ${counts[filter]}`;
}

function formatRecordMoney(record: SalesQuoteRecord): string {
  if (record.status === "manual_required") {
    return "待人工确认";
  }
  const value = record.total_price_usd;
  if (value === null || value === undefined || value === "") {
    return "待匹配";
  }
  const numberValue = Number(value);
  return Number.isFinite(numberValue)
    ? `${record.currency_code} ${numberValue.toFixed(2)}`
    : `${record.currency_code} ${value}`;
}

function formatRecordDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value || "-";
  }
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatRecordSourceType(sourceType: string): string {
  if (sourceType === "zone_matrix") {
    return "Zone 价格矩阵";
  }
  if (sourceType === "learned_manual_quote") {
    return "人工确认学习库";
  }
  if (sourceType === "manual_required") {
    return "需要人工复核";
  }
  return sourceType || "待匹配";
}

function readSalesQuoteRecords(): SalesQuoteRecord[] {
  if (typeof window === "undefined") {
    return [];
  }
  try {
    const raw = window.localStorage.getItem(SALES_QUOTE_RECORDS_STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.filter(isSalesQuoteRecord).slice(0, SALES_QUOTE_RECORD_LIMIT);
  } catch {
    return [];
  }
}

function persistSalesQuoteRecords(records: SalesQuoteRecord[]): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(
    SALES_QUOTE_RECORDS_STORAGE_KEY,
    JSON.stringify(records.slice(0, SALES_QUOTE_RECORD_LIMIT)),
  );
}

function isSalesQuoteRecord(value: unknown): value is SalesQuoteRecord {
  if (!value || typeof value !== "object") {
    return false;
  }
  const record = value as Record<string, unknown>;
  return (
    typeof record.id === "string" &&
    typeof record.quote_id === "string" &&
    typeof record.created_at === "string" &&
    (record.status === "quoted" || record.status === "manual_required") &&
    typeof record.customer_message === "string" &&
    typeof record.destination === "string" &&
    typeof record.cargo_summary === "string" &&
    typeof record.currency_code === "string"
  );
}

function readQuoteThemeMode(): QuoteThemeMode {
  if (typeof window === "undefined") {
    return "light";
  }
  const stored = window.localStorage.getItem(QUOTE_THEME_STORAGE_KEY);
  return stored === "dark" ? "dark" : "light";
}
