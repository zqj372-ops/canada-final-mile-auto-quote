export default function QuoteRiskPanel({
  title = "报价风险提示",
  risks,
  manualRequired,
}: {
  title?: string;
  risks: string[];
  manualRequired: boolean;
}) {
  return (
    <section
      className={`ai-glass-panel p-5 ${
        manualRequired ? "border-amber-300/60 shadow-[0_0_28px_rgba(245,158,11,0.18)]" : ""
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-xl font-semibold text-white">{title}</h2>
        {manualRequired && (
          <span className="rounded-full border border-amber-300/60 bg-amber-300/10 px-3 py-1 text-xs font-semibold text-amber-100">
            不能直接发客户
          </span>
        )}
      </div>
      <div className="mt-4 grid gap-2">
        {risks.length ? (
          risks.map((risk) => (
            <div key={risk} className="rounded-md border border-amber-200/20 bg-amber-300/10 px-3 py-2 text-sm leading-6 text-amber-50">
              {risk}
            </div>
          ))
        ) : (
          <div className="rounded-md border border-white/10 bg-white/[0.04] px-3 py-3 text-sm text-slate-300">
            暂无额外风险提示
          </div>
        )}
      </div>
    </section>
  );
}
