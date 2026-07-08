import { type ReactNode, useEffect, useMemo, useState } from "react";
import {
  approveHermesLearningCandidate,
  getHermesLearningCandidate,
  listHermesLearningCandidates,
  rejectHermesLearningCandidate,
  updateLearnedQuoteRule,
  type HermesLearningCandidate,
} from "../api/client";
import RiskTags from "../components/RiskTags";

type CandidateFilter = "pending_review" | "approved" | "rejected" | "all";

interface LearningCandidatesPageProps {
  embedded?: boolean;
}

export default function LearningCandidatesPage({
  embedded = false,
}: LearningCandidatesPageProps = {}) {
  const [candidates, setCandidates] = useState<HermesLearningCandidate[]>([]);
  const [selected, setSelected] = useState<HermesLearningCandidate | null>(null);
  const [filter, setFilter] = useState<CandidateFilter>("pending_review");
  const [reviewNote, setReviewNote] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    void loadCandidates(filter);
  }, [filter]);

  const counts = useMemo(() => {
    return candidates.reduce<Record<string, number>>((acc, candidate) => {
      acc[candidate.status] = (acc[candidate.status] ?? 0) + 1;
      return acc;
    }, {});
  }, [candidates]);

  async function loadCandidates(nextFilter = filter) {
    setIsLoading(true);
    setError(null);
    try {
      const response = await listHermesLearningCandidates({
        status: nextFilter,
        limit: 100,
      });
      setCandidates(response);
      if (response.length) {
        const nextSelected = selected
          ? response.find((item) => item.id === selected.id) ?? response[0]
          : response[0];
        setSelected(nextSelected);
        setReviewNote(nextSelected.review_note ?? "");
      } else {
        setSelected(null);
        setReviewNote("");
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Hermes 学习候选加载失败");
    } finally {
      setIsLoading(false);
    }
  }

  async function selectCandidate(candidate: HermesLearningCandidate) {
    setSelected(candidate);
    setReviewNote(candidate.review_note ?? "");
    try {
      setSelected(await getHermesLearningCandidate(candidate.id));
    } catch {
      // 列表信息足够人工判断，详情加载失败时不打断操作。
    }
  }

  async function approveSelected() {
    if (!selected) {
      return;
    }
    setBusyId(selected.id);
    setError(null);
    setNotice(null);
    try {
      const response = await approveHermesLearningCandidate(selected.id, {
        review_note: optionalText(reviewNote),
      });
      setSelected(response.candidate);
      setNotice(`候选 #${selected.id} 已批准，生成学习规则 #${response.learned_rule.id}`);
      await loadCandidates(filter);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "批准 Hermes 候选失败");
    } finally {
      setBusyId(null);
    }
  }

  async function rejectSelected() {
    if (!selected) {
      return;
    }
    setBusyId(selected.id);
    setError(null);
    setNotice(null);
    try {
      const response = await rejectHermesLearningCandidate(selected.id, {
        review_note: optionalText(reviewNote),
      });
      setSelected(response);
      setNotice(`候选 #${selected.id} 已拒绝`);
      await loadCandidates(filter);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "拒绝 Hermes 候选失败");
    } finally {
      setBusyId(null);
    }
  }

  async function disablePromotedRule() {
    if (!selected?.promoted_rule_id) {
      return;
    }
    setBusyId(selected.id);
    setError(null);
    setNotice(null);
    try {
      await updateLearnedQuoteRule(selected.promoted_rule_id, {
        status: "disabled",
        note: optionalText(reviewNote) ?? "Disabled from Hermes candidate page.",
      });
      setNotice(`学习规则 #${selected.promoted_rule_id} 已禁用`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "禁用学习规则失败");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className={embedded ? "flex flex-col gap-5" : "mx-auto flex max-w-[1500px] flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8"}>
      {!embedded && (
      <header className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-sm font-medium text-blue-800">Hermes Learning</p>
          <h1 className="mt-1 text-2xl font-semibold text-slate-950">
            自学习候选审核
          </h1>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            系统报价时先给出建议，人工确认后才会进入这里。批准后才发布为可复用学习规则；Hermes 不直接改价格表，也不直接算价。
          </p>
        </div>
        <button className="btn-secondary" type="button" onClick={() => void loadCandidates()}>
          刷新
        </button>
      </header>
      )}

      <section className="panel p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap gap-2" role="tablist" aria-label="Hermes 候选筛选">
            {(["pending_review", "approved", "rejected", "all"] as CandidateFilter[]).map((item) => (
              <button
                key={item}
                className={filter === item ? "btn-primary" : "btn-secondary bg-white text-slate-700"}
                type="button"
                onClick={() => setFilter(item)}
              >
                {candidateStatusLabel(item)}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap gap-2 text-xs font-semibold text-slate-600">
            <span className="rounded-md bg-amber-50 px-2.5 py-1 text-amber-900">
              待审 {counts.pending_review ?? 0}
            </span>
            <span className="rounded-md bg-emerald-50 px-2.5 py-1 text-emerald-800">
              已批准 {counts.approved ?? 0}
            </span>
            <span className="rounded-md bg-slate-100 px-2.5 py-1 text-slate-700">
              当前 {candidates.length}
            </span>
          </div>
        </div>
      </section>

      {error && (
        <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <div className="rounded-md border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-900" role="status">
          {notice}
        </div>
      )}

      <div className="grid gap-5 xl:grid-cols-[0.95fr_1.05fr]">
        <section className="panel overflow-hidden">
          <div className="border-b border-slate-200 px-4 py-3">
            <h2 className="section-title">候选列表</h2>
            <p className="mt-1 text-sm text-slate-600">
              这里只审核“已有人确认过金额”的建议。报价现场的建议请先在人工任务里确认，单票不确定时直接拒绝或保持待审。
            </p>
          </div>
          {isLoading ? (
            <div className="p-5 text-sm text-slate-600">正在加载 Hermes 候选...</div>
          ) : candidates.length === 0 ? (
            <div className="p-5 text-sm text-slate-600">当前筛选下没有学习候选。</div>
          ) : (
            <div className="max-h-[720px] overflow-auto">
              {candidates.map((candidate) => {
                const isSelected = selected?.id === candidate.id;
                return (
                  <button
                    key={candidate.id}
                    className={`grid w-full gap-2 border-b border-slate-100 px-4 py-3 text-left transition hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-blue-700 ${
                      isSelected ? "bg-blue-50" : "bg-white"
                    }`}
                    type="button"
                    onClick={() => void selectCandidate(candidate)}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-semibold text-slate-950">
                        #{candidate.id} {candidate.postal_prefix || candidate.postal_code || "未知邮编"} / {candidate.city || "未知城市"}
                      </span>
                      <span className={statusBadgeClass(candidate.status)}>
                        {candidateStatusLabel(candidate.status)}
                      </span>
                    </div>
                    <div className="grid gap-2 text-sm text-slate-700 sm:grid-cols-4">
                      <CompactValue label="省份" value={candidate.province || "-"} />
                      <CompactValue label="仓/区" value={`${candidate.origin || "-"} / ${candidate.zone ?? "-"}`} />
                      <CompactValue label="托数" value={`${candidate.billing_pallets} 托`} />
                      <CompactValue label="建议价" value={formatMoney(candidate.resolved_total_price_usd)} />
                    </div>
                    <div className="flex flex-wrap gap-2 text-xs text-slate-500">
                      <span>scope: {candidate.scope}</span>
                      <span>support: {candidate.support_count}</span>
                      <span>confidence: {candidate.confidence}%</span>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </section>

        <section className="panel p-5">
          {selected ? (
            <CandidateDetails
              candidate={selected}
              busy={busyId === selected.id}
              reviewNote={reviewNote}
              onApprove={() => void approveSelected()}
              onDisableRule={() => void disablePromotedRule()}
              onReject={() => void rejectSelected()}
              onReviewNoteChange={setReviewNote}
            />
          ) : (
            <div className="text-sm text-slate-600">选择左侧候选后查看证据和审核操作。</div>
          )}
        </section>
      </div>
    </div>
  );
}

function CandidateDetails({
  busy,
  candidate,
  reviewNote,
  onApprove,
  onDisableRule,
  onReject,
  onReviewNoteChange,
}: {
  busy: boolean;
  candidate: HermesLearningCandidate;
  reviewNote: string;
  onApprove: () => void;
  onDisableRule: () => void;
  onReject: () => void;
  onReviewNoteChange: (value: string) => void;
}) {
  return (
    <div className="grid gap-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-blue-800">候选 #{candidate.id}</p>
          <h2 className="mt-1 text-xl font-semibold text-slate-950">
            {candidate.postal_prefix || candidate.postal_code || "未知邮编"} / {candidate.city || "未知城市"}
          </h2>
        </div>
        <span className={statusBadgeClass(candidate.status)}>{candidateStatusLabel(candidate.status)}</span>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Metric label="建议合计" value={formatMoney(candidate.resolved_total_price_usd)} />
        <Metric label="基础价" value={formatMoney(candidate.resolved_base_price_usd)} />
        <Metric label="计费托数" value={`${candidate.billing_pallets} 托`} />
        <Metric label="证据次数" value={`${candidate.support_count} 次`} />
        <Metric label="始发仓" value={candidate.origin || "-"} />
        <Metric label="Zone" value={candidate.zone === null ? "-" : String(candidate.zone)} />
        <Metric label="置信度" value={`${candidate.confidence}%`} />
        <Metric label="发布规则" value={candidate.promoted_rule_id ? `#${candidate.promoted_rule_id}` : "未发布"} />
      </div>

      <div>
        <p className="field-label">风险标签</p>
        <div className="mt-2">
          <RiskTags tags={candidate.risk_tags} />
        </div>
      </div>

      <label>
        <span className="field-label">审核备注</span>
        <textarea
          className="field-input min-h-24"
          value={reviewNote}
          onChange={(event) => onReviewNoteChange(event.target.value)}
          placeholder="写明为什么批准或拒绝，例如：已和供应商确认 S7K/Saskatoon/3托按 Calgary Zone 5 处理。"
        />
      </label>

      <div className="grid gap-3 sm:grid-cols-3">
        <button
          className="btn-primary"
          type="button"
          disabled={busy || candidate.status === "approved"}
          onClick={onApprove}
        >
          {busy ? "处理中..." : "批准并发布"}
        </button>
        <button
          className="btn-secondary bg-white text-slate-700"
          type="button"
          disabled={busy || candidate.status === "rejected"}
          onClick={onReject}
        >
          拒绝候选
        </button>
        <button
          className="btn-secondary bg-white text-slate-700"
          type="button"
          disabled={busy || !candidate.promoted_rule_id}
          onClick={onDisableRule}
        >
          禁用已发布规则
        </button>
      </div>

      <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm leading-6 text-amber-950">
        Hermes 的顺序是先给建议，再由人工审核确认。批准后的学习规则只会在 Zone/价格表未命中时复用，不会覆盖正常 Zone Matrix 报价。
      </div>

      <LearningProposalCard candidate={candidate} />
      <LearningEvidenceCard candidate={candidate} />
      <RawDebugDetails proposal={candidate.proposal_json} evidence={candidate.evidence_json} />
    </div>
  );
}

function CompactValue({ label, value }: { label: string; value: string }) {
  return (
    <span>
      <span className="text-slate-500">{label}</span>
      <span className="ml-1 font-semibold text-slate-950">{value}</span>
    </span>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
      <p className="text-xs font-semibold text-slate-500">{label}</p>
      <p className="mt-1 break-words font-semibold text-slate-950 tabular-nums">{value}</p>
    </div>
  );
}

function LearningProposalCard({ candidate }: { candidate: HermesLearningCandidate }) {
  const proposal = asRecord(candidate.proposal_json);
  const action = readText(proposal, "action");
  const scope = readText(proposal, "scope") || candidate.scope;
  const totalPrice = readText(proposal, "total_price_usd") || candidate.resolved_total_price_usd;
  const basePrice = readText(proposal, "base_price_usd") || candidate.resolved_base_price_usd;

  return (
    <section className="rounded-lg border border-blue-100 bg-blue-50/70 p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-blue-800">学习建议</p>
          <h3 className="mt-1 text-lg font-semibold text-slate-950">
            {candidateActionLabel(action || candidate.candidate_type)}
          </h3>
          <p className="mt-1 text-sm leading-6 text-slate-600">
            批准后只在正常 Zone / 价格表未命中时复用，不能覆盖现有价格矩阵。
          </p>
        </div>
        <span className="inline-flex w-fit rounded-full border border-blue-200 bg-white px-3 py-1 text-xs font-semibold text-blue-800">
          {scopeLabel(scope)}
        </span>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <InfoTile label="适用邮编" value={candidate.postal_code || candidate.postal_prefix || "-"} />
        <InfoTile label="适用城市" value={candidate.city || "-"} />
        <InfoTile label="省份" value={candidate.province || "-"} />
        <InfoTile label="始发仓" value={candidate.origin || "待人工指定"} />
        <InfoTile label="Zone" value={candidate.zone === null ? "待人工指定" : String(candidate.zone)} />
        <InfoTile label="计费托数" value={`${candidate.billing_pallets} 托`} />
        <InfoTile label="建议合计" value={formatMoney(totalPrice)} strong />
        <InfoTile label="基础价" value={formatMoney(basePrice)} />
        <InfoTile label="证据次数" value={`${candidate.support_count} 次`} />
      </div>
    </section>
  );
}

function LearningEvidenceCard({ candidate }: { candidate: HermesLearningCandidate }) {
  const evidence = asRecord(candidate.evidence_json);
  const request = asRecord(evidence.request_json);
  const result = asRecord(evidence.result_json);
  const resolvedNote = readText(evidence, "resolved_note");
  const matchedRule = readText(result, "matched_rule");
  const sourceType = readText(result, "source_type");

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-slate-600">人工确认依据</p>
          <h3 className="mt-1 text-lg font-semibold text-slate-950">
            这条候选来自人工任务 #{candidate.source_task_id ?? "-"}
          </h3>
        </div>
        <span className="inline-flex w-fit rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-700">
          quote {candidate.quote_id ? shortId(candidate.quote_id) : "-"}
        </span>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <EvidenceGroup title="原始询价摘要">
          <InfoRow label="目的地地址" value={readText(request, "address_line") || "-"} />
          <InfoRow label="邮编 / 城市 / 省份" value={formatLocation(request, candidate)} />
          <InfoRow label="货量" value={formatCargo(request)} />
          <InfoRow label="包装 / 地址类型" value={formatServiceContext(request)} />
        </EvidenceGroup>

        <EvidenceGroup title="系统判断与人工确认">
          <InfoRow label="未命中原因" value={matchedRule || "未记录"} highlight />
          <InfoRow label="系统来源" value={sourceTypeLabel(sourceType)} />
          <InfoRow label="人工确认金额" value={formatMoney(candidate.resolved_total_price_usd)} highlight />
          <InfoRow label="人工备注" value={resolvedNote || "未填写"} />
        </EvidenceGroup>
      </div>
    </section>
  );
}

function EvidenceGroup({ children, title }: { children: ReactNode; title: string }) {
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
      <h4 className="text-sm font-semibold text-slate-900">{title}</h4>
      <div className="mt-3 grid gap-2">{children}</div>
    </div>
  );
}

function InfoTile({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="rounded-md border border-white/70 bg-white/80 px-3 py-2 shadow-sm">
      <p className="text-xs font-semibold text-slate-500">{label}</p>
      <p className={`mt-1 break-words tabular-nums ${strong ? "text-lg font-bold text-blue-900" : "font-semibold text-slate-950"}`}>
        {value}
      </p>
    </div>
  );
}

function InfoRow({ label, value, highlight = false }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="grid gap-1 rounded-md bg-white px-3 py-2 sm:grid-cols-[7rem_1fr]">
      <span className="text-xs font-semibold text-slate-500">{label}</span>
      <span className={`break-words text-sm leading-6 ${highlight ? "font-semibold text-slate-950" : "text-slate-700"}`}>
        {value}
      </span>
    </div>
  );
}

function RawDebugDetails({ evidence, proposal }: { evidence: unknown; proposal: unknown }) {
  return (
    <details className="rounded-md border border-slate-200 bg-white">
      <summary className="cursor-pointer px-3 py-2 text-sm font-semibold text-slate-700">
        高级调试：原始数据
      </summary>
      <div className="grid gap-3 border-t border-slate-200 p-3 lg:grid-cols-2">
        <pre className="max-h-72 overflow-auto rounded-md bg-slate-950 p-3 text-xs leading-5 text-slate-100">
          {JSON.stringify(proposal, null, 2)}
        </pre>
        <pre className="max-h-72 overflow-auto rounded-md bg-slate-950 p-3 text-xs leading-5 text-slate-100">
          {JSON.stringify(evidence, null, 2)}
        </pre>
      </div>
    </details>
  );
}

function asRecord(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return {};
}

function readText(source: Record<string, unknown>, key: string): string | null {
  const value = source[key];
  if (value === null || value === undefined || value === "") {
    return null;
  }
  return String(value);
}

function scopeLabel(value: string | null): string {
  const labels: Record<string, string> = {
    postal_code: "精确邮编规则",
    postal_prefix: "FSA 邮编前缀规则",
    postal_prefix_city: "FSA + 城市规则",
    city_province: "城市 + 省份规则",
  };
  return value ? labels[value] ?? value : "待确认范围";
}

function candidateActionLabel(value: string): string {
  const labels: Record<string, string> = {
    approve_learned_exception_price: "发布一条人工确认例外价",
    learned_exception_price: "发布一条人工确认例外价",
    postal_zone_override: "补一条邮编分区修正规则",
    zone_price_matrix_gap: "补齐 Zone 价格矩阵缺口",
  };
  return labels[value] ?? "发布一条待审核学习规则";
}

function sourceTypeLabel(value: string | null): string {
  const labels: Record<string, string> = {
    manual_required: "系统未命中，进入人工复核",
    zone_matrix: "Zone 价格矩阵命中",
    learned_manual_quote: "已发布学习规则命中",
    hermes_agent_correction: "Hermes Agent 已纠错",
  };
  return value ? labels[value] ?? value : "未记录";
}

function formatLocation(request: Record<string, unknown>, candidate: HermesLearningCandidate): string {
  const postal = readText(request, "postal_code") || candidate.postal_code || candidate.postal_prefix || "-";
  const city = readText(request, "city") || candidate.city || "-";
  const province = readText(request, "province") || candidate.province || "-";
  return `${postal} / ${city} / ${province}`;
}

function formatCargo(request: Record<string, unknown>): string {
  const pieces = readText(request, "piece_count") || "-";
  const cbm = readText(request, "cbm") || "-";
  const weight = readText(request, "weight_kg") || "-";
  const longestSide = readText(request, "longest_side_cm");
  const parts = [`${pieces} 件`, `${cbm} CBM`, `${weight} KG`];
  if (longestSide) {
    parts.push(`最长边 ${longestSide} cm`);
  }
  return parts.join(" / ");
}

function formatServiceContext(request: Record<string, unknown>): string {
  const packaging = readText(request, "packaging_type") || "-";
  const addressType = addressTypeLabel(readText(request, "address_type"));
  const extras = [
    boolLabel("尾板", request.requires_liftgate),
    boolLabel("手叉车", request.requires_pallet_jack),
    boolLabel("预约", request.requires_appointment),
  ];
  return `${packaging} / ${addressType} / ${extras.join(" / ")}`;
}

function addressTypeLabel(value: string | null): string {
  const labels: Record<string, string> = {
    commercial: "商业地址",
    residential: "住宅地址",
    private: "私人地址",
    rural_residential: "乡村住宅",
  };
  return value ? labels[value] ?? value : "地址类型待确认";
}

function boolLabel(label: string, value: unknown): string {
  return `${label}${value === true ? "是" : "否"}`;
}

function shortId(value: string): string {
  return value.length > 8 ? `${value.slice(0, 8)}...` : value;
}

function candidateStatusLabel(value: string): string {
  const labels: Record<string, string> = {
    pending_review: "待审核",
    approved: "已批准",
    rejected: "已拒绝",
    all: "全部",
  };
  return labels[value] ?? value;
}

function statusBadgeClass(status: string): string {
  if (status === "approved") {
    return "inline-flex rounded-md bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-800";
  }
  if (status === "rejected") {
    return "inline-flex rounded-md bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-700";
  }
  return "inline-flex rounded-md bg-amber-50 px-2 py-1 text-xs font-semibold text-amber-900";
}

function formatMoney(value: string | number | null): string {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? `USD ${numberValue.toFixed(2)}` : String(value);
}

function optionalText(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}
