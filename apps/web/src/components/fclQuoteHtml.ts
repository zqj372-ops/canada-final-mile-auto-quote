import type { FCLQuoteResult } from "../api/client";
import {
  FCL_ADDRESS_TYPES,
  FCL_CUSTOMER_TYPES,
  FCL_DEADLINE_STRICTNESS,
  FCL_IMPORTER_EXISTS,
  FCL_SERVICE_STAGES,
  FCL_SPECIAL_ATTRIBUTES,
  FCL_TRADE_TERMS,
  labelOf,
} from "./fclFieldLabels";

function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatMoney(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "按实际/人工确认";
  }
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue.toFixed(2) : String(value);
}

export function buildFclQuoteHtml(result: FCLQuoteResult): string {
  const normalized = result.normalized_input;
  const containers = normalized.containers
    .map((item) => `${escapeHtml(item.container_type)} × ${escapeHtml(item.quantity)}`)
    .join("、");
  const visibleItems = result.fee_items.filter((item) =>
    ["both", "quoteOnly", "merged"].includes(item.display_mode),
  );
  const hiddenIncluded = result.fee_items.filter(
    (item) => item.included && item.display_mode === "hiddenIncluded",
  );
  const totalsRows = Object.entries(result.totals_by_currency)
    .map(
      ([currency, amount]) =>
        `<div class="total-line"><span>${escapeHtml(currency)} 合计</span><span>${escapeHtml(currency)} ${formatMoney(amount)}</span></div>`,
    )
    .join("");
  const convertedRow =
    result.settlement_currency && result.converted_total !== null && result.converted_total !== undefined
      ? `<div class="total-line grand"><span>折算合计（${escapeHtml(result.settlement_currency)}）</span><span>${escapeHtml(result.settlement_currency)} ${formatMoney(result.converted_total)}</span></div>`
      : "";
  const feeRows = visibleItems
    .map((item) => {
      const amount = item.amount === null || item.amount === undefined || item.amount === ""
        ? "按实际/人工确认"
        : `${escapeHtml(item.currency)} ${formatMoney(item.amount)}`;
      const unitPrice = item.unit_price === null || item.unit_price === undefined || item.unit_price === ""
        ? "—"
        : `${escapeHtml(item.currency)} ${formatMoney(item.unit_price)}`;
      return `<tr>
        <td>${escapeHtml(item.item_name)}${item.description ? `<div class="muted">${escapeHtml(item.description)}</div>` : ""}</td>
        <td>${escapeHtml(item.quantity)} ${escapeHtml(item.unit)}</td>
        <td>${unitPrice}</td>
        <td class="num">${amount}</td>
      </tr>`;
    })
    .join("");
  const termsRows = result.public_terms.map((term) => `<li>${escapeHtml(term)}</li>`).join("");
  const conflicts = result.cargo_calculation.conflicts.length
    ? `<div class="warn">货物声明值与确定性重算存在差异：${escapeHtml(result.cargo_calculation.conflicts.join("、"))}</div>`
    : "";
  const specialAttributes = normalized.special_attributes
    .map((value) => labelOf(FCL_SPECIAL_ATTRIBUTES, value))
    .join("、");
  const serviceStages = (normalized.service_stages ?? [])
    .map((value) => labelOf(FCL_SERVICE_STAGES, value))
    .join("、");

  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>整柜报价单 ${escapeHtml(result.quote_id)}</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; color: #111827; margin: 0; }
  .sheet { max-width: 210mm; margin: 0 auto; padding: 12mm 10mm; }
  .brand { display: flex; justify-content: space-between; gap: 16px; border-bottom: 3px solid #0f766e; padding-bottom: 10px; }
  .brand h1 { margin: 0; font-size: 22px; }
  .brand .muted { color: #6b7280; font-size: 12px; line-height: 1.6; }
  .meta { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 24px; margin: 14px 0; font-size: 13px; }
  .meta .label { color: #6b7280; }
  table { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 12px; }
  th { background: #f3f4f6; text-align: left; padding: 6px 8px; }
  td { border-top: 1px solid #e5e7eb; padding: 7px 8px; vertical-align: top; }
  .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .muted { color: #6b7280; font-size: 11px; margin-top: 2px; }
  .totals { margin-left: auto; width: 240px; font-size: 13px; }
  .total-line { display: flex; justify-content: space-between; padding: 4px 0; }
  .grand { font-weight: 700; border-top: 2px solid #111827; margin-top: 4px; padding-top: 8px; font-size: 15px; }
  .terms { margin-top: 20px; font-size: 12px; color: #374151; }
  .terms h3 { font-size: 13px; }
  .terms li { margin: 3px 0; }
  .warn { border: 1px solid #f59e0b; background: #fffbeb; color: #92400e; padding: 8px 10px; border-radius: 6px; font-size: 12px; }
  footer { margin-top: 28px; padding-top: 8px; border-top: 1px solid #e5e7eb; color: #6b7280; font-size: 11px; text-align: center; }
  @media print {
    body { print-color-adjust: exact; -webkit-print-color-adjust: exact; }
    .sheet { padding: 0; }
  }
</style>
</head>
<body>
<div class="sheet">
  <header class="brand">
    <div>
      <h1>${escapeHtml(result.company_name || "整柜报价单")}</h1>
      <div class="muted">${escapeHtml(result.company_address)}${result.company_phone ? `<br>${escapeHtml(result.company_phone)}` : ""}${result.company_email ? `<br>${escapeHtml(result.company_email)}` : ""}</div>
    </div>
    <div class="muted">
      <div>报价编号：${escapeHtml(result.quote_id)}</div>
      <div>报价有效期至：${escapeHtml(result.quote_valid_until ?? "—")}</div>
      <div>Renderer：${escapeHtml(result.renderer_version)}</div>
    </div>
  </header>

  <div class="meta">
    <div><span class="label">客户 / 联系人</span><br>${escapeHtml(normalized.customer_name || "—")} / ${escapeHtml(normalized.contact || "—")}</div>
    <div><span class="label">客户类型</span><br>${escapeHtml(labelOf(FCL_CUSTOMER_TYPES, normalized.customer_type))}</div>
    <div><span class="label">起运港</span><br>${escapeHtml(normalized.pol || "待确认")}</div>
    <div><span class="label">目的港</span><br>${escapeHtml(normalized.pod || "待确认")}</div>
    <div><span class="label">目的邮编 / 收货地址</span><br>${escapeHtml(normalized.destination_postal_code || "—")}${normalized.destination_postal_code && normalized.destination_address ? "<br>" : " / "}${escapeHtml(normalized.destination_address || "—")}</div>
    <div><span class="label">柜型柜量</span><br>${containers || "待确认"}</div>
    <div><span class="label">服务范围</span><br>${escapeHtml(normalized.service_scope || "待确认")}</div>
    <div><span class="label">服务环节</span><br>${escapeHtml(serviceStages || "—")}</div>
    <div><span class="label">货名 / 材质用途</span><br>${escapeHtml(normalized.cargo_name || "—")}${normalized.cargo_details ? ` / ${escapeHtml(normalized.cargo_details)}` : ""}</div>
    <div><span class="label">特殊属性</span><br>${escapeHtml(specialAttributes || "—")}</div>
    <div><span class="label">件数 / 总毛重 / 总体积</span><br>${escapeHtml(result.cargo_calculation.piece_count ?? "—")} 件 / ${escapeHtml(result.cargo_calculation.total_weight_kg ?? "—")} KG / ${escapeHtml(result.cargo_calculation.total_volume_cbm ?? "—")} CBM</div>
    <div><span class="label">货值 / HS / 原产地</span><br>${escapeHtml(normalized.cargo_value ? `${normalized.cargo_value_currency ?? ""} ${normalized.cargo_value}` : "—")} / ${escapeHtml(normalized.hs_code || "—")} / ${escapeHtml(normalized.origin_country || "—")}</div>
    <div><span class="label">备货 / ETD / 期望到门</span><br>${escapeHtml(normalized.ready_date || "—")} / ${escapeHtml(normalized.target_etd || "—")} / ${escapeHtml(normalized.expected_delivery_date || "—")}（${escapeHtml(labelOf(FCL_DEADLINE_STRICTNESS, normalized.deadline_strictness))}）</div>
    <div><span class="label">贸易条款 / 进口商</span><br>${escapeHtml(labelOf(FCL_TRADE_TERMS, normalized.trade_terms))} / ${escapeHtml(labelOf(FCL_IMPORTER_EXISTS, normalized.importer_exists))}</div>
    <div><span class="label">到门信息</span><br>${escapeHtml(labelOf(FCL_ADDRESS_TYPES, normalized.address_type))} / 尾板 ${escapeHtml(normalized.tail_lift || "—")} / 叉车 ${escapeHtml(normalized.forklift || "—")}${normalized.appointment_window ? ` / ${escapeHtml(normalized.appointment_window)}` : ""}</div>
    <div><span class="label">船东 / 渠道</span><br>${escapeHtml(normalized.carrier || "—")} / ${escapeHtml(normalized.service_preference || "—")}</div>
  </div>

  ${conflicts}

  <table>
    <thead><tr><th>费用项目</th><th>数量</th><th>单价</th><th class="num">金额</th></tr></thead>
    <tbody>${feeRows || `<tr><td colspan="4">无自动计价费用（待人工复核）</td></tr>`}</tbody>
  </table>

  <div class="totals">
    ${totalsRows}
    ${convertedRow}
  </div>

  <div class="terms">
    <h3>包含与不包含 / 条款</h3>
    <ul>${termsRows || "<li>—</li>"}</ul>
  </div>

  <footer>${escapeHtml(result.footer)}</footer>
</div>
</body>
</html>`;
}

export function printFclQuoteHtml(result: FCLQuoteResult): void {
  const frame = document.createElement("iframe");
  frame.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden;";
  frame.srcdoc = buildFclQuoteHtml(result);
  frame.sandbox.add("allow-same-origin");
  frame.addEventListener("load", () => {
    frame.contentWindow?.focus();
    frame.contentWindow?.print();
    window.setTimeout(() => frame.remove(), 1000);
  });
  document.body.appendChild(frame);
}
