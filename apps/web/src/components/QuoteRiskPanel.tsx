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
      className={`panel p-4 ${
        manualRequired ? "border-amber-300 shadow-sm" : ""
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <h2 className="section-title text-lg">{title}</h2>
        {manualRequired && (
          <span className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700">
            不能直接发客户
          </span>
        )}
      </div>
      <div className="mt-4 grid gap-2">
        {risks.length ? (
          risks.map((risk) => (
            <div key={risk} className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm leading-6 text-amber-700">
              {risk}
            </div>
          ))
        ) : (
          <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-500">
            暂无额外风险提示
          </div>
        )}
      </div>
    </section>
  );
}
