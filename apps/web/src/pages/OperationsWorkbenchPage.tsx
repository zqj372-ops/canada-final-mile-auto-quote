import { lazy, Suspense, useEffect, useMemo, useState } from "react";

const AuditPage = lazy(() => import("./AuditPage"));
const BatchDiagnosticReportsPage = lazy(() => import("./BatchDiagnosticReportsPage"));
const HermesDiagnosticsPage = lazy(() => import("./HermesDiagnosticsPage"));
const LearningCandidatesPage = lazy(() => import("./LearningCandidatesPage"));
const ManualTasksPage = lazy(() => import("./ManualTasksPage"));

type OperationsTab = "manual" | "diagnostics" | "batch" | "hermes" | "audit";

interface OperationsWorkbenchPageProps {
  initialTab?: OperationsTab;
}

const tabs: Array<{
  id: OperationsTab;
  label: string;
  summary: string;
  metric: string;
}> = [
  {
    id: "manual",
    label: "人工任务",
    summary: "先看系统建议，再人工确认金额和处理结论",
    metric: "复核",
  },
  {
    id: "diagnostics",
    label: "诊断队列",
    summary: "每票报价的结构化诊断包，供 Hermes Agent 只读分析",
    metric: "建议",
  },
  {
    id: "batch",
    label: "批量报告",
    summary: "查看随机邮编命中测试的汇总、Top 缺口和整理建议",
    metric: "批量",
  },
  {
    id: "hermes",
    label: "Hermes 学习",
    summary: "审核人工确认后的学习候选，决定是否发布复用",
    metric: "学习",
  },
  {
    id: "audit",
    label: "审计查询",
    summary: "查看报价列表、价格来源和每票为什么这样算",
    metric: "追溯",
  },
];

export default function OperationsWorkbenchPage({
  initialTab = "manual",
}: OperationsWorkbenchPageProps) {
  const [activeTab, setActiveTab] = useState<OperationsTab>(initialTab);

  useEffect(() => {
    setActiveTab(initialTab);
  }, [initialTab]);

  const activeTabMeta = useMemo(
    () => tabs.find((tab) => tab.id === activeTab) ?? tabs[0],
    [activeTab],
  );

  return (
    <div className="mx-auto flex max-w-[1600px] flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
      <header className="rounded-lg border border-slate-200 bg-white/90 p-4 shadow-sm">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <p className="text-sm font-semibold text-teal-700">Operations Workbench</p>
            <h1 className="mt-1 text-2xl font-semibold tracking-normal text-slate-950">
              后台处理工作台
            </h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
              把人工复核、Hermes 诊断建议、学习候选和报价审计合并在一个页面。系统先落诊断包，Hermes 只给建议，人工确认后才进入学习并可被后续报价复用。
            </p>
          </div>

          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                type="button"
                className={`rounded-md border px-3 py-3 text-left transition ${
                  activeTab === tab.id
                    ? "border-teal-400 bg-teal-50 text-teal-950 shadow-sm"
                    : "border-slate-200 bg-white text-slate-700 hover:border-teal-200 hover:bg-slate-50"
                }`}
                onClick={() => setActiveTab(tab.id)}
              >
                <span className="text-xs font-semibold text-slate-500">{tab.metric}</span>
                <strong className="mt-1 block text-base">{tab.label}</strong>
                <span className="mt-1 block text-xs leading-5 text-slate-500">{tab.summary}</span>
              </button>
            ))}
          </div>
        </div>
      </header>

      <section className="rounded-lg border border-slate-200 bg-white/80 p-3 shadow-sm">
        <div className="mb-3 flex flex-col gap-2 border-b border-slate-200 pb-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-950">{activeTabMeta.label}</h2>
            <p className="text-sm leading-6 text-slate-600">{activeTabMeta.summary}</p>
          </div>
          <div className="inline-flex w-fit rounded-md bg-slate-100 p-1">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                type="button"
                className={`min-h-9 rounded px-3 text-sm font-semibold transition ${
                  activeTab === tab.id
                    ? "bg-white text-teal-800 shadow-sm"
                    : "text-slate-600 hover:text-slate-950"
                }`}
                onClick={() => setActiveTab(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        <Suspense fallback={<WorkbenchLoading />}>
          {activeTab === "manual" && (
            <ManualTasksPage embedded onOpenHermes={() => setActiveTab("diagnostics")} />
          )}
          {activeTab === "diagnostics" && <HermesDiagnosticsPage embedded />}
          {activeTab === "batch" && <BatchDiagnosticReportsPage embedded />}
          {activeTab === "hermes" && <LearningCandidatesPage embedded />}
          {activeTab === "audit" && <AuditPage embedded />}
        </Suspense>
      </section>
    </div>
  );
}

function WorkbenchLoading() {
  return <div className="px-4 py-12 text-center text-sm font-medium text-slate-500">加载工作台数据…</div>;
}
