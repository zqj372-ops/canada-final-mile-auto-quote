import { useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";
import {
  calculateAIAutoQuote,
  clearStoredAuthToken,
  getCurrentActor,
  getQuoteWorkbenchConfig,
  getStoredAuthToken,
  listEmailConfigs,
  listSalesQuoteRecords,
  login,
  setStoredAuthToken,
  updateSalesQuoteManualPrice,
  type AIExtractedQuoteDraft,
  type AIAutoQuoteResponse,
  type AddressType,
  type CurrentActor,
  type EmailConfigPublic,
  type PackagingType,
  type QuoteSearchContext,
  type QuoteWorkbenchConfig,
  type SalesQuoteRecord,
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

type SalesQuoteTab = "quote" | "records";
type SalesQuoteRecordStatus = "quoted" | "manual_required";
type SalesQuoteRecordFilter = SalesQuoteRecordStatus | "all";

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
  const [currentActor, setCurrentActor] = useState<CurrentActor | null>(null);
  const [loginUsername, setLoginUsername] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [authError, setAuthError] = useState<string | null>(null);
  const [isCheckingAuth, setIsCheckingAuth] = useState(Boolean(getStoredAuthToken()));
  const [isLoggingIn, setIsLoggingIn] = useState(false);
  const [activeSalesTab, setActiveSalesTab] = useState<SalesQuoteTab>("quote");
  const [quoteRecords, setQuoteRecords] = useState<SalesQuoteRecord[]>([]);
  const [isLoadingRecords, setIsLoadingRecords] = useState(false);
  const [recordFilter, setRecordFilter] = useState<SalesQuoteRecordFilter>("all");
  const [recordQuery, setRecordQuery] = useState("");
  const [selectedRecordId, setSelectedRecordId] = useState<number | null>(null);

  useEffect(() => {
    void restoreSession();
  }, []);

  async function restoreSession() {
    if (!getStoredAuthToken()) {
      setIsCheckingAuth(false);
      return;
    }
    setAuthError(null);
    setIsCheckingAuth(true);
    try {
      const actor = await getCurrentActor("quote");
      setCurrentActor(actor);
      await Promise.all([loadConfig(), loadEmailConfigs(), refreshSalesRecords()]);
    } catch (caught) {
      clearStoredAuthToken();
      setCurrentActor(null);
      setAuthError(caught instanceof Error ? caught.message : "登录已失效，请重新登录。");
    } finally {
      setIsCheckingAuth(false);
    }
  }

  async function handleLogin() {
    setAuthError(null);
    if (!loginUsername.trim() || !loginPassword) {
      setAuthError("请输入账号和密码。");
      return;
    }
    setIsLoggingIn(true);
    try {
      const response = await login({
        username: loginUsername.trim(),
        password: loginPassword,
      });
      setStoredAuthToken(response.access_token);
      setCurrentActor(response.actor);
      setLoginPassword("");
      await Promise.all([loadConfig(), loadEmailConfigs(), refreshSalesRecords()]);
    } catch (caught) {
      setAuthError(caught instanceof Error ? caught.message : "登录失败");
    } finally {
      setIsLoggingIn(false);
    }
  }

  function logout() {
    clearStoredAuthToken();
    setCurrentActor(null);
    setConfig(null);
    setQuoteRecords([]);
    setSelectedRecordId(null);
    setRawInput("");
    setResult(null);
    setAiResult(null);
    setStatus("idle");
  }

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

  async function refreshSalesRecords() {
    setIsLoadingRecords(true);
    try {
      const records = await listSalesQuoteRecords({ limit: 80 });
      setQuoteRecords(records);
      setSelectedRecordId((current) => current ?? records[0]?.id ?? null);
    } finally {
      setIsLoadingRecords(false);
    }
  }

  function updateSalesRecord(record: SalesQuoteRecord) {
    setQuoteRecords((current) =>
      current.map((item) => (item.id === record.id ? record : item)),
    );
    setSelectedRecordId(record.id);
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
  const recordCounts = useMemo(() => countSalesQuoteRecords(quoteRecords), [quoteRecords]);

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
          enable_search_context: false,
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
      await refreshSalesRecords();
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

  if (!currentActor || isCheckingAuth) {
    return (
      <div className="sales-frontdesk min-h-dvh">
        <SalesLoginPanel
          error={authError}
          isChecking={isCheckingAuth}
          isLoggingIn={isLoggingIn}
          onLogin={() => {
            void handleLogin();
          }}
          onPasswordChange={setLoginPassword}
              onUsernameChange={setLoginUsername}
              password={loginPassword}
              username={loginUsername}
            />
      </div>
    );
  }

  if (!config || !parsed) {
    return (
      <div className="sales-frontdesk grid min-h-dvh place-items-center px-4 py-8">
        <section className="panel mx-auto grid max-w-3xl gap-4 p-5">
          <h1 className="text-2xl font-semibold text-slate-950">加拿大尾端 AI 报价系统</h1>
          <p className="text-sm leading-6 text-slate-600">
            {error ? `配置加载失败：${error}` : "正在读取后台配置..."}
          </p>
          <div className="flex flex-wrap gap-3">
            <button className="btn-primary" type="button" onClick={() => void loadConfig()}>
              重新加载配置
            </button>
            <button className="btn-secondary" type="button" onClick={logout}>
              退出登录
            </button>
          </div>
        </section>
      </div>
    );
  }

  const displayParsed = effectiveParsed ?? parsed;

  return (
    <div className="sales-frontdesk min-h-dvh">
      <div className="sales-main">
        <header className="sales-topbar">
          <div className="sales-brand">
            <span className="sales-brand-mark">AI</span>
            <div>
              <p>AI 报价系统</p>
              <small>Canada Final-Mile</small>
            </div>
          </div>

          <nav className="sales-tabs" aria-label="销售前台功能">
            <button
              className={activeSalesTab === "quote" ? "sales-tab-active" : ""}
              type="button"
              onClick={() => setActiveSalesTab("quote")}
            >
              AI 报价
            </button>
            <button
              className={activeSalesTab === "records" ? "sales-tab-active" : ""}
              type="button"
              onClick={() => setActiveSalesTab("records")}
            >
              报价记录
            </button>
          </nav>

          <div className="sales-account-bar">
            <label className="sales-global-search">
              <span className="sr-only">搜索销售记录</span>
              <input
                value={recordQuery}
                onChange={(event) => {
                  setRecordQuery(event.target.value);
                  setActiveSalesTab("records");
                }}
                placeholder="搜索 quote_id、地址、原始询价..."
              />
            </label>
            <span className="sales-user-chip" title={currentActor.name}>
              <span className="sales-avatar sales-avatar-small">
                {currentActor.name.slice(0, 1).toUpperCase()}
              </span>
              <span className="hidden sm:block">{currentActor.name}</span>
              <span className="hidden xl:block">{roleLabel(currentActor.role)}</span>
            </span>
            <button className="btn-secondary min-h-10 px-3 py-1" type="button" onClick={logout}>
              退出登录
            </button>
          </div>
        </header>

        <main id="top">
        <section className="sales-page-heading">
          <div className="min-w-0">
            <h1>{activeSalesTab === "quote" ? "AI 智能报价" : "报价记录"}</h1>
            <p>
              {activeSalesTab === "quote"
                ? "粘贴客户询价，系统会自动解析货物、地址与服务要求，再交给 Quote Engine 查表报价。"
                : "回查自己的报价记录，筛选人工复核状态，并复制已生成的客户回复。"}
            </p>
          </div>
          {activeSalesTab === "quote" ? (
            <span
              className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${
                manualRequired
                  ? "border-amber-200 bg-amber-50 text-amber-700"
                  : "border-emerald-200 bg-emerald-50 text-emerald-700"
              }`}
            >
              {statusLabel}
            </span>
          ) : (
            <div className="flex flex-wrap gap-2">
              <button className="btn-secondary min-h-10 px-3 py-1" type="button" onClick={() => void refreshSalesRecords()} disabled={isLoadingRecords}>
                {isLoadingRecords ? "刷新中" : "刷新记录"}
              </button>
              <button className="btn-primary min-h-10 px-3 py-1" type="button" onClick={() => setActiveSalesTab("quote")}>
                新建报价
              </button>
            </div>
          )}
        </section>

        <SalesDeskStats
          activeTab={activeSalesTab}
          manualRequired={manualRequired}
          recordCounts={recordCounts}
          statusLabel={statusLabel}
        />

        <section id="quote-workbench">
          {activeSalesTab === "quote" && error && (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900" role="alert">
              {error}
            </div>
          )}
          {activeSalesTab === "quote" && notice && (
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900" role="status">
              {notice}
            </div>
          )}

          {activeSalesTab === "quote" ? (
            <div className="grid gap-4">
              <div className="sales-workbench-grid">
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

                <div className="grid min-w-0 content-start gap-3 sales-result-rail">
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
              <SalesQuoteRecordsPreview
                isLoading={isLoadingRecords}
                records={quoteRecords}
                onRefresh={() => {
                  void refreshSalesRecords();
                }}
                onViewAll={() => setActiveSalesTab("records")}
              />
            </div>
          ) : (
            <SalesQuoteRecordsPanel
              canOverridePrice={["admin", "operator"].includes(currentActor.role)}
              filter={recordFilter}
              isLoading={isLoadingRecords}
              query={recordQuery}
              records={quoteRecords}
              selectedRecordId={selectedRecordId}
              onFilterChange={setRecordFilter}
              onNewQuote={() => setActiveSalesTab("quote")}
              onQueryChange={setRecordQuery}
              onRefresh={() => {
                void refreshSalesRecords();
              }}
              onRecordUpdated={updateSalesRecord}
              onSelectRecord={setSelectedRecordId}
            />
          )}
        </section>
        </main>
      </div>
    </div>
  );
}

function SalesDeskStats({
  activeTab,
  manualRequired,
  recordCounts,
  statusLabel,
}: {
  activeTab: SalesQuoteTab;
  manualRequired: boolean;
  recordCounts: Record<SalesQuoteRecordFilter, number>;
  statusLabel: string;
}) {
  const items = [
    {
      label: "当前工作区",
      value: activeTab === "quote" ? "AI 报价" : "报价记录",
      tone: "info",
    },
    {
      label: "报价状态",
      value: statusLabel,
      tone: manualRequired ? "warn" : "success",
    },
    {
      label: "已报价记录",
      value: String(recordCounts.quoted),
      tone: "success",
    },
    {
      label: "人工复核",
      value: String(recordCounts.manual_required),
      tone: recordCounts.manual_required ? "warn" : "neutral",
    },
  ];

  return (
    <section className="sales-desk-stats" aria-label="销售工作台状态">
      {items.map((item) => (
        <div key={item.label} className={`sales-desk-stat sales-desk-stat-${item.tone}`}>
          <span>{item.label}</span>
          <strong>{item.value}</strong>
        </div>
      ))}
    </section>
  );
}

function SalesLoginPanel({
  error,
  isChecking,
  isLoggingIn,
  onLogin,
  onPasswordChange,
  onUsernameChange,
  password,
  username,
}: {
  error: string | null;
  isChecking: boolean;
  isLoggingIn: boolean;
  onLogin: () => void;
  onPasswordChange: (value: string) => void;
  onUsernameChange: (value: string) => void;
  password: string;
  username: string;
}) {
  return (
    <div className="sales-login-screen px-4 py-8">
      <section className="sales-login-card">
        <div>
          <div className="sales-brand">
            <span className="sales-brand-mark">CFM</span>
            <div>
              <p>Canada Final Mile</p>
              <small>销售前台</small>
            </div>
          </div>
          <h1 className="mt-10 text-3xl font-semibold tracking-normal text-slate-950">
            AI 报价与记录工作台
          </h1>
          <p className="mt-4 text-sm leading-6 text-slate-600">
            登录后直接进入新建报价和报价记录。后台配置、审计和人工复核由运营端处理。
          </p>
          <div className="mt-8 grid gap-3">
            <LoginCapability label="AI 智能报价" value="粘贴客户询价，一键解析并查价" tone="teal" />
            <LoginCapability label="报价记录" value="回查自己的历史报价和客户回复" tone="indigo" />
            <LoginCapability label="人工复核" value="需确认的票自动进入后台队列" tone="amber" />
          </div>
        </div>

        <form
          className="panel grid content-center gap-5 p-6 sm:p-8"
          onSubmit={(event) => {
            event.preventDefault();
            onLogin();
          }}
        >
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">账号登录</p>
            <h2 className="mt-2 text-2xl font-semibold text-slate-950">销售账号登录</h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              仅销售、运营或管理员账号可以提交报价；报价记录会按当前账号显示。
            </p>
          </div>

          {error && (
            <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm leading-6 text-rose-900">
              {error}
            </div>
          )}

          <label>
            <span className="text-xs font-semibold text-slate-700">账号</span>
            <input
              className="field-input mt-2"
              value={username}
              onChange={(event) => onUsernameChange(event.target.value)}
              placeholder="sales@example.com"
              autoComplete="username"
              autoFocus
            />
          </label>
          <label>
            <span className="text-xs font-semibold text-slate-700">密码</span>
            <input
              className="field-input mt-2"
              type="password"
              value={password}
              onChange={(event) => onPasswordChange(event.target.value)}
              placeholder="请输入密码"
              autoComplete="current-password"
            />
          </label>
          <button className="btn-primary" type="submit" disabled={isChecking || isLoggingIn}>
            {isChecking ? "恢复登录中..." : isLoggingIn ? "登录中..." : "登录并进入报价"}
          </button>
        </form>
      </section>
    </div>
  );
}

function LoginCapability({
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
    <section className="panel p-4">
      <div className="grid grid-cols-2 gap-2 xl:grid-cols-4">
        {steps.map((step) => (
          <div key={step.label} className="rounded-md border border-slate-200 bg-slate-50 px-2.5 py-2">
            <p className="text-xs font-semibold text-slate-500">{step.label}</p>
            <p className="mt-1 text-sm font-semibold text-slate-900">{step.status}</p>
          </div>
        ))}
      </div>
      <p className="mt-2 text-xs leading-5 text-slate-500">
        搜索结果只用于确认地址情况，不能覆盖 Zone 价格表和 Quote Engine 金额。
      </p>
    </section>
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
    <section className="panel p-4">
      <label className="flex min-h-11 items-center gap-3 text-sm font-semibold text-slate-800">
        <input
          className="h-4 w-4 rounded border-slate-300 text-teal-700 focus:ring-teal-700"
          type="checkbox"
          checked={notifyEmail}
          onChange={(event) => onNotifyChange(event.target.checked)}
        />
        报价完成后发送邮件
      </label>
      <label className="mt-3 block">
        <span className="text-xs font-semibold text-slate-600">邮件通知配置</span>
        <select
          className="field-input mt-2"
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

function SalesQuoteRecordsPreview({
  isLoading,
  records,
  onRefresh,
  onViewAll,
}: {
  isLoading: boolean;
  records: SalesQuoteRecord[];
  onRefresh: () => void;
  onViewAll: () => void;
}) {
  return (
    <section className="panel sales-records-preview overflow-hidden p-4">
      <div className="flex flex-col gap-3 border-b border-slate-200 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Recent Quotes</p>
          <h2 className="mt-1 text-base font-semibold text-slate-950">报价记录（最近 5 条）</h2>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn-secondary min-h-10 px-3 py-1" type="button" onClick={onRefresh} disabled={isLoading}>
            {isLoading ? "刷新中" : "刷新记录"}
          </button>
          <button className="btn-primary min-h-10 px-3 py-1" type="button" onClick={onViewAll}>
            查看全部
          </button>
        </div>
      </div>

      {records.length ? (
        <div className="overflow-x-auto">
          <div className="min-w-[760px]">
            <div className="grid grid-cols-[1.1fr_1.5fr_0.75fr_0.8fr_0.9fr] gap-3 bg-slate-50 px-4 py-3 text-xs font-semibold text-slate-500">
              <span>报价 ID</span>
              <span>客户概要</span>
              <span>状态</span>
              <span>金额</span>
              <span>创建时间</span>
            </div>
            {records.slice(0, 5).map((record) => (
              <button
                key={record.id}
                className="grid w-full grid-cols-[1.1fr_1.5fr_0.75fr_0.8fr_0.9fr] gap-3 border-t border-slate-100 px-4 py-3 text-left text-sm transition hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-teal-700"
                type="button"
                onClick={onViewAll}
              >
                <span className="break-all font-mono font-semibold text-slate-950">{record.quote_id || `#${record.id}`}</span>
                <span className="truncate text-slate-700">{record.destination || record.customer_message}</span>
                <span>
                  <SalesRecordStatusBadge status={record.status} />
                </span>
                <span className="font-semibold tabular-nums text-slate-950">{formatRecordMoney(record)}</span>
                <span className="text-xs text-slate-500">{formatRecordDate(record.created_at)}</span>
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="px-4 py-6 text-sm text-slate-600">
          完成一次报价后，这里会显示最近记录。
        </div>
      )}
    </section>
  );
}

function SalesQuoteRecordsPanel({
  canOverridePrice,
  filter,
  isLoading,
  query,
  records,
  selectedRecordId,
  onFilterChange,
  onNewQuote,
  onQueryChange,
  onRefresh,
  onRecordUpdated,
  onSelectRecord,
}: {
  canOverridePrice: boolean;
  filter: SalesQuoteRecordFilter;
  isLoading: boolean;
  query: string;
  records: SalesQuoteRecord[];
  selectedRecordId: number | null;
  onFilterChange: (value: SalesQuoteRecordFilter) => void;
  onNewQuote: () => void;
  onQueryChange: (value: string) => void;
  onRefresh: () => void;
  onRecordUpdated: (record: SalesQuoteRecord) => void;
  onSelectRecord: (id: number) => void;
}) {
  const visibleRecords = useMemo(
    () => filterSalesQuoteRecords(records, filter, query),
    [filter, query, records],
  );
  const selectedRecord =
    visibleRecords.find((record) => record.id === selectedRecordId) ?? visibleRecords[0] ?? null;
  const counts = countSalesQuoteRecords(records);

  return (
    <section className="panel p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase text-slate-500">销售记录</p>
          <h2 className="mt-1 text-xl font-semibold text-slate-950">报价记录</h2>
          <p className="mt-1 text-sm leading-6 text-slate-600">
            按当前账号回查已提交报价；人工复核状态以后端处理结果为准。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn-primary" type="button" onClick={onNewQuote}>
            新建报价
          </button>
          <button className="btn-secondary" type="button" onClick={onRefresh} disabled={isLoading}>
            {isLoading ? "刷新中" : "刷新记录"}
          </button>
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(220px,0.8fr)_minmax(0,1.2fr)]">
        <div className="grid gap-3">
          <div className="grid gap-3 rounded-md border border-slate-200 bg-slate-50 p-3">
            <label>
              <span className="text-xs font-semibold text-slate-500">搜索记录</span>
              <input
                className="field-input mt-2"
                value={query}
                onChange={(event) => onQueryChange(event.target.value)}
                placeholder="quote_id / 邮编 / 城市 / 原始询价"
              />
            </label>
            <div className="flex flex-wrap gap-2" role="tablist" aria-label="报价记录筛选">
              {(["all", "quoted", "manual_required"] as SalesQuoteRecordFilter[]).map((item) => (
                <button
                  key={item}
                  className={filter === item ? "btn-primary" : "btn-secondary"}
                  type="button"
                  onClick={() => onFilterChange(item)}
                >
                  {salesRecordFilterLabel(item, counts)}
                </button>
              ))}
            </div>
          </div>

          <div className="max-h-[640px] overflow-auto rounded-md border border-slate-200">
            {visibleRecords.length ? (
              visibleRecords.map((record) => {
                const isSelected = selectedRecord?.id === record.id;
                return (
                  <button
                    key={record.id}
                    className={`grid w-full gap-2 border-b border-slate-100 px-3 py-3 text-left transition hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-teal-700 ${
                      isSelected ? "bg-slate-100" : "bg-white"
                    }`}
                    type="button"
                    onClick={() => onSelectRecord(record.id)}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <span className="min-w-0 break-all text-sm font-semibold text-slate-900">
                        {record.quote_id}
                      </span>
                      <SalesRecordStatusBadge status={record.status} />
                    </div>
                    <p className="line-clamp-2 text-sm leading-5 text-slate-600">
                      {record.destination}
                    </p>
                    <div className="grid grid-cols-2 gap-2 text-xs text-slate-400">
                      <span>{formatRecordDate(record.created_at)}</span>
                      <span className="text-right font-semibold text-slate-800">
                        {formatRecordMoney(record)}
                      </span>
                    </div>
                  </button>
                );
              })
            ) : (
              <div className="grid min-h-52 place-items-center p-5 text-center">
                <div>
                  <h3 className="text-base font-semibold text-slate-900">暂无报价记录</h3>
                  <p className="mt-2 text-sm leading-6 text-slate-400">
                    完成一次报价后，系统会自动把结果保存到这里。
                  </p>
                  <button className="btn-primary mt-4" type="button" onClick={onNewQuote}>
                    去报价
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>

        <SalesQuoteRecordDetail
          canOverridePrice={canOverridePrice}
          record={selectedRecord}
          onRecordUpdated={onRecordUpdated}
        />
      </div>
    </section>
  );
}

function SalesQuoteRecordDetail({
  canOverridePrice,
  record,
  onRecordUpdated,
}: {
  canOverridePrice: boolean;
  record: SalesQuoteRecord | null;
  onRecordUpdated: (record: SalesQuoteRecord) => void;
}) {
  const [manualPrice, setManualPrice] = useState("");
  const [manualNote, setManualNote] = useState("");
  const [manualReply, setManualReply] = useState("");
  const [isSavingManualPrice, setIsSavingManualPrice] = useState(false);
  const [manualPriceError, setManualPriceError] = useState<string | null>(null);

  useEffect(() => {
    if (!record) {
      return;
    }
    setManualPrice(record.total_price_usd ? String(record.total_price_usd) : "");
    setManualNote("");
    setManualReply(record.customer_reply ?? "");
    setManualPriceError(null);
  }, [record?.id]);

  if (!record) {
    return (
      <div className="rounded-md border border-slate-200 bg-white p-5 text-sm text-slate-500">
        选择左侧记录后查看报价详情。
      </div>
    );
  }

  const canCopyReply = record.status === "quoted" && Boolean(record.customer_reply?.trim());
  const manualOverride = getManualOverride(record);

  async function saveManualPrice() {
    if (!record) {
      return;
    }
    const currentRecord = record;
    const price = Number(manualPrice);
    if (!Number.isFinite(price) || price < 0) {
      setManualPriceError("请输入大于等于 0 的 USD 金额。");
      return;
    }
    if (!manualNote.trim()) {
      setManualPriceError("请填写改价原因，方便后续复盘。");
      return;
    }
    const confirmed = window.confirm(
      "请二次确认：这会覆盖本条报价记录的客户可见金额，但不会修改 Zone 价格矩阵，也不会自动发布 Hermes 学习规则。确认保存？",
    );
    if (!confirmed) {
      return;
    }
    setIsSavingManualPrice(true);
    setManualPriceError(null);
    try {
      const updated = await updateSalesQuoteManualPrice(currentRecord.id, {
        total_price_usd: price,
        override_note: manualNote.trim(),
        customer_reply: manualReply.trim() || null,
        confirmed: true,
      });
      onRecordUpdated(updated);
    } catch (caught) {
      setManualPriceError(caught instanceof Error ? caught.message : "人工改价保存失败");
    } finally {
      setIsSavingManualPrice(false);
    }
  }

  return (
    <article className="rounded-md border border-slate-200 bg-white p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase text-slate-400">Quote ID</p>
          <h3 className="mt-1 break-all text-lg font-semibold text-slate-900">{record.quote_id}</h3>
          <p className="mt-1 text-sm text-slate-500">{formatRecordDate(record.created_at)}</p>
        </div>
        <SalesRecordStatusBadge status={record.status} />
      </div>

      {record.status === "manual_required" && (
        <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm font-semibold leading-6 text-amber-700">
          已提交人工复核。{record.manual_reason ? `原因：${record.manual_reason}` : "请等待后台确认后再回复客户金额。"}
        </div>
      )}

      {manualOverride && (
        <div className="mt-4 rounded-md border border-teal-200 bg-teal-50 px-3 py-2 text-sm leading-6 text-teal-800">
          后台已人工确认价格：USD {manualOverride.total_price_usd}
          {manualOverride.actor_name ? `，处理人：${manualOverride.actor_name}` : ""}。
          该金额只覆盖本条报价记录，不修改 Zone 价格矩阵。
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
        <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-3">
          <h4 className="text-sm font-semibold text-amber-700">风险与缺失字段</h4>
          <div className="mt-3 flex flex-wrap gap-2">
            {[...record.missing_fields, ...record.risk_tags].map((tag) => (
              <span
                key={tag}
                className="rounded-md border border-amber-300/50 bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-800"
              >
                {tag}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="mt-4 grid gap-3 xl:grid-cols-2">
        <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
          <h4 className="text-sm font-semibold text-slate-700">客户原始询价</h4>
          <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-sm leading-6 text-slate-700">
            {record.customer_message}
          </pre>
        </div>
        <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
          <h4 className="text-sm font-semibold text-slate-700">客户回复</h4>
          <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-sm leading-6 text-slate-700">
            {record.customer_reply || "人工复核单不生成可直接发送的报价话术。"}
          </pre>
          <div className="mt-3">
            <QuoteCopyButton text={record.customer_reply ?? ""} disabled={!canCopyReply} />
          </div>
        </div>
      </div>

      {canOverridePrice && (
        <section className="mt-4 rounded-md border border-teal-200 bg-teal-50/70 p-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h4 className="text-sm font-semibold text-teal-900">后台人工确认金额</h4>
              <p className="mt-1 text-xs leading-5 text-teal-700">
                只修改这条报价记录和客户回复；不会修改 Zone 价格表，也不会自动写入 Hermes 学习规则。
              </p>
            </div>
            <span className="rounded-md border border-amber-200 bg-amber-50 px-2 py-1 text-xs font-semibold text-amber-700">
              保存前会二次确认
            </span>
          </div>

          <div className="mt-3 grid gap-3 lg:grid-cols-[180px_minmax(0,1fr)]">
            <label>
              <span className="text-xs font-semibold text-slate-700">确认金额 USD</span>
              <input
                className="field-input mt-2"
                type="number"
                min="0"
                step="0.01"
                value={manualPrice}
                onChange={(event) => setManualPrice(event.target.value)}
                placeholder="例如 365.00"
              />
            </label>
            <label>
              <span className="text-xs font-semibold text-slate-700">改价/确认原因</span>
              <input
                className="field-input mt-2"
                value={manualNote}
                onChange={(event) => setManualNote(event.target.value)}
                placeholder="例如：已与供应商确认，按 Calgary Zone 5 / 3 托处理"
              />
            </label>
          </div>

          <label className="mt-3 block">
            <span className="text-xs font-semibold text-slate-700">客户回复文案</span>
            <textarea
              className="field-input mt-2 min-h-32"
              value={manualReply}
              onChange={(event) => setManualReply(event.target.value)}
              placeholder="留空则由系统按确认金额生成基础报价话术。"
            />
          </label>

          {manualPriceError && (
            <div className="mt-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
              {manualPriceError}
            </div>
          )}

          <button
            className="btn-primary mt-3 min-h-10 px-4 py-2"
            type="button"
            onClick={() => {
              void saveManualPrice();
            }}
            disabled={isSavingManualPrice}
          >
            {isSavingManualPrice ? "保存中..." : "保存人工确认价"}
          </button>
        </section>
      )}
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
    <div className={`rounded-md border border-slate-200 bg-white p-2.5 ${wide ? "sm:col-span-2" : ""}`}>
      <dt className="text-xs font-medium text-slate-500">{label}</dt>
      <dd className={`mt-1 break-words text-sm font-semibold tabular-nums ${strong ? "text-slate-900" : "text-slate-800"}`}>
        {value}
      </dd>
    </div>
  );
}

function SalesRecordStatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`shrink-0 rounded-md border px-2 py-1 text-xs font-semibold ${
        status === "quoted"
          ? "border-emerald-200 bg-emerald-50 text-emerald-700"
          : "border-amber-200 bg-amber-50 text-amber-700"
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
    <section className="panel p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase text-slate-500">搜索验证</p>
          <h2 className="mt-1 text-lg font-semibold text-slate-950">地址情况确认</h2>
        </div>
        <span className="shrink-0 rounded-full border border-cyan-200 bg-cyan-50 px-2.5 py-1 text-xs font-semibold text-cyan-700">
          {searchContext.provider}
        </span>
      </div>
      <p className="mt-2 text-xs leading-5 text-slate-500">
        {searchContext.note}
      </p>
      <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-3">
        <h3 className="text-sm font-semibold text-slate-700">地址情况</h3>
        {summary.error ? (
          <p className="mt-2 rounded-md border border-red-200 bg-red-50 p-2 text-sm leading-6 text-red-700">
            {summary.text}
          </p>
        ) : (
          <p className="mt-2 text-sm leading-6 text-slate-700">
            {summary.text}
          </p>
        )}
        <p className="mt-2 text-xs leading-5 text-slate-500">
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

function formatRecordDate(value: string | null): string {
  if (!value) {
    return "-";
  }
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
  if (sourceType === "manual_override") {
    return "后台人工确认价";
  }
  if (sourceType === "learned_manual_quote") {
    return "人工确认学习库";
  }
  if (sourceType === "hermes_agent_correction") {
    return "Hermes Agent 纠错";
  }
  if (sourceType === "manual_required") {
    return "需要人工复核";
  }
  return sourceType || "待匹配";
}

function getManualOverride(record: SalesQuoteRecord): {
  total_price_usd?: string;
  actor_name?: string;
} | null {
  const resultJson = record.result_json;
  if (!resultJson || typeof resultJson !== "object" || Array.isArray(resultJson)) {
    return null;
  }
  const override = (resultJson as Record<string, unknown>).manual_override;
  if (!override || typeof override !== "object" || Array.isArray(override)) {
    return null;
  }
  const data = override as Record<string, unknown>;
  return {
    total_price_usd: data.total_price_usd === undefined ? undefined : String(data.total_price_usd),
    actor_name: data.actor_name === undefined ? undefined : String(data.actor_name),
  };
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
