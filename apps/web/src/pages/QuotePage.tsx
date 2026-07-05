import { useEffect, useMemo, useState } from "react";
import {
  calculateZoneQuote,
  clearStoredApiKey,
  getStoredApiKey,
  getQuoteWorkbenchConfig,
  listWeComBots,
  setStoredApiKey,
  type AddressType,
  type PackagingType,
  type QuoteWorkbenchConfig,
  type WeComBotConfigPublic,
  type ZoneQuoteRequest,
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

export default function QuotePage({ adminHref }: { adminHref: string }) {
  const [config, setConfig] = useState<QuoteWorkbenchConfig | null>(null);
  const [rawInput, setRawInput] = useState("");
  const [result, setResult] = useState<ZoneQuoteResult | null>(null);
  const [status, setStatus] = useState<WorkbenchStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [packagingType, setPackagingType] = useState<PackagingType | "">("");
  const [addressType, setAddressType] = useState<AddressType | "">("");
  const [services, setServices] = useState<Record<string, boolean>>({});
  const [detentionMinutes, setDetentionMinutes] = useState(0);
  const [wecomBots, setWecomBots] = useState<WeComBotConfigPublic[]>([]);
  const [notifyWecom, setNotifyWecom] = useState(false);
  const [selectedWecomBotId, setSelectedWecomBotId] = useState("");
  const [apiKeyInput, setApiKeyInput] = useState(() => getStoredApiKey("quote"));
  const [hasApiKey, setHasApiKey] = useState(() => Boolean(getStoredApiKey("quote")));

  useEffect(() => {
    void loadConfig();
    void loadWecomBots();
  }, []);

  async function loadConfig() {
    setError(null);
    try {
      const nextConfig = await getQuoteWorkbenchConfig("quote");
      setConfig(nextConfig);
      setPackagingType(nextConfig.defaults.packaging_type);
      setAddressType(nextConfig.defaults.address_type);
      setDetentionMinutes(nextConfig.defaults.detention_minutes);
      setNotifyWecom(nextConfig.defaults.notify_wecom);
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

  async function loadWecomBots() {
    try {
      setWecomBots(await listWeComBots("quote"));
    } catch {
      setWecomBots([]);
    }
  }

  const parsed = useMemo(
    () => (config ? parseQuoteInput(rawInput, config) : null),
    [config, rawInput],
  );

  const statusLabel = config?.status_labels[status] ?? status;
  const manualRequired = Boolean(result?.manual_review_required) || status === "manual_required";
  const riskMessages = useMemo(
    () => (config && parsed ? buildRiskMessages(config, parsed, result, manualRequired) : []),
    [config, parsed, result, manualRequired],
  );
  const salesText = useMemo(
    () => (config && parsed ? buildSalesText(config, parsed, result) : ""),
    [config, parsed, result],
  );

  function updateRawInput(value: string) {
    setRawInput(value);
    setResult(null);
    setNotice(null);
    setError(null);
    setStatus(value.trim() ? "parsed" : "idle");
  }

  async function handleSmartQuote() {
    if (!config || !parsed) {
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

    if (parsed.missing_fields.length) {
      setStatus("manual_required");
      setError(`识别信息不完整：${parsed.missing_fields.join("、")}。请补齐后再自动报价。`);
      return;
    }

    const payload = buildPayload(config, parsed, {
      packagingType,
      addressType,
      services,
      detentionMinutes,
    });

    setIsSubmitting(true);
    setStatus("quoting");
    try {
      const quoteResult = await calculateZoneQuote(
        notifyWecom
          ? {
              quote: payload,
              notify_wecom: true,
              wecom_bot_id: selectedWecomBotId ? Number(selectedWecomBotId) : null,
            }
          : payload,
      );
      setResult(quoteResult);
      setStatus(quoteResult.manual_review_required ? "manual_required" : "quoted");
      if (quoteResult.manual_review_required) {
        setNotice("该票已进入人工确认流程，请勿直接发送客户报价。");
      }
    } catch (caught) {
      setStatus("manual_required");
      setError(caught instanceof Error ? caught.message : "报价请求失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  function clearInput() {
    setRawInput("");
    setResult(null);
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
    void loadWecomBots();
  }

  function clearAccessKey() {
    clearStoredApiKey("quote");
    setApiKeyInput("");
    setHasApiKey(false);
    setConfig(null);
  }

  if (!config || !parsed) {
    return (
      <div className="ai-quote-workbench min-h-dvh px-4 py-8">
        <section className="ai-glass-panel mx-auto grid max-w-3xl gap-5 p-6">
          <h1 className="text-2xl font-semibold text-white">加拿大尾端 AI 报价系统</h1>
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
              后台管理
            </a>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="ai-quote-workbench min-h-dvh px-4 py-6 sm:px-6 lg:px-8">
      <div className="mx-auto flex max-w-[1800px] flex-col gap-6">
        <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-sm font-semibold uppercase text-cyan-200">
              AI 报价工作台
            </p>
            <h1 className="mt-3 text-3xl font-bold text-white sm:text-4xl">
              {config.title}
            </h1>
            <p className="mt-3 max-w-3xl text-base leading-7 text-slate-300">
              {config.subtitle}
            </p>
          </div>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
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
              后台管理
            </a>
            <span
              className={`inline-flex min-h-11 w-fit items-center rounded-full border px-4 py-2 text-sm font-semibold ${
                manualRequired
                  ? "border-amber-300/60 bg-amber-300/10 text-amber-100"
                  : "border-cyan-300/50 bg-cyan-300/10 text-cyan-100"
              }`}
            >
              {statusLabel}
            </span>
          </div>
        </header>

        {error && (
          <div
            className="rounded-md border border-red-300/60 bg-red-500/10 px-4 py-3 text-sm font-semibold text-red-100"
            role="alert"
          >
            {error}
          </div>
        )}
        {notice && (
          <div
            className="rounded-md border border-amber-300/50 bg-amber-300/10 px-4 py-3 text-sm font-semibold text-amber-50"
            role="status"
          >
            {notice}
          </div>
        )}

        <div className="grid gap-6 xl:grid-cols-[minmax(320px,560px)_minmax(0,1fr)]">
          <div className="grid min-w-0 gap-6">
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
              bots={wecomBots}
              notifyWecom={notifyWecom}
              selectedBotId={selectedWecomBotId}
              onNotifyChange={setNotifyWecom}
              onBotChange={setSelectedWecomBotId}
            />
          </div>

          <div className="grid min-w-0 content-start gap-6">
            <div className="grid min-w-0 gap-6 2xl:grid-cols-[minmax(0,1.08fr)_minmax(360px,0.92fr)]">
              <ParsedCargoTable parsed={parsed} />
              <QuoteCalculationPanel
                config={config}
                parsed={parsed}
                result={result}
                salesText={salesText}
                onExport={exportQuote}
              />
            </div>

            <div className="grid min-w-0 gap-6 2xl:grid-cols-[minmax(0,1.08fr)_minmax(360px,0.92fr)]">
              <ParsedAddressCard
                parsed={parsed}
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
              <QuoteRiskPanel risks={riskMessages} manualRequired={manualRequired} />
            </div>
          </div>
        </div>
      </div>
    </div>
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
  bots,
  notifyWecom,
  selectedBotId,
  onNotifyChange,
  onBotChange,
}: {
  bots: WeComBotConfigPublic[];
  notifyWecom: boolean;
  selectedBotId: string;
  onNotifyChange: (value: boolean) => void;
  onBotChange: (value: string) => void;
}) {
  return (
    <section className="ai-glass-panel p-4">
      <label className="flex min-h-11 items-center gap-3 text-sm font-semibold text-slate-100">
        <input
          className="h-4 w-4 rounded border-cyan-200 bg-slate-950 text-cyan-400 focus:ring-cyan-300"
          type="checkbox"
          checked={notifyWecom}
          onChange={(event) => onNotifyChange(event.target.checked)}
        />
        报价完成后推送企业微信
      </label>
      <label className="mt-3 block">
        <span className="text-xs font-semibold text-slate-300">企业微信机器人</span>
        <select
          className="ai-select mt-2"
          value={selectedBotId}
          onChange={(event) => onBotChange(event.target.value)}
          disabled={!notifyWecom}
        >
          <option value="">使用后台默认机器人</option>
          {bots.map((bot) => (
            <option key={bot.id} value={bot.id}>
              {bot.name} / {bot.purpose}
              {bot.is_default ? " / 默认" : ""}
            </option>
          ))}
        </select>
      </label>
    </section>
  );
}

function buildPayload(
  config: QuoteWorkbenchConfig,
  parsed: ParsedQuoteInput,
  options: {
    packagingType: PackagingType | "";
    addressType: AddressType | "";
    services: Record<string, boolean>;
    detentionMinutes: number;
  },
): ZoneQuoteRequest {
  return {
    address_line: parsed.address.address_line,
    postal_code: parsed.address.postal_code || "",
    city: parsed.address.city,
    province: parsed.address.province_code,
    cbm: parsed.total_cbm,
    weight_kg: parsed.total_weight_kg,
    piece_count: parsed.piece_count,
    packaging_type: (options.packagingType || config.defaults.packaging_type) as PackagingType,
    longest_side_cm: parsed.longest_side_cm,
    explicit_pallet_count: config.defaults.explicit_pallet_count,
    is_stackable: config.defaults.is_stackable,
    address_type: (options.addressType || config.defaults.address_type) as AddressType,
    requires_liftgate: Boolean(options.services.requires_liftgate),
    requires_pallet_jack: Boolean(options.services.requires_pallet_jack),
    requires_appointment: Boolean(options.services.requires_appointment),
    detention_minutes: options.detentionMinutes,
  };
}

function buildRiskMessages(
  config: QuoteWorkbenchConfig,
  parsed: ParsedQuoteInput,
  result: ZoneQuoteResult | null,
  manualRequired: boolean,
): string[] {
  const backendRisks =
    result?.risk_tags.map((tag) => config.backend_risk_tag_labels[tag] || tag) ?? [];
  const manualRisk = manualRequired ? ["需要人工确认，不要直接发客户。"] : [];
  return Array.from(new Set([...manualRisk, ...parsed.risk_hints, ...backendRisks]));
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
