import type { QuoteWorkbenchConfig, ZoneQuoteResult } from "../api/client";
import type { ParsedQuoteInput } from "../utils/quoteParser";
import { formatBillingPalletSummary } from "../utils/quoteResultView";
import QuoteCopyButton from "./QuoteCopyButton";

export default function QuoteCalculationPanel({
  config,
  parsed,
  result,
  aiParsed,
  salesText,
  onExport,
  ruralConfirmationRequired = false,
  ruralConfirmationAcknowledged = false,
}: {
  config: QuoteWorkbenchConfig;
  parsed: ParsedQuoteInput;
  result: ZoneQuoteResult | null;
  aiParsed: boolean;
  salesText: string;
  onExport: () => void;
  ruralConfirmationRequired?: boolean;
  ruralConfirmationAcknowledged?: boolean;
}) {
  const waitingForAI = !aiParsed && !result;
  const manualRequired = result?.manual_review_required ?? (aiParsed && Boolean(parsed.missing_fields.length));
  const totalPrice = result?.total_price_usd;
  const currency = config.copy_template?.currency_code ?? "USD";
  const manualPriceText = config.copy_template?.manual_price_text ?? "需要人工确认";
  const requiresRuralConfirmation = Boolean(
    ruralConfirmationRequired || parsed.risk_hints.includes("rural_fsa_secondary_confirmation"),
  );
  const ruralActionsLocked = Boolean(requiresRuralConfirmation && !ruralConfirmationAcknowledged);
  const billingPalletSummary = waitingForAI
    ? "待计算"
    : formatBillingPalletSummary(result ?? {
      billing_pallets: null,
      manual_review_required: manualRequired,
    });

  return (
    <section className="panel min-w-0 p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase text-slate-500">AI 报价结果</p>
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
          {waitingForAI ? "待解析" : manualRequired ? "需要人工确认" : "报价已完成"}
        </span>
      </div>

      {waitingForAI && (
        <div className="mt-3 rounded-md border border-cyan-200 bg-cyan-50 px-3 py-2 text-sm font-semibold leading-6 text-cyan-700">
          点击“开始智能报价”后，系统会调用后台配置的大模型解析字段，再交给 Quote Engine 查表报价。
        </div>
      )}

      {!waitingForAI && manualRequired && (
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm font-semibold leading-6 text-amber-700">
          需人工确认，不要直接发客户。请补充缺失的实际搬运单元尺寸和单重，或由运营在内部审计页复核。
        </div>
      )}

      {requiresRuralConfirmation && (
        <div
          className={`mt-3 rounded-md border-2 px-3 py-2 text-sm font-semibold leading-6 ${
            ruralConfirmationAcknowledged
              ? "border-teal-300 bg-teal-50 text-teal-900"
              : "border-amber-400 bg-amber-50 text-amber-900"
          }`}
          role="status"
        >
          {ruralConfirmationAcknowledged ? "已完成本次乡村邮编二次确认。" : "乡村邮编需二次确认。"}
          仍请保留完整地址、服务城市、卡车准入和偏远附加费的核对记录。
        </div>
      )}

      <div className="mt-3 grid grid-cols-2 gap-2 xl:grid-cols-3">
        <Metric label="算托摘要" value={billingPalletSummary} />
        <Metric label="报价合计" value={totalPrice && !manualRequired ? formatMoney(totalPrice, currency) : manualRequired ? manualPriceText : "待计算"} />
        <Metric label="货物件数" value={parsed.piece_count ? `${parsed.piece_count} 件` : "待确认"} />
        <Metric label="总体积" value={parsed.total_cbm ? `${parsed.total_cbm.toFixed(3)} CBM` : "待确认"} />
        <Metric label="总重量" value={parsed.total_weight_kg ? `${parsed.total_weight_kg.toFixed(1)} KG` : "待确认"} />
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
        <QuoteCopyButton text={salesText} disabled={manualRequired || !salesText.trim() || ruralActionsLocked} />
        <button className="btn-secondary" type="button" onClick={onExport} disabled={!salesText.trim() || ruralActionsLocked}>
          导出报价
        </button>
      </div>
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

function formatMoney(value: string | number | null | undefined, currency: string): string {
  if (value === null || value === undefined || value === "") {
    return "未返回";
  }
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? `${currency} ${numberValue.toFixed(2)}` : `${currency} ${String(value)}`;
}
