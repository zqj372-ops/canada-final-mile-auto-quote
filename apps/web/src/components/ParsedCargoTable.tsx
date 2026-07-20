import type { ParsedQuoteInput } from "../utils/quoteParser";

export default function ParsedCargoTable({
  parsed,
  isAwaitingAI = false,
}: {
  parsed: ParsedQuoteInput;
  isAwaitingAI?: boolean;
}) {
  return (
    <section className="panel min-w-0 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase text-slate-500">
            AI 识别结果
          </p>
          <h2 className="mt-2 section-title text-lg">货物信息</h2>
        </div>
        <span className="rounded-full border border-slate-200 bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700">
          {isAwaitingAI ? "待 AI 解析" : `${parsed.piece_count || "待确认"} 件`}
        </span>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 xl:grid-cols-4">
        <Metric label="总体积" value={isAwaitingAI ? "待 AI 解析" : parsed.total_cbm ? `${parsed.total_cbm.toFixed(3)} CBM` : "待确认"} />
        <Metric label="总重量" value={isAwaitingAI ? "待 AI 解析" : parsed.total_weight_kg ? `${parsed.total_weight_kg.toFixed(1)} KG` : "待确认"} />
        <Metric
          label="计费密度"
          value={isAwaitingAI ? "待 AI 解析" : parsed.density_kg_per_cbm !== null ? `${parsed.density_kg_per_cbm.toFixed(1)} KG/CBM` : "待确认"}
        />
        <Metric
          label="最大单件"
          value={
            isAwaitingAI
              ? "待 AI 解析"
              : parsed.max_dimensions_cm
                ? `${parsed.max_dimensions_cm.join(" × ")} cm`
                : parsed.piece_count || parsed.total_cbm || parsed.total_weight_kg
                  ? "原文未提供尺寸"
                  : "待确认"
          }
        />
      </div>

      <div className="mt-3 overflow-x-auto rounded-md border border-slate-200">
        <table className="w-full min-w-[460px] text-left text-sm">
          <thead className="bg-slate-50 text-xs text-slate-600">
            <tr>
              <th className="px-3 py-2 font-semibold">序号</th>
              <th className="px-3 py-2 font-semibold">数量</th>
              <th className="px-3 py-2 font-semibold">长</th>
              <th className="px-3 py-2 font-semibold">宽</th>
              <th className="px-3 py-2 font-semibold">高</th>
              <th className="px-3 py-2 font-semibold">单件重量</th>
              <th className="px-3 py-2 font-semibold">单件体积</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 text-slate-700">
            {parsed.cargo_items.length ? (
              parsed.cargo_items.map((item) => (
                <tr key={item.id} title={item.source_span ?? undefined}>
                  <td className="px-3 py-2 tabular-nums">{hasDimensions(item) ? item.id : "汇总"}</td>
                  <td className="px-3 py-2 tabular-nums">{item.quantity} 件</td>
                  <td className="px-3 py-2 tabular-nums">{formatDimension(item.length_cm)}</td>
                  <td className="px-3 py-2 tabular-nums">{formatDimension(item.width_cm)}</td>
                  <td className="px-3 py-2 tabular-nums">{formatDimension(item.height_cm)}</td>
                  <td className="px-3 py-2 tabular-nums">
                    {item.weight_kg !== null
                      ? `${hasDimensions(item) ? "" : "约 "}${item.weight_kg.toFixed(2)} KG`
                      : "未提供"}
                  </td>
                  <td className="px-3 py-2 tabular-nums">
                    {item.cbm !== null
                      ? `${hasDimensions(item) ? "" : "约 "}${item.cbm.toFixed(3)} CBM`
                      : "未提供"}
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td className="px-3 py-5 text-center text-slate-500" colSpan={7}>
                  {isAwaitingAI
                    ? "点击开始智能报价后，由后台大模型解析并回填货物信息"
                    : parsed.piece_count || parsed.total_cbm || parsed.total_weight_kg
                      ? "已识别汇总数据，但原文没有可拆分的尺寸明细"
                      : "未能识别货物数据，请检查原始询价格式"}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function hasDimensions(item: ParsedQuoteInput["cargo_items"][number]): boolean {
  return item.length_cm !== null && item.width_cm !== null && item.height_cm !== null;
}

function formatDimension(value: number | null): string {
  return value === null ? "未提供" : `${value} cm`;
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white p-2.5">
      <dt className="text-xs font-medium text-slate-500">{label}</dt>
      <dd className="mt-1 text-sm font-semibold text-slate-900 tabular-nums">{value}</dd>
    </div>
  );
}
