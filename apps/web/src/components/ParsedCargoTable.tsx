import type { AIExtractedCargoItem, AIExtractedQuoteDraft, MoneyValue } from "../api/client";
import type { Draft } from "./quote-workbench/state";

type CargoTotals = Pick<AIExtractedQuoteDraft, "piece_count" | "weight_kg" | "cbm">;

export function CargoSummary({ cargo }: { cargo: CargoTotals }) {
  return <dl className="qw-cargo-totals">
    <div><dt>件数</dt><dd>{formatValue(cargo.piece_count, 0, "件")}</dd></div>
    <div><dt>毛重</dt><dd>{formatValue(cargo.weight_kg, 2, "kg")}</dd></div>
    <div><dt>体积</dt><dd>{formatValue(cargo.cbm, 3, "CBM", true)}</dd></div>
  </dl>;
}

export default function ParsedCargoTable({ extraction, draft }: { extraction: AIExtractedQuoteDraft; draft: Draft | null }) {
  const modified = draft && (["piece_count", "weight_kg", "cbm"] as const).some((field) => {
    const current = draft[field].trim();
    const original = extraction[field];
    return current === "" ? original != null : original == null || Number(current) !== Number(original);
  });
  return <section className="qw-cargo" aria-labelledby="cargo-parsed-heading">
    <h3 id="cargo-parsed-heading">件毛体解析</h3>
    <CargoSummary cargo={extraction} />
    {modified && <p className="qw-warning">汇总已人工修改。以下保留原始解析明细，报价按中栏确认值计算。</p>}
    <p className="qw-note">尺寸统一为 cm，重量统一为 kg；单件重量可能为均重。</p>
    {extraction.cargo_items.length ? <ol className="qw-cargo-items">
      {extraction.cargo_items.map((item, index) => <li key={index}>
        <header><h4>货物 {index + 1}</h4><strong>{item.quantity} 件</strong></header>
        <p className="qw-cargo-size">长 × 宽 × 高：{[item.length_cm, item.width_cm, item.height_cm].every((v) => v != null)
          ? `${[item.length_cm, item.width_cm, item.height_cm].map((v) => formatValue(v, 1)).join(" × ")} cm`
          : "尺寸未齐全"}</p>
        <table><caption className="sr-only">货物 {index + 1} 的重量与体积</caption>
          <thead><tr><th scope="col">项目</th><th scope="col">毛重 (kg)</th><th scope="col">体积 (CBM)</th></tr></thead>
          <tbody><tr><th scope="row">单件 / 均值</th><td>{formatValue(item.weight_kg, 2)}</td><td>{formatValue(item.cbm, 6)}</td></tr>
            <tr><th scope="row">本项合计</th><td>{formatValue(item.total_weight_kg, 2)}</td><td>{formatValue(item.total_cbm, 3, "", true)}</td></tr></tbody>
        </table>
        <div className="qw-cargo-formulas">
          {dimensionCalculation(item) && <p>{dimensionCalculation(item)}</p>}
          <p>{calculation(item, "weight_kg", "total_weight_kg", "毛重", "kg", 2, 0.005, 0.05)}</p>
          <p>{calculation(item, "cbm", "total_cbm", "体积", "CBM", 6, 0.0000005, 0.0005)}</p>
        </div>
        {item.source_span && <details className="qw-cargo-source"><summary>对应原文</summary><blockquote>{item.source_span}</blockquote></details>}
      </li>)}
    </ol> : <p className="qw-note">未返回可拆分的货物明细，请核对上方件毛体汇总。</p>}
  </section>;
}

function formatValue(value: MoneyValue, decimals: number, unit = "", fixed = false): string {
  if (value === null || value === "" || !Number.isFinite(Number(value))) return "未提供";
  const formatted = Number(value).toLocaleString("en-CA", { maximumFractionDigits: decimals, minimumFractionDigits: fixed ? decimals : 0 });
  return `${formatted}${unit ? ` ${unit}` : ""}`;
}

function calculation(item: AIExtractedCargoItem, unitKey: "weight_kg" | "cbm", totalKey: "total_weight_kg" | "total_cbm",
  label: string, unit: string, precision: number, perPieceTolerance: number, totalTolerance: number): string {
  const perPiece = item[unitKey];
  const total = item[totalKey];
  if (perPiece == null || total == null) return `${label}计算：明细未齐全，待核对`;
  // Display the API's totals. Never replace them with frontend arithmetic;
  // rounded per-piece averages can differ from the declared shipment total.
  const expression = `${formatValue(perPiece, precision)} ${unit}/件 × ${item.quantity} 件`;
  const difference = Math.abs(Number(perPiece) * item.quantity - Number(total));
  const tolerance = item.quantity * perPieceTolerance + totalTolerance;
  if (difference > tolerance + 1e-9) return `${label}计算：${expression}，与合计 ${formatValue(total, 3, unit)} 不一致，请核对`;
  return `${label}计算：${expression} ≈ ${formatValue(total, unit === "CBM" ? 3 : 2, unit, unit === "CBM")}`;
}

function dimensionCalculation(item: AIExtractedCargoItem): string | null {
  const dimensions = [item.length_cm, item.width_cm, item.height_cm];
  if (dimensions.some((value) => value == null) || item.cbm == null) return null;
  const expression = dimensions.map((value) => formatValue(value, 6)).join(" × ") + " ÷ 1,000,000";
  const calculated = dimensions.reduce<number>((product, value) => product * Number(value), 1) / 1_000_000;
  if (Math.abs(calculated - Number(item.cbm)) > 0.0000005 + 1e-9) {
    return `尺寸计算：${expression}，与单件体积 ${formatValue(item.cbm, 6, "CBM")} 不一致，请核对`;
  }
  return `单件体积：${expression} ≈ ${formatValue(item.cbm, 6, "CBM")}`;
}
