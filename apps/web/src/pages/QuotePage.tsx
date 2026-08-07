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
  type AIExtractedQuoteDraft,
  type AIAutoQuoteResponse,
  type AddressType,
  type CurrentActor,
  type EmailConfigPublic,
  type FCLQuoteResult,
  type PackagingType,
  type QuoteSearchContext,
  type QuoteWorkbenchConfig,
  type SalesQuoteRecord,
  type ZoneQuoteResult,
} from "../api/client";
import AiQuoteInputPanel from "../components/AiQuoteInputPanel";
import FclQuotePanel from "../components/FclQuotePanel";
import AccountMenu from "../components/AccountMenu";
import LogoutConfirmationDialog from "../components/LogoutConfirmationDialog";
import ParsedAddressCard from "../components/ParsedAddressCard";
import ParsedCargoTable from "../components/ParsedCargoTable";
import QuoteCopyButton from "../components/QuoteCopyButton";
import QuoteCalculationPanel from "../components/QuoteCalculationPanel";
import QuoteRiskPanel from "../components/QuoteRiskPanel";
import {
  FCL_ADDRESS_TYPES,
  FCL_CUSTOMER_TYPES,
  FCL_DEADLINE_STRICTNESS,
  FCL_EXPORT_DECLARATIONS,
  FCL_IMPORTER_EXISTS,
  FCL_SERVICE_STAGES,
  FCL_SPECIAL_ATTRIBUTES,
  FCL_TAX_INCLUDED,
  FCL_TRADE_TERMS,
  labelOf,
} from "../components/fclFieldLabels";
import { printFclQuoteHtml } from "../components/fclQuoteHtml";
import { parseQuoteInput, type ParsedCargoItem, type ParsedQuoteInput } from "../utils/quoteParser";

type WorkbenchStatus = "idle" | "quoting" | "quoted" | "manual_required" | "error";

type SalesQuoteTab = "quote" | "records";
type QuoteMode = "final_mile" | "fcl";
type SalesQuoteRecordStatus = "quoted" | "manual_required";
type SalesQuoteRecordFilter = SalesQuoteRecordStatus | "all";

const RURAL_CONFIRMATION_CHECKS = [
  "完整街道地址、城市和邮编是否彼此一致",
  "大型卡车能否进入，现场是否具备装卸条件",
  "是否需要尾板、手叉车、预约或其他附加服务",
  "偏远地区附加费及供应商最终派送条件是否已确认",
];

