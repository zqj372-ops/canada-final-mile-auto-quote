import { useState } from "react";
import type { MoneyValue, ZoneQuoteResult } from "../api/client";
import RiskTags from "./RiskTags";

interface ResultCardProps {
  result: ZoneQuoteResult;
}

export default function ResultCard({ result }: ResultCardProps) {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">(
    "idle",
  );
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
          isManual
            ? "border-red-200 bg-red-50"
            : "border-emerald-200 bg-emerald-50"
        }`}
      >
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <p
              className={`text-sm font-semibold ${
                isManual ? "text-red-900" : "text-emerald-900"
              }`}
            >
              {isManual ? "需人工确认，不要直接发客户" : "报价已锁定，可复制给销售"}
            </p>
            <h2 className="mt-1 text-xl font-semibold text-slate-950">
              {isManual
                ? "Manual Required"
                : formatMoney(result.total_price_usd)}
            </h2>
            <p className="mt-1 text-sm text-slate-700">
              Quote ID:{" "}
              <span className="font-mono text-xs">{result.quote_id}</span>
            </p>
          </div>

          {!isManual && (
            <button
              className="btn-primary"
              type="button"
              onClick={copySalesNote}
              disabled={!canCopy}
            >
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
            系统没有可直接发送给客户的自动报价。请进入人工确认池处理，原因：
            <span className="font-medium"> {result.matched_rule}</span>
          </div>
        )}
      </div>

      <div className="grid gap-5 p-5 xl:grid-cols-[1fr_0.8fr]">
        <div className="space-y-5">
          <div>
            <h3 className="section-title">报价结果</h3>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <Metric label="source_type" value={result.source_type} />
              <Metric label="confidence" value={`${result.confidence}`} />
              <Metric
                label={isManual ? "后端返回金额" : "total_price_usd"}
                value={
                  isManual && result.total_price_usd
                    ? `${formatMoney(result.total_price_usd)}（需确认）`
                    : formatMoney(result.total_price_usd)
                }
              />
              <Metric label="base_price_usd" value={formatMoney(result.base_price_usd)} />
              <Metric label="fuel_usd" value={formatMoney(result.fuel_usd)} />
              <Metric
                label="billing_pallets"
                value={formatNullable(result.billing_pallets)}
              />
            </div>
          </div>

          <div>
            <h3 className="section-title">匹配路径</h3>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <Metric label="postal_prefix" value={formatNullable(result.postal_prefix)} />
              <Metric label="preferred_city" value={formatNullable(result.preferred_city)} />
              <Metric label="city" value={formatNullable(result.city)} />
              <Metric label="province" value={formatNullable(result.province)} />
              <Metric label="origin" value={formatNullable(result.origin)} />
              <Metric label="zone" value={formatNullable(result.zone)} />
            </div>
            <p className="mt-3 rounded-md bg-slate-50 p-3 text-sm leading-6 text-slate-800">
              {result.matched_rule}
            </p>
          </div>

          <div>
            <h3 className="section-title">附加费</h3>
            <div className="mt-3 grid gap-2">
              {Object.entries(result.accessorials).length ? (
                Object.entries(result.accessorials).map(([key, value]) => (
                  <div
                    key={key}
                    className="flex items-center justify-between rounded-md border border-slate-200 px-3 py-2"
                  >
                    <span className="text-sm text-slate-700">{key}</span>
                    <span className="font-mono text-sm font-semibold text-slate-950">
                      {formatMoney(value)}
                    </span>
                  </div>
                ))
              ) : (
                <p className="text-sm text-slate-500">无附加费</p>
              )}
            </div>
          </div>
        </div>

        <div className="space-y-5">
          <div>
            <h3 className="section-title">风险标签</h3>
            <div className="mt-3">
              <RiskTags tags={result.risk_tags} />
            </div>
          </div>

          <div>
            <h3 className="section-title">销售备注</h3>
            <p className="mt-3 min-h-24 rounded-md bg-slate-50 p-3 text-sm leading-6 text-slate-800">
              {result.sales_note || "未生成销售备注"}
            </p>
          </div>

          <div>
            <h3 className="section-title">内部备注</h3>
            <p className="mt-3 min-h-24 rounded-md bg-slate-50 p-3 text-sm leading-6 text-slate-800">
              {result.internal_note || "无内部备注"}
            </p>
          </div>
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
  if (Number.isFinite(numberValue)) {
    return `$${numberValue.toFixed(2)}`;
  }

  return `$${String(value)}`;
}

function formatNullable(value: string | number | null): string {
  if (value === null || value === undefined || value === "") {
    return "未返回";
  }
  return String(value);
}
