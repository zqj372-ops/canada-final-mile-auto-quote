import type { QuoteWorkbenchConfig, ZoneQuoteResult } from "../api/client";
import type { ParsedQuoteInput } from "../utils/quoteParser";
import QuoteCopyButton from "./QuoteCopyButton";

export default function QuoteCalculationPanel({
  config,
  parsed,
  result,
  aiParsed,
  salesText,
  onExport,
}: {
  config: QuoteWorkbenchConfig;
  parsed: ParsedQuoteInput;
  result: ZoneQuoteResult | null;
  aiParsed: boolean;
  salesText: string;
  onExport: () => void;
}) {
  const waitingForAI = !aiParsed && !result;
  const manualRequired = result?.manual_review_required ?? (aiParsed && Boolean(parsed.missing_fields.length));
  const totalPrice = result?.total_price_usd;
  const currency = config.copy_template?.currency_code ?? "USD";
  const manualPriceText = config.copy_template?.manual_price_text ?? "需要人工确认";

  return (
    <section className="panel min-w-0 p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase text-slate-500">
            AI 报价结果
          </p>
          <h2 className="mt-2 section-title text-lg">
            {waitingForAI ? "等待 AI 解析" : manualRequired ? "需要人工复核" : "报价完成"}
          </h2>
        </div>
        <span
          className={`rounded-full border px-3 py-1 text-xs font-semibold ${
            manualRequired
              ? "border-amber-200 bg-amber-50 text-amber-700"
              : "border-emerald-200 bg-emerald-50 text-emerald-700"
          }`}
        >
          {waitingForAI ? "待解析" : `报价可信度 ${result?.confidence ?? parsed.confidence}%`}
        </span>
      </div>

      {waitingForAI && (
        <div className="mt-3 rounded-md border border-cyan-200 bg-cyan-50 px-3 py-2 text-sm font-semibold leading-6 text-cyan-700">
          点击“开始智能报价”后，系统会调用后台配置的大模型解析字段，再交给 Quote Engine 查表报价。
        </div>
      )}

      {!waitingForAI && manualRequired && (
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm font-semibold leading-6 text-amber-700">
          需人工确认，不要直接发客户。原因：{result?.matched_rule || parsed.missing_fields.join("、") || "价格表未命中"}
        </div>
      )}

      <div className="mt-3 grid grid-cols-2 gap-2 xl:grid-cols-3">
        <Metric label="来源类型" value={formatSourceType(result?.source_type)} />
        <Metric label="邮编前缀" value={result?.postal_prefix || parsed.address.postal_code?.slice(0, 3) || "待确认"} />
        <Metric label="系统城市" value={result?.preferred_city || result?.city || parsed.address.city || "待确认"} />
        <Metric label="省份" value={result?.province || parsed.address.province_code || "待确认"} />
        <Metric label="始发仓" value={result?.origin || "待匹配"} />
        <Metric label="Zone" value={result?.zone !== null && result?.zone !== undefined ? String(result.zone) : "待匹配"} />
        <Metric label="计费托数" value={result?.billing_pallets ? `${result.billing_pallets} 托` : "待计算"} />
        <Metric label="托数拆解" value={formatPalletBreakdown(result?.pallet_breakdown)} />
        <Metric label="基础派送费" value={formatMoney(result?.base_price_usd, currency)} />
        <Metric label="燃油附加费" value={formatMoney(result?.fuel_usd, currency)} />
        <Metric label="风险缓冲" value="未配置" />
      </div>

      <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-3">
        <h3 className="text-sm font-semibold text-slate-700">附加费</h3>
        <div className="mt-3 grid gap-2">
          {result?.accessorials && Object.keys(result.accessorials).length ? (
            Object.entries(result.accessorials).map(([key, value]) => (
                <div key={key} className="flex items-center justify-between gap-3 text-sm">
                <span className="text-slate-600">{config.accessorial_labels?.[key] || key}</span>
                <span className="font-semibold text-slate-900 tabular-nums">{formatMoney(value, currency)}</span>
              </div>
            ))
          ) : (
            <p className="text-sm text-slate-500">暂无已确认附加费</p>
          )}
        </div>
      </div>

      <div className="mt-3 rounded-lg border border-teal-200 bg-teal-50 p-2.5">
        <p className="text-sm font-medium text-slate-700">报价合计</p>
        <p className="mt-1 text-xl font-bold text-slate-900 tabular-nums sm:text-2xl">
          {totalPrice && !manualRequired
            ? formatMoney(totalPrice, currency)
            : waitingForAI
              ? "待 AI 解析"
              : manualPriceText}
        </p>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <QuoteCopyButton text={salesText} disabled={manualRequired || !salesText.trim()} />
        <button className="btn-secondary" type="button" onClick={onExport} disabled={!salesText.trim()}>
          导出报价
        </button>
      </div>

      {result?.internal_note && (
        <p className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-2.5 text-sm leading-6 text-slate-600">
          内部备注：{result.internal_note}
        </p>
      )}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white p-2">
      <dt className="text-xs font-medium text-slate-500">{label}</dt>
      <dd className="mt-1 break-words text-sm font-semibold text-slate-900 tabular-nums">{value}</dd>
    </div>
  );
}

function formatSourceType(sourceType: string | undefined): string {
  if (!sourceType) {
    return "待匹配";
  }
  if (sourceType === "zone_matrix") {
    return "Zone 价格矩阵";
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
  return sourceType;
}

function formatPalletBreakdown(breakdown: Record<string, number> | null | undefined): string {
  if (!breakdown || Object.keys(breakdown).length === 0) {
    return "待计算";
  }
  const labels: Record<string, string> = {
    volume_pallets: "体积",
    weight_pallets: "重量",
    long_piece_pallets: "超长",
    wooden_crate_pallets: "木箱",
    explicit_pallet_count: "显式",
    normal_basis_pallets: "基础",
  };
  return Object.entries(breakdown)
    .map(([key, value]) => `${labels[key] || key}:${value}`)
    .join(" / ");
}

function formatMoney(value: string | number | null | undefined, currency: string): string {
  if (value === null || value === undefined || value === "") {
    return "待匹配";
  }
  const numberValue = Number(value);
  if (!Number.isFinite(numberValue)) {
    return `${currency} ${value}`;
  }
  return `${currency} ${numberValue.toFixed(2)}`;
}