export default function QuotePage({ adminHref: _adminHref }: { adminHref: string }) {
  const [config, setConfig] = useState<QuoteWorkbenchConfig | null>(null);
  const [rawInput, setRawInput] = useState("");
  const [result, setResult] = useState<ZoneQuoteResult | null>(null);
  const [aiResult, setAiResult] = useState<AIAutoQuoteResponse | null>(null);
  const [status, setStatus] = useState<WorkbenchStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
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
  const [quoteMode, setQuoteMode] = useState<QuoteMode>("final_mile");
  const [ruralAcknowledgedKey, setRuralAcknowledgedKey] = useState<string | null>(null);
  const [controlsDirty, setControlsDirty] = useState(false);
  const [quoteRecords, setQuoteRecords] = useState<SalesQuoteRecord[]>([]);
  const [isLoadingRecords, setIsLoadingRecords] = useState(false);
  const [recordsError, setRecordsError] = useState<string | null>(null);
  const [recordFilter, setRecordFilter] = useState<SalesQuoteRecordFilter>("all");
  const [recordQuery, setRecordQuery] = useState("");
  const [selectedRecordId, setSelectedRecordId] = useState<number | null>(null);
  const [isLogoutConfirmationOpen, setIsLogoutConfirmationOpen] = useState(false);
  const [isResultModalOpen, setIsResultModalOpen] = useState(false);

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
    } catch (caught) {
      clearStoredAuthToken();
      setCurrentActor(null);
      setAuthError(caught instanceof Error ? caught.message : "登录已失效，请重新登录。");
      return;
    } finally {
      setIsCheckingAuth(false);
    }
    await Promise.allSettled([loadConfig(), loadEmailConfigs(), refreshSalesRecords()]);
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
      await Promise.allSettled([loadConfig(), loadEmailConfigs(), refreshSalesRecords()]);
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
    setRuralAcknowledgedKey(null);
    setControlsDirty(false);
    setIsResultModalOpen(false);
  }

  function requestLogout() {
    setIsLogoutConfirmationOpen(true);
  }

  function confirmLogout() {
    setIsLogoutConfirmationOpen(false);
    logout();
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

  async function refreshSalesRecords(): Promise<boolean> {
    setIsLoadingRecords(true);
    setRecordsError(null);
    try {
      const records = await listSalesQuoteRecords({ limit: 80 });
      setQuoteRecords(records);
      setSelectedRecordId((current) => current ?? records[0]?.id ?? null);
      return true;
    } catch (caught) {
      setRecordsError(caught instanceof Error ? caught.message : "报价记录刷新失败");
      return false;
    } finally {
      setIsLoadingRecords(false);
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
  const manualRequired = Boolean(result?.manual_review_required);
  const riskMessages = useMemo(
    () =>
      effectiveParsed
        ? buildRiskMessages(effectiveParsed, manualRequired, aiResult)
        : [],
    [aiResult, effectiveParsed, manualRequired],
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

  // 乡村邮编二次确认:同一 quote_id(或地址组合)在本会话内确认一次即可。
  const ruralPostalPrefix = extractPostalPrefix(effectiveParsed?.address.postal_code ?? null);
  const requiresRuralConfirmation = Boolean(ruralPostalPrefix && ruralPostalPrefix[1] === "0");
  const ruralConfirmationKey =
    result?.quote_id ||
    [
      effectiveParsed?.address.postal_code,
      effectiveParsed?.address.city,
      effectiveParsed?.address.address_line,
    ]
      .filter(Boolean)
      .join("|");
  const ruralConfirmed = Boolean(
    requiresRuralConfirmation && ruralConfirmationKey && ruralAcknowledgedKey === ruralConfirmationKey,
  );

  function updateRawInput(value: string) {
    setRawInput(value);
    setResult(null);
    setAiResult(null);
    setNotice(null);
    setError(null);
    setStatus("idle");
    setControlsDirty(false);
    setIsResultModalOpen(false);
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

    setStatus("quoting");
    setError(null);
    setNotice(null);
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
      setControlsDirty(false);
      setIsResultModalOpen(true);
      const manual = response.manual_review_required || response.quote_result?.manual_review_required;
      setStatus(manual ? "manual_required" : "quoted");
      if (manual) {
        setNotice(
          response.missing_fields.length
            ? `AI 已解析，但缺少 ${formatMissingFields(response.missing_fields).join("、")}；已进入人工任务池。`
            : "该票已进入人工确认流程，请勿直接发送客户报价。",
        );
      }
      const recordsRefreshed = await refreshSalesRecords();
      if (!recordsRefreshed) {
        setNotice((current) =>
          [current, "报价结果已生成，但历史记录列表暂未刷新。"].filter(Boolean).join(" "),
        );
      }
    } catch (caught) {
      // 请求失败是独立状态:清空旧结果,避免把失败伪装成"人工复核"或展示过期数据。
      setStatus("error");
      setResult(null);
      setAiResult(null);
      setError(
        caught instanceof Error
          ? `报价请求失败：${caught.message}。请检查后台 AI 模型配置后重试。`
          : "报价请求失败，请稍后重试。",
      );
    }
  }

  function clearInput() {
    setRawInput("");
    setResult(null);
    setAiResult(null);
    setError(null);
    setNotice(null);
    setStatus("idle");
    setControlsDirty(false);
    setIsResultModalOpen(false);
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
            <button className="btn-danger" type="button" onClick={requestLogout}>
              退出登录
            </button>
          </div>
          <LogoutConfirmationDialog
            isOpen={isLogoutConfirmationOpen}
            onCancel={() => setIsLogoutConfirmationOpen(false)}
            onConfirm={confirmLogout}
          />
        </section>
      </div>
    );
  }

  // 守卫之后 parsed 恒非空;effectiveParsed 在 config 非空时也恒非空,
  // ?? 兜底只用于让 TypeScript 收窄类型(运行时永远走左侧)。
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
            <AccountMenu
              actor={currentActor}
              roleLabel={roleLabel(currentActor.role)}
              variant="sales"
              onRequestLogout={requestLogout}
            />
          </div>
        </header>

        <main id="top">
        <section className="sales-page-heading">
          <div className="min-w-0">
            <h1>{activeSalesTab === "quote" ? (quoteMode === "fcl" ? "AI 整柜报价" : "AI 智能报价") : "报价记录"}</h1>
            <p>
              {activeSalesTab === "quote"
                ? quoteMode === "fcl"
                  ? "填写结构化询价字段；货物重算与计价全部由确定性引擎完成。"
                  : "粘贴客户询价，系统会自动解析货物、地址与服务要求，再交给 Quote Engine 查表报价。"
                : "回查自己的报价记录，筛选人工复核状态，并复制已生成的客户回复。"}
            </p>
          </div>
          {activeSalesTab === "quote" ? (
            <div className="flex flex-wrap items-center gap-3">
              <div className="rounded-lg border border-slate-200 bg-white p-0.5 text-xs font-semibold" role="group" aria-label="报价模式">
                <button
                  className={`rounded-md px-3 py-1.5 ${quoteMode === "final_mile" ? "bg-teal-700 text-white" : "text-slate-600"}`}
                  type="button"
                  onClick={() => setQuoteMode("final_mile")}
                >
                  加拿大尾程
                </button>
                <button
                  className={`rounded-md px-3 py-1.5 ${quoteMode === "fcl" ? "bg-teal-700 text-white" : "text-slate-600"}`}
                  type="button"
                  onClick={() => setQuoteMode("fcl")}
                >
                  AI 整柜
                </button>
              </div>
              {quoteMode === "final_mile" && (
                <span
                  className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${
                    manualRequired
                      ? "border-amber-200 bg-amber-50 text-amber-700"
                      : "border-emerald-200 bg-emerald-50 text-emerald-700"
                  }`}
                >
                  {statusLabel}
                </span>
              )}
              {quoteMode === "final_mile" && result && (
                <button
                  className="btn-primary min-h-10 px-3 py-1"
                  type="button"
                  onClick={() => setIsResultModalOpen(true)}
                >
                  查看报价结果
                </button>
              )}
            </div>
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
          {recordsError && (
            <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900" role="status">
              报价记录：{recordsError}
            </div>
          )}

          {activeSalesTab === "quote" ? (
            quoteMode === "fcl" ? (
              <FclQuotePanel onRecordsRefresh={refreshSalesRecords} />
            ) : (
            <div className="grid gap-4">
              <div className="sales-workbench-grid">
                <div className="sales-stage sales-stage-input grid min-w-0 content-start gap-3">
                  <AiQuoteInputPanel
                    config={config}
                    value={rawInput}
                    statusLabel={statusLabel}
                    isQuoting={status === "quoting"}
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

                <div className="sales-stage sales-stage-parsed grid min-w-0 content-start gap-3">
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
                    onPackagingTypeChange={(value) => {
                      setPackagingType(value as PackagingType);
                      setControlsDirty(true);
                    }}
                    addressType={addressType}
                    onAddressTypeChange={(value) => {
                      setAddressType(value as AddressType);
                      setControlsDirty(true);
                    }}
                    services={services}
                    onServiceChange={(key, checked) => {
                      setServices((current) => ({ ...current, [key]: checked }));
                      setControlsDirty(true);
                    }}
                    detentionMinutes={detentionMinutes}
                    onDetentionMinutesChange={(value) => {
                      setDetentionMinutes(value);
                      setControlsDirty(true);
                    }}
                  />
                </div>
              </div>
              <SalesQuoteRecordsPreview
                isLoading={isLoadingRecords}
                records={quoteRecords}
                onRefresh={() => {
                  void refreshSalesRecords();
                }}
                onViewAll={() => setActiveSalesTab("records")}
                onOpenRecord={(recordId) => {
                  setSelectedRecordId(recordId);
                  setActiveSalesTab("records");
                }}
              />
            </div>
            )
          ) : (
            <SalesQuoteRecordsPanel
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
              onSelectRecord={setSelectedRecordId}
            />
          )}
        </section>
        </main>
      </div>
      <QuoteResultDialog
        isOpen={isResultModalOpen}
        config={config}
        parsed={displayParsed}
        result={result}
        aiParsed={Boolean(aiResult)}
        salesText={salesText}
        risks={riskMessages}
        manualRequired={manualRequired}
        searchContext={aiResult?.search_context ?? null}
        onClose={() => setIsResultModalOpen(false)}
        onExport={exportQuote}
        requiresRuralConfirmation={requiresRuralConfirmation}
        ruralConfirmed={ruralConfirmed}
        onAcknowledgeRural={() => setRuralAcknowledgedKey(ruralConfirmationKey)}
        onReturnToEdit={() => {
          setIsResultModalOpen(false);
          updateRawInput(rawInput);
        }}
        controlsDirty={controlsDirty}
        onRequote={handleSmartQuote}
      />
      <LogoutConfirmationDialog
        isOpen={isLogoutConfirmationOpen}
        onCancel={() => setIsLogoutConfirmationOpen(false)}
        onConfirm={confirmLogout}
      />
    </div>
  );
}

function QuoteResultDialog({
  aiParsed,
  config,
  controlsDirty,
  isOpen,
  manualRequired,
  onAcknowledgeRural,
  onClose,
  onExport,
  onRequote,
  onReturnToEdit,
  parsed,
  requiresRuralConfirmation,
  result,
  risks,
  ruralConfirmed,
  salesText,
  searchContext,
}: {
  aiParsed: boolean;
  config: QuoteWorkbenchConfig;
  controlsDirty: boolean;
  isOpen: boolean;
  manualRequired: boolean;
  onAcknowledgeRural: () => void;
  onClose: () => void;
  onExport: () => void;
  onRequote: () => void;
  onReturnToEdit: () => void;
  parsed: ParsedQuoteInput;
  requiresRuralConfirmation: boolean;
  result: ZoneQuoteResult | null;
  risks: string[];
  ruralConfirmed: boolean;
  salesText: string;
  searchContext: QuoteSearchContext | null;
}) {
  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const previousOverflow = document.body.style.overflow;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen, onClose]);

  if (!isOpen) {
    return null;
  }

  const ruralPostalPrefix = extractPostalPrefix(parsed.address.postal_code);

  return (
    <div
      className="quote-result-modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <section
        className="quote-result-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="quote-result-modal-title"
      >
        <header className="quote-result-modal-header">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase text-teal-700">AI 报价结果</p>
            <h2 id="quote-result-modal-title" className="mt-1 text-xl font-semibold text-slate-950">
              {manualRequired ? "报价待人工复核" : "报价已完成"}
            </h2>
          </div>
          <button
            className="quote-result-modal-close"
            type="button"
            onClick={onClose}
            aria-label="关闭报价结果"
            autoFocus
          >
            <span aria-hidden="true">×</span>
          </button>
        </header>

        <div className="quote-result-modal-content">
          <div className="quote-result-modal-summary grid min-w-0 content-start gap-3">
            {controlsDirty && (
              <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm font-semibold leading-6 text-amber-700" role="status">
                已修改包装、地址类型或附加服务，当前结果基于修改前的字段。
                <button className="ml-2 underline" type="button" onClick={onRequote}>
                  重新报价
                </button>
              </div>
            )}

            {requiresRuralConfirmation && !ruralConfirmed && (
              <div className="rounded-md border-2 border-amber-400 bg-amber-50 p-3" role="status">
                <p className="text-sm font-bold text-amber-900">乡村邮编二次确认</p>
                <p className="mt-1 text-sm leading-6 text-amber-800">
                  邮编前缀 <strong>{ruralPostalPrefix || "待确认"}</strong> 第二位为 0，属于乡村 FSA。
                  {manualRequired
                    ? "该票同时存在人工复核原因，地址确认不代表价格已审核。"
                    : "报价已计算完成，但复制或导出前必须核对派送条件。"}
                </p>
                <ul className="mt-2 grid gap-1">
                  {RURAL_CONFIRMATION_CHECKS.map((item, index) => (
                    <li key={item} className="flex gap-2 text-sm leading-5 text-amber-800">
                      <span className="font-semibold">{index + 1}.</span>
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-xs leading-5 text-amber-700">
                  点击确认仅表示已完成地址与派送条件核对；最终价格仍以供应商实测地址为准。
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button className="btn-secondary" type="button" onClick={onReturnToEdit}>
                    返回修改地址
                  </button>
                  <button className="btn-primary" type="button" onClick={onAcknowledgeRural}>
                    我已核对，允许复制与导出
                  </button>
                </div>
              </div>
            )}

            <QuoteCalculationPanel
              config={config}
              parsed={parsed}
              result={result}
              aiParsed={aiParsed}
              salesText={salesText}
              onExport={onExport}
              ruralConfirmationRequired={requiresRuralConfirmation}
              ruralConfirmationAcknowledged={ruralConfirmed}
            />
            <QuoteRiskPanel risks={risks} manualRequired={manualRequired} />
            {searchContext ? <SearchVerificationPanel searchContext={searchContext} /> : null}
          </div>
        </div>
      </section>
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
    { label: "本地预览", status: "仅辅助核对" },
    { label: "AI 解析", status: hasAIResult ? `完成 ${extractionConfidence}%` : "待提交" },
    { label: "搜索验证", status: hasAIResult ? (hasSearchContext ? "已返回参考" : "未返回参考") : "提交后验证" },
    { label: "规则报价", status: hasAIResult ? (manualRequired ? "需人工复核" : "已完成") : "待执行" },
  ];

  return (
    <section className="panel quote-pipeline-panel p-4">
      <div className="quote-pipeline-steps grid grid-cols-2 gap-2 xl:grid-cols-4">
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
  onOpenRecord,
}: {
  isLoading: boolean;
  records: SalesQuoteRecord[];
  onRefresh: () => void;
  onViewAll: () => void;
  onOpenRecord: (recordId: number) => void;
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
                onClick={() => onOpenRecord(record.id)}
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
  filter,
  isLoading,
  query,
  records,
  selectedRecordId,
  onFilterChange,
  onNewQuote,
  onQueryChange,
  onRefresh,
  onSelectRecord,
}: {
  filter: SalesQuoteRecordFilter;
  isLoading: boolean;
  query: string;
  records: SalesQuoteRecord[];
  selectedRecordId: number | null;
  onFilterChange: (value: SalesQuoteRecordFilter) => void;
  onNewQuote: () => void;
  onQueryChange: (value: string) => void;
  onRefresh: () => void;
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

        <SalesQuoteRecordDetail record={selectedRecord} />
      </div>
    </section>
  );
}

function SalesQuoteRecordDetail({ record }: { record: SalesQuoteRecord | null }) {
  if (!record) {
    return (
      <div className="rounded-md border border-slate-200 bg-white p-5 text-sm text-slate-500">
        选择左侧记录后查看报价详情。
      </div>
    );
  }

  const canCopyReply = record.status === "quoted" && Boolean(record.customer_reply?.trim());
  const manualOverride = getManualOverride(record);
  if (record.quote_type === "fcl") {
    return <FclSalesRecordDetail record={record} />;
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
    </article>
  );
}

function FclSalesRecordDetail({ record }: { record: SalesQuoteRecord }) {
  const resultJson = record.result_json;
  const quoteResult =
    resultJson && typeof resultJson === "object" && !Array.isArray(resultJson)
      ? ((resultJson as Record<string, unknown>).quote_result as FCLQuoteResult | undefined)
      : undefined;
  const normalized = quoteResult?.normalized_input;
  const manual = record.status === "manual_required" || Boolean(quoteResult?.manual_review_required);
  const visibleItems = quoteResult?.fee_items.filter((item) =>
    ["both", "quoteOnly", "merged"].includes(item.display_mode),
  );

  return (
    <article className="rounded-md border border-slate-200 bg-white p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase text-slate-400">FCL Quote ID</p>
          <h3 className="mt-1 break-all text-lg font-semibold text-slate-900">{record.quote_id}</h3>
          <p className="mt-1 text-sm text-slate-500">{formatRecordDate(record.created_at)}</p>
        </div>
        <SalesRecordStatusBadge status={record.status} />
      </div>

      {manual && (
        <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm font-semibold leading-6 text-amber-700">
          已提交人工复核。{(quoteResult?.manual_reasons ?? []).join("、") || record.manual_reason || "请等待后台确认后再回复客户金额。"}
        </div>
      )}

      <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        <RecordMetric label="报价金额" value={formatRecordMoney(record)} strong wide />
        <RecordMetric label="线路" value={record.destination} />
        <RecordMetric label="货物" value={record.cargo_summary} />
        <RecordMetric label="来源" value={record.source_type === "fcl_rate_card" ? "整柜费率卡" : "人工复核"} />
        <RecordMetric label="报价有效期至" value={quoteResult?.quote_valid_until ?? "—"} />
      </div>

      {normalized && (
        <div className="mt-4 grid gap-2 rounded-md border border-slate-200 bg-slate-50 p-3 sm:grid-cols-2 xl:grid-cols-3">
          <RecordMetric label="客户 / 联系人" value={`${normalized.customer_name || "—"} / ${normalized.contact || "—"}`} />
          <RecordMetric label="客户类型" value={labelOf(FCL_CUSTOMER_TYPES, normalized.customer_type)} />
          <RecordMetric label="目的邮编 / 地址" value={`${normalized.destination_postal_code || "—"} / ${normalized.destination_address || "—"}`} />
          <RecordMetric label="货名 / 材质用途" value={`${normalized.cargo_name || "—"}${normalized.cargo_details ? ` / ${normalized.cargo_details}` : ""}`} />
          <RecordMetric label="货值 / HS / 原产地" value={`${normalized.cargo_value ? `${normalized.cargo_value_currency ?? ""} ${normalized.cargo_value}` : "—"} / ${normalized.hs_code || "—"} / ${normalized.origin_country || "—"}`} />
          <RecordMetric label="特殊属性" value={(normalized.special_attributes ?? []).map((value) => labelOf(FCL_SPECIAL_ATTRIBUTES, value)).join("、") || "—"} />
          <RecordMetric label="备货 / ETD / 期望到门" value={`${normalized.ready_date || "—"} / ${normalized.target_etd || "—"} / ${normalized.expected_delivery_date || "—"}（${labelOf(FCL_DEADLINE_STRICTNESS, normalized.deadline_strictness)}）`} />
          <RecordMetric label="贸易条款 / 出口报关" value={`${labelOf(FCL_TRADE_TERMS, normalized.trade_terms)} / ${labelOf(FCL_EXPORT_DECLARATIONS, normalized.export_declaration)}`} />
          <RecordMetric label="进口商 / 包税" value={`${labelOf(FCL_IMPORTER_EXISTS, normalized.importer_exists)} / ${labelOf(FCL_TAX_INCLUDED, normalized.tax_included)}`} />
          <RecordMetric label="服务环节" value={(normalized.service_stages ?? []).map((value) => labelOf(FCL_SERVICE_STAGES, value)).join("、") || "—"} />
          <RecordMetric label="到门信息" value={`${labelOf(FCL_ADDRESS_TYPES, normalized.address_type)} / 尾板 ${normalized.tail_lift || "—"} / 叉车 ${normalized.forklift || "—"}`} />
          <RecordMetric label="平台仓 / 预约" value={`${normalized.platform_warehouse || "—"} / ${normalized.appointment_window || "—"}`} />
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
            <QuoteCopyButton text={record.customer_reply ?? ""} disabled={manual || !record.customer_reply} />
          </div>
        </div>
      </div>

      {quoteResult && (
        <>
          <div className="mt-4 overflow-x-auto rounded-md border border-slate-200">
            <table className="w-full min-w-[520px] text-left text-sm">
              <thead>
                <tr className="bg-slate-50 text-xs text-slate-500">
                  <th className="px-3 py-2">费用项目</th>
                  <th className="px-3 py-2">数量</th>
                  <th className="px-3 py-2">单价</th>
                  <th className="px-3 py-2">金额</th>
                </tr>
              </thead>
              <tbody>
                {(visibleItems ?? []).map((item) => (
                  <tr key={item.item_name} className="border-t border-slate-100">
                    <td className="px-3 py-2">{item.item_name}</td>
                    <td className="px-3 py-2">{item.quantity} {item.unit}</td>
                    <td className="px-3 py-2">{item.unit_price === null || item.unit_price === "" ? "—" : `${item.currency} ${item.unit_price}`}</td>
                    <td className="px-3 py-2">{item.amount === null || item.amount === "" ? "按实际/人工确认" : `${item.currency} ${item.amount}`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <span className="text-sm font-semibold text-slate-800">{formatRecordMoney(record)}</span>
            <button
              className="btn-primary"
              type="button"
              disabled={manual}
              onClick={() => printFclQuoteHtml(quoteResult)}
            >
              打印 A4 报价单 / 另存为 PDF
            </button>
          </div>
        </>
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

function extractPostalPrefix(value: string | null | undefined): string | null {
  const compact = String(value || "")
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, "");
  const match = compact.match(/^([ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTVWXYZ])/);
  return match?.[1] ?? null;
}

function formatQuoteAmount(value: string | number): string {
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue.toFixed(2) : "待确认";
}

function buildRiskMessages(
  parsed: ParsedQuoteInput,
  manualRequired: boolean,
  aiResult: AIAutoQuoteResponse | null,
): string[] {
  if (!aiResult) {
    return ["待提交给后台大模型解析；本地预览不再作为最终字段来源。"];
  }
  const manualRisk = manualRequired ? ["需要人工确认，不要直接发客户。"] : [];
  const aiMissingRisks =
    aiResult?.missing_fields.map((field) => `AI 解析缺少：${formatMissingField(field)}`) ?? [];
  const searchRisks = aiResult ? searchContextToRiskMessages(aiResult.search_context) : [];
  const addressValidationRisks = aiResult ? addressValidationToRiskMessages(aiResult) : [];
  return Array.from(new Set([
    ...manualRisk,
    ...parsed.risk_hints,
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
    result?.total_price_usd !== null &&
    result?.total_price_usd !== undefined &&
    result.total_price_usd !== "" &&
    !result.manual_review_required
      ? `${config.copy_template.currency_code} ${formatQuoteAmount(result.total_price_usd)}`
      : config.copy_template.manual_price_text;
  const ruralPrefix = extractPostalPrefix(parsed.address.postal_code);
  const ruralConfirmationLines = ruralPrefix && ruralPrefix[1] === "0"
    ? ["特别提醒：该地址为乡村邮编，完整地址、卡车准入及可能附加费需二次确认。"]
    : [];

  return [
    "加拿大尾端派送报价如下：",
    `目的地：${destination || "待确认"}`,
    `货物数据：共 ${parsed.piece_count || "待确认"} 件，约 ${parsed.total_cbm ? parsed.total_cbm.toFixed(3) : "待确认"} CBM，${parsed.total_weight_kg ? parsed.total_weight_kg.toFixed(1) : "待确认"} KG`,
    `最大单件：${maxDimensions}`,
    `计费密度：${parsed.density_kg_per_cbm !== null ? `约 ${parsed.density_kg_per_cbm.toFixed(1)} KG/CBM` : "待确认"}`,
    `报价合计：${totalPrice}`,
    ...ruralConfirmationLines,
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
  const aiCargoItems = normalizeAICargoItems(extraction);
  const cargoItems = aiCargoItems.length ? aiCargoItems : parsed.cargo_items;
  const calculatedCbm = cargoItems.length && cargoItems.every((item) => item.cbm !== null)
    ? round3(cargoItems.reduce(
        (sum, item) => sum + (item.total_cbm ?? item.cbm! * item.quantity),
        0,
      ))
    : null;
  const calculatedWeight = cargoItems.length && cargoItems.every((item) => item.weight_kg !== null)
    ? round1(cargoItems.reduce(
        (sum, item) => sum + (item.total_weight_kg ?? item.weight_kg! * item.quantity),
        0,
      ))
    : null;
  const totalCbm = calculatedCbm ?? toNumber(extraction.cbm) ?? parsed.total_cbm;
  const totalWeight = calculatedWeight ?? toNumber(extraction.weight_kg) ?? parsed.total_weight_kg;
  const density = totalCbm > 0 && totalWeight > 0 ? round1(totalWeight / totalCbm) : parsed.density_kg_per_cbm;
  const provinceCode = extraction.province || parsed.address.province_code;
  const province = config.provinces.find((item) => item.code.toLowerCase() === String(provinceCode ?? "").toLowerCase());
  const dimensionedItems = cargoItems.filter(hasCargoDimensions);
  const maxItem = dimensionedItems.reduce<ParsedCargoItem | null>(
    (current, item) => (!current || parsedCargoVolume(item) > parsedCargoVolume(current) ? item : current),
    null,
  );
  const dimensions = dimensionedItems.flatMap((item) => [item.length_cm, item.width_cm, item.height_cm]) as number[];
  const longestSide = dimensions.length
    ? Math.max(...dimensions)
    : toNumber(extraction.longest_side_cm) ?? parsed.longest_side_cm;
  const weights = cargoItems
    .map((item) => item.weight_kg)
    .filter((value): value is number => value !== null && value > 0);

  return {
    ...parsed,
    piece_count: extraction.piece_count ?? parsed.piece_count,
    total_cbm: totalCbm,
    total_weight_kg: totalWeight,
    density_kg_per_cbm: density,
    cargo_items: cargoItems,
    longest_side_cm: longestSide,
    heaviest_piece_kg: weights.length ? Math.max(...weights) : parsed.heaviest_piece_kg,
    max_dimensions_cm: maxItem
      ? [maxItem.length_cm!, maxItem.width_cm!, maxItem.height_cm!]
      : parsed.max_dimensions_cm,
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

function normalizeAICargoItems(extraction: AIExtractedQuoteDraft): ParsedCargoItem[] {
  if (!Array.isArray(extraction.cargo_items)) {
    return [];
  }
  return extraction.cargo_items.flatMap((item, index): ParsedCargoItem[] => {
      const length = toNumber(item.length_cm);
      const width = toNumber(item.width_cm);
      const height = toNumber(item.height_cm);
      const hasDimensions = Boolean(length && width && height);
      const quantity = Math.max(1, Number(item.quantity) || 1);
      const totalWeight = toNumber(item.total_weight_kg);
      const totalCbm = toNumber(item.total_cbm);
      const weight = toNumber(item.weight_kg) ?? (totalWeight === null ? null : totalWeight / quantity);
      const cbm = toNumber(item.cbm) ??
        (hasDimensions
          ? (length! * width! * height!) / 1_000_000
          : totalCbm === null
            ? null
            : totalCbm / quantity);
      if (
        !hasDimensions
        && weight === null
        && cbm === null
        && totalWeight === null
        && totalCbm === null
        && !item.source_span
      ) {
        return [];
      }
      const normalized: ParsedCargoItem = {
        id: index + 1,
        quantity,
        length_cm: length,
        width_cm: width,
        height_cm: height,
        weight_kg: weight,
        cbm,
        total_weight_kg: totalWeight ?? (weight === null ? null : weight * quantity),
        total_cbm: totalCbm ?? (cbm === null ? null : cbm * quantity),
        contained_customer_pieces: item.contained_customer_pieces ?? null,
        stackability: item.stackability ?? null,
        max_stack_layers: item.max_stack_layers ?? null,
        max_top_load_kg: toNumber(item.max_top_load_kg),
        floor_rotation_allowed: item.floor_rotation_allowed ?? null,
        source_span: item.source_span,
      };
      return [normalized];
    });
}

function hasCargoDimensions(
  item: ParsedCargoItem,
): item is ParsedCargoItem & { length_cm: number; width_cm: number; height_cm: number } {
  return item.length_cm !== null && item.width_cm !== null && item.height_cm !== null;
}

function parsedCargoVolume(item: ParsedCargoItem): number {
  if (item.cbm !== null) {
    return item.cbm;
  }
  return hasCargoDimensions(item)
    ? (item.length_cm * item.width_cm * item.height_cm) / 1_000_000
    : 0;
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

function round3(value: number): number {
  return Math.round(value * 1000) / 1000;
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
  if (record.quote_type === "fcl") {
    const totals = record.totals_by_currency ?? {};
    const entries = Object.entries(totals)
      .filter(([, value]) => value !== null && value !== undefined && value !== "")
      .map(([currency, value]) => `${currency} ${value}`);
    if (
      record.currency_code &&
      record.total_price_usd !== null &&
      record.total_price_usd !== undefined &&
      record.total_price_usd !== ""
    ) {
      entries.push(`折算 ${record.currency_code} ${record.total_price_usd}`);
    }
    return entries.length ? entries.join("；") : "待匹配";
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
  if (sourceType === "llm_auxiliary_advice") {
    return "LLM 辅助建议";
  }
  if (sourceType === "hermes_agent_correction") {
    return "历史 LLM 辅助建议";
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
