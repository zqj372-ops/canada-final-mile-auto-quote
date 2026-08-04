import { useState } from "react";
import type { MoneyValue, ZoneQuoteResult } from "../api/client";
import { formatBillingPalletSummary } from "../utils/quoteResultView";

interface ResultCardProps {
  result: ZoneQuoteResult;
}

/** Minimal public quote result.  Audit-only fields are intentionally not part
 * of the client type or this component's rendering contract. */
export default function ResultCard({ result }: ResultCardProps) {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const isManual = result.manual_review_required;
  const canCopy = !isManual && Boolean(result.sales_note);

  async function copySalesNote() {
    if (!result.sales_note) {
      return;
    }
    try {
      await navigator.clipboard.writeText(result.sales_note);
      setCopyState("copied");
      window.setTimeout(() => setCopyState("idle"), 2400);
    } catch {
      setCopyState("failed");
    }
  }

  return (
    <section className="panel overflow-hidden" aria-live="polite">
      <div
        className={`border-b px-5 py-4 ${
          isManual ? "border-red-200 bg-red-50" : "border-emerald-200 bg-emerald-50"
        }`}
      >
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <p className={`text-sm font-semibold ${isManual ? "text-red-900" : "text-emerald-900"}`}>
              {isManual ? "需人工确认，不要直接发客户" : "报价已锁定，可复制给销售"}
            </p>
            <h2 className="mt-1 text-xl font-semibold text-slate-950">
              {isManual ? "需要人工确认" : formatMoney(result.total_price_usd)}
            </h2>
            <p className="mt-1 text-sm text-slate-700">
              Quote ID: <span className="font-mono text-xs">{result.quote_id}</span>
            </p>
          </div>
          {!isManual && (
            <button className="btn-primary" type="button" onClick={copySalesNote} disabled={!canCopy}>
              {copyState === "copied"
                ? "已复制"
                : copyState === "failed"
                  ? "复制失败"
                  : "一键复制销售报价"}
            </button>
          )}
        </div>
        {isManual && (
          <div className="mt-3 rounded-md border border-red-300 bg-white px-3 py-2 text-sm text-red-900">
            系统没有可直接发送给客户的自动报价，请进入人工确认池处理。
          </div>
        )}
      </div>

      <div className="grid gap-5 p-5 xl:grid-cols-[1fr_0.8fr]">
        <div className="space-y-5">
          <div>
            <h3 className="section-title">报价结果</h3>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <Metric label="算托摘要" value={formatBillingPalletSummary(result)} />
              <Metric label="报价合计" value={isManual ? "需要人工确认" : formatMoney(result.total_price_usd)} />
            </div>
          </div>
        </div>
        <div>
          <h3 className="section-title">销售备注</h3>
          <p className="mt-3 min-h-24 rounded-md bg-slate-50 p-3 text-sm leading-6 text-slate-800">
            {result.sales_note || (isManual ? "需要人工确认后再生成销售报价。" : "未生成销售备注")}
          </p>
        </div>
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white p-3">
      <dt className="metric-label">{label}</dt>
      <dd className="metric-value break-words font-mono tabular-nums">{value}</dd>
    </div>
  );
}

function formatMoney(value: MoneyValue): string {
  if (value === null || value === undefined || value === "") {
    return "未返回";
  }
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? `$${numberValue.toFixed(2)}` : `$${String(value)}`;
}
