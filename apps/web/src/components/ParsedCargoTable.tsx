import type { ParsedQuoteInput } from "../utils/quoteParser";

export default function ParsedCargoTable({
  parsed,
  isAwaitingAI = false,
}: {
  parsed: ParsedQuoteInput;
  isAwaitingAI?: boolean;
}) {
  return (
    <section className="ai-glass-panel min-w-0 p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase text-violet-200">
            AI 识别结果
          </p>
          <h2 className="mt-2 text-xl font-semibold text-white">货物信息</h2>
        </div>
        <span className="rounded-full bg-white/10 px-3 py-1 text-xs font-semibold text-slate-200">
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
          value={isAwaitingAI ? "待 AI 解析" : parsed.max_dimensions_cm ? `${parsed.max_dimensions_cm.join(" × ")} cm` : "待确认"}
        />
      </div>

      <div className="mt-3 overflow-x-auto rounded-md border border-white/10">
        <table className="w-full min-w-[460px] text-left text-sm">
          <thead className="bg-white/[0.06] text-xs text-cyan-100">
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
          <tbody className="divide-y divide-white/10 text-slate-200">
            {parsed.cargo_items.length ? (
              parsed.cargo_items.map((item) => (
                <tr key={item.id}>
                  <td className="px-3 py-2 tabular-nums">{item.id}</td>
                  <td className="px-3 py-2 tabular-nums">{item.quantity} 件</td>
                  <td className="px-3 py-2 tabular-nums">{item.length_cm} cm</td>
                  <td className="px-3 py-2 tabular-nums">{item.width_cm} cm</td>
                  <td className="px-3 py-2 tabular-nums">{item.height_cm} cm</td>
                  <td className="px-3 py-2 tabular-nums">{item.weight_kg.toFixed(1)} KG</td>
                  <td className="px-3 py-2 tabular-nums">{item.cbm.toFixed(3)} CBM</td>
                </tr>
              ))
            ) : (
              <tr>
                <td className="px-3 py-5 text-center text-slate-400" colSpan={7}>
                  {isAwaitingAI ? "点击开始智能报价后，由后台大模型解析并回填货物信息" : "待识别货物尺寸和重量"}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-white/10 bg-white/[0.04] p-2.5">
      <dt className="text-xs font-medium text-slate-400">{label}</dt>
      <dd className="mt-1 text-sm font-semibold text-white tabular-nums">{value}</dd>
    </div>
  );
}
