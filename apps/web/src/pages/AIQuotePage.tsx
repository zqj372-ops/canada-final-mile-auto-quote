import { FormEvent, useEffect, useState } from "react";
import {
  calculateAIAutoQuote,
  listAIConfigs,
  listWeComBots,
  type AIModelConfigPublic,
  type AIAutoQuoteResponse,
  type WeComBotConfigPublic,
} from "../api/client";
import ResultCard from "../components/ResultCard";
import RiskTags from "../components/RiskTags";

export default function AIQuotePage() {
  const [message, setMessage] = useState("");
  const [configs, setConfigs] = useState<AIModelConfigPublic[]>([]);
  const [wecomBots, setWecomBots] = useState<WeComBotConfigPublic[]>([]);
  const [selectedConfigId, setSelectedConfigId] = useState("");
  const [selectedWecomBotId, setSelectedWecomBotId] = useState("");
  const [autoSubmit, setAutoSubmit] = useState(true);
  const [notifyWecom, setNotifyWecom] = useState(false);
  const [result, setResult] = useState<AIAutoQuoteResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    void loadConfigs();
    void loadWecomBots();
  }, []);

  async function loadConfigs() {
    try {
      setConfigs(await listAIConfigs());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "AI 配置加载失败");
    }
  }

  async function loadWecomBots() {
    try {
      setWecomBots(await listWeComBots());
    } catch {
      setWecomBots([]);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setCopyState("idle");
    if (!message.trim()) {
      setError("请先粘贴客户原始消息");
      return;
    }

    setIsLoading(true);
    try {
      const response = await calculateAIAutoQuote({
        customer_message: message.trim(),
        ai_config_id: selectedConfigId ? Number(selectedConfigId) : null,
        auto_submit_when_complete: autoSubmit,
        notify_wecom: notifyWecom,
        wecom_bot_id: selectedWecomBotId ? Number(selectedWecomBotId) : null,
      });
      setResult(response);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "AI 自动报价失败");
    } finally {
      setIsLoading(false);
    }
  }

  async function copyReply() {
    if (!result?.customer_reply) {
      return;
    }
    try {
      await navigator.clipboard.writeText(result.customer_reply);
      setCopyState("copied");
      window.setTimeout(() => setCopyState("idle"), 2400);
    } catch {
      setCopyState("failed");
    }
  }

  const canCopyReply = Boolean(result?.customer_reply) && result?.manual_review_required === false;

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
      <header>
        <p className="text-sm font-medium text-blue-800">AI Auto Quote</p>
        <h1 className="mt-1 text-2xl font-semibold text-slate-950">
          AI 自动提取并报价
        </h1>
      </header>

      <div className="grid gap-6 xl:grid-cols-[0.85fr_1.15fr]">
        <section className="panel p-5">
          <h2 className="section-title">客户原始消息</h2>
          <p className="mt-1 text-sm leading-6 text-slate-600">
            AI 只负责提取字段和润色回复，Zone、托数、燃油、附加费和总价仍由后端 Quote Engine 计算。
          </p>

          {error && (
            <div
              className="mt-4 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900"
              role="alert"
            >
              {error}
            </div>
          )}

          <form className="mt-5 grid gap-4" onSubmit={handleSubmit}>
            <label>
              <span className="field-label">customer_message</span>
              <textarea
                className="field-input min-h-56"
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                placeholder="例如：帮我报一下 8888 Keele St, Concord ON L4K 2N2，4.2方 850kg 10箱，商业地址，需要预约"
              />
            </label>

            <label>
              <span className="field-label">AI 模型配置</span>
              <select
                className="field-input"
                value={selectedConfigId}
                onChange={(event) => setSelectedConfigId(event.target.value)}
              >
                <option value="">使用默认模型配置</option>
                {configs.map((config) => (
                  <option key={config.id} value={config.id}>
                    {config.name} / {config.model_name}
                    {config.is_default ? " / 默认" : ""}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex min-h-11 items-center gap-3 rounded-md border border-slate-200 px-3 py-2">
              <input
                className="h-4 w-4 rounded border-slate-300 text-blue-700 focus:ring-blue-700"
                type="checkbox"
                checked={autoSubmit}
                onChange={(event) => setAutoSubmit(event.target.checked)}
              />
              <span className="text-sm font-medium text-slate-800">
                字段完整时自动提交 Quote Engine 报价
              </span>
            </label>

            <fieldset className="grid gap-3 rounded-md border border-slate-200 p-3">
              <legend className="px-1 text-sm font-semibold text-slate-950">企业微信推送</legend>
              <label className="flex min-h-11 items-center gap-3">
                <input
                  className="h-4 w-4 rounded border-slate-300 text-blue-700 focus:ring-blue-700"
                  type="checkbox"
                  checked={notifyWecom}
                  onChange={(event) => setNotifyWecom(event.target.checked)}
                />
                <span className="text-sm font-medium text-slate-800">
                  成功报价后推送企业微信
                </span>
              </label>
              <label>
                <span className="field-label">wecom_bot_id</span>
                <select
                  className="field-input"
                  value={selectedWecomBotId}
                  onChange={(event) => setSelectedWecomBotId(event.target.value)}
                  disabled={!notifyWecom}
                >
                  <option value="">使用 ai_quote/default 机器人</option>
                  {wecomBots.map((bot) => (
                    <option key={bot.id} value={bot.id}>
                      {bot.name} / {bot.purpose}
                      {bot.is_default ? " / 默认" : ""}
                    </option>
                  ))}
                </select>
                <p className="field-hint">
                  字段缺失时仅在勾选后推送追问提示；manual_required 会自动通知人工确认群。
                </p>
              </label>
            </fieldset>

            <button className="btn-primary" type="submit" disabled={isLoading}>
              {isLoading ? "处理中..." : "AI 自动提取并报价"}
            </button>
          </form>
        </section>

        <div className="grid gap-6">
          {result ? (
            <>
              <section className="panel p-5">
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div>
                    <h2 className="section-title">AI 提取字段</h2>
                    <p className="mt-1 text-sm text-slate-600">
                      confidence: {result.extraction.confidence}
                    </p>
                  </div>
                  {result.manual_review_required && (
                    <span className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm font-semibold text-red-900">
                      需人工确认，不能直接发客户
                    </span>
                  )}
                </div>

                <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {Object.entries(result.extraction)
                    .filter(([key]) => !["missing_fields", "extraction_notes"].includes(key))
                    .map(([key, value]) => (
                      <div key={key} className="rounded-md border border-slate-200 p-3">
                        <dt className="metric-label">{key}</dt>
                        <dd className="metric-value break-words font-mono tabular-nums">
                          {formatValue(value)}
                        </dd>
                      </div>
                    ))}
                </div>

                <div className="mt-5 grid gap-4 md:grid-cols-2">
                  <div>
                    <h3 className="section-title">missing_fields</h3>
                    <div className="mt-3">
                      <RiskTags tags={result.missing_fields} />
                    </div>
                  </div>
                  <div>
                    <h3 className="section-title">extraction_notes</h3>
                    <p className="mt-3 rounded-md bg-slate-50 p-3 text-sm leading-6 text-slate-800">
                      {result.extraction.extraction_notes || "无"}
                    </p>
                  </div>
                </div>
              </section>

              <section
                className={`panel p-5 ${
                  result.manual_review_required
                    ? "border-red-300 bg-red-50"
                    : "border-emerald-300 bg-emerald-50"
                }`}
              >
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div>
                    <h2 className="section-title">客户回复</h2>
                    <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-800">
                      {result.customer_reply || "无客户回复"}
                    </p>
                    {result.internal_note && (
                      <p className="mt-3 text-sm font-medium text-slate-700">
                        内部备注：{result.internal_note}
                      </p>
                    )}
                  </div>
                  {!result.manual_review_required && (
                    <button
                      className="btn-primary shrink-0"
                      type="button"
                      onClick={copyReply}
                      disabled={!canCopyReply}
                    >
                      {copyState === "copied"
                        ? "已复制"
                        : copyState === "failed"
                          ? "复制失败"
                          : "一键复制报价"}
                    </button>
                  )}
                </div>
              </section>

              {result.quote_result && <ResultCard result={result.quote_result} />}
            </>
          ) : (
            <section className="panel flex min-h-72 items-center justify-center p-6 text-center">
              <div>
                <h2 className="text-lg font-semibold text-slate-950">
                  等待 AI 提取结果
                </h2>
                <p className="mt-2 max-w-md text-sm leading-6 text-slate-600">
                  字段缺失时只会生成追问话术；字段完整时才会调用后端确定性报价。
                </p>
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "未提取";
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  if (Array.isArray(value)) {
    return value.join(", ");
  }
  return String(value);
}
