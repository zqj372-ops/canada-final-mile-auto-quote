import { useState } from "react";
import {
  calculateFCLAutoQuote,
  type FCLAutoQuoteResponse,
  type FCLCargoItem,
  type FCLContainerInput,
  type FCLQuoteDraft,
  type FCLServiceScope,
  type FCLServiceStage,
  type FCLSpecialAttribute,
} from "../api/client";
import {
  FCL_ADDRESS_TYPES,
  FCL_BN_RM_STATUSES,
  FCL_BROKER_OPTIONS,
  FCL_CARM_STATUSES,
  FCL_CUSTOMER_TYPES,
  FCL_DEADLINE_STRICTNESS,
  FCL_EXPORT_DECLARATIONS,
  FCL_IMPORTER_EXISTS,
  FCL_PRIORITY_GOALS,
  FCL_SERVICE_STAGES,
  FCL_SPECIAL_ATTRIBUTES,
  FCL_TAX_INCLUDED,
  FCL_TRADE_TERMS,
  FCL_WOOD_PACKAGING,
  FCL_YES_NO_UNKNOWN,
  optionList,
} from "./fclFieldLabels";
import QuoteCopyButton from "./QuoteCopyButton";
import { printFclQuoteHtml } from "./fclQuoteHtml";

type Stage = "form" | "done";

const SERVICE_SCOPES: Array<{ value: FCLServiceScope; label: string }> = [
  { value: "port-to-port", label: "港到港 Port-to-Port" },
  { value: "door-to-port", label: "门到港 Door-to-Port" },
  { value: "port-to-door", label: "港到门 Port-to-Door" },
  { value: "door-to-door", label: "门到门 Door-to-Door" },
];

const SPECIAL_ATTRIBUTE_OPTIONS = optionList(FCL_SPECIAL_ATTRIBUTES) as Array<{
  value: FCLSpecialAttribute;
  label: string;
}>;
const SERVICE_STAGE_OPTIONS = optionList(FCL_SERVICE_STAGES) as Array<{
  value: FCLServiceStage;
  label: string;
}>;

function emptyDraft(): FCLQuoteDraft {
  return {
    containers: [{ container_type: "40GP", quantity: 1 }],
    cargo_items: [],
    special_attributes: [],
    service_stages: [],
    confidence: 0,
    extraction_notes: [],
  };
}

export default function FclQuotePanel({
  onRecordsRefresh,
}: {
  onRecordsRefresh: () => Promise<boolean>;
}) {
  const [stage, setStage] = useState<Stage>("form");
  const [draft, setDraft] = useState<FCLQuoteDraft>(emptyDraft);
  const [parsed, setParsed] = useState<FCLAutoQuoteResponse | null>(null);
  const [result, setResult] = useState<FCLAutoQuoteResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const quote = result?.quote_result ?? null;
  const manual = Boolean(result?.manual_review_required || quote?.manual_review_required);

  function updateDraft<K extends keyof FCLQuoteDraft>(key: K, value: FCLQuoteDraft[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
    setResult(null);
    setStage((currentStage) => (currentStage === "done" ? "form" : currentStage));
  }

  function updateContainer(index: number, value: Partial<FCLContainerInput>) {
    setDraft((current) => ({
      ...current,
      containers: current.containers.map((item, itemIndex) =>
        itemIndex === index ? { ...item, ...value } : item,
      ),
    }));
  }

  function updateCargoItem(index: number, value: Partial<FCLCargoItem>) {
    setDraft((current) => ({
      ...current,
      cargo_items: current.cargo_items.map((item, itemIndex) =>
        itemIndex === index ? { ...item, ...value } : item,
      ),
    }));
  }

  function toggleSpecialAttribute(value: FCLSpecialAttribute) {
    setDraft((current) => ({
      ...current,
      special_attributes: current.special_attributes.includes(value)
        ? current.special_attributes.filter((item) => item !== value)
        : [...current.special_attributes, value],
    }));
  }

  function toggleServiceStage(value: FCLServiceStage) {
    setDraft((current) => ({
      ...current,
      service_stages: (current.service_stages ?? []).includes(value)
        ? (current.service_stages ?? []).filter((item) => item !== value)
        : [...(current.service_stages ?? []), value],
    }));
  }

  async function precheckCargo() {
    setError(null);
    setNotice(null);
    setIsLoading(true);
    try {
      const response = await calculateFCLAutoQuote(
        {
          confirmed_fields: draft,
          auto_submit_when_complete: false,
        },
        "quote",
      );
      setParsed(response);
      setResult(null);
      setNotice("货物重算预检完成：无冲突即可提交报价。");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "货物重算预检失败");
    } finally {
      setIsLoading(false);
    }
  }

  async function submitQuote() {
    setError(null);
    setNotice(null);
    setIsLoading(true);
    try {
      const response = await calculateFCLAutoQuote(
        {
          confirmed_fields: draft,
          auto_submit_when_complete: true,
        },
        "quote",
      );
      setResult(response);
      setStage("done");
      const refreshed = await onRecordsRefresh();
      if (!refreshed) {
        setNotice("报价已完成，但历史记录列表暂未刷新。");
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "AI 整柜报价失败");
    } finally {
      setIsLoading(false);
    }
  }

  function reset() {
    setDraft(emptyDraft());
    setParsed(null);
    setResult(null);
    setError(null);
    setNotice(null);
    setStage("form");
  }

  return (
    <div className="grid gap-3 fcl-form">
      <nav className="sales-stage-tabs" aria-label="AI 整柜报价步骤">
        <button
          className={stage === "form" ? "sales-stage-tab-active" : ""}
          type="button"
          onClick={() => setStage("form")}
        >
          <span>01</span> 表单填写
        </button>
        <button
          className={stage === "done" ? "sales-stage-tab-active" : ""}
          type="button"
          onClick={() => setStage("done")}
          disabled={!result}
        >
          <span>02</span> 报价结果
        </button>
      </nav>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900" role="status">
          {notice}
        </div>
      )}

      {stage === "form" && (
        <>
        <StructuredFieldForm
          draft={draft}
          parsed={parsed}
          onDraftChange={updateDraft}
          onContainerChange={updateContainer}
          onCargoItemChange={updateCargoItem}
          onToggleSpecial={toggleSpecialAttribute}
          onToggleServiceStage={toggleServiceStage}
        />

        <section className="panel p-3">
          <div className="flex flex-wrap gap-3">
            <button className="btn-secondary" type="button" onClick={() => void precheckCargo()} disabled={isLoading}>
              {isLoading ? "计算中…" : "预检货物重算"}
            </button>
            <button className="btn-primary" type="button" onClick={() => void submitQuote()} disabled={isLoading}>
              {isLoading ? "报价中…" : "提交整柜报价"}
            </button>
            <button className="btn-secondary" type="button" onClick={reset} disabled={isLoading}>
              重置表单
            </button>
          </div>
        </section>
        </>
      )}

      {stage === "done" && result && (
        <FclResultPanel
          response={result}
          manual={manual}
          onNewInquiry={reset}
        />
      )}
    </div>
  );
}

function StructuredFieldForm({
  draft,
  parsed,
  onCargoItemChange,
  onContainerChange,
  onDraftChange,
  onToggleServiceStage,
  onToggleSpecial,
}: {
  draft: FCLQuoteDraft;
  parsed: FCLAutoQuoteResponse | null;
  onCargoItemChange: (index: number, value: Partial<FCLCargoItem>) => void;
  onContainerChange: (index: number, value: Partial<FCLContainerInput>) => void;
  onDraftChange: <K extends keyof FCLQuoteDraft>(key: K, value: FCLQuoteDraft[K]) => void;
  onToggleServiceStage: (value: FCLServiceStage) => void;
  onToggleSpecial: (value: FCLSpecialAttribute) => void;
}) {
  const dangerousOrBattery = draft.special_attributes.some(
    (value) => value === "dangerous_goods" || value === "battery",
  );
  const woodSelected = draft.special_attributes.includes("wood");
  const doorDelivery = draft.service_scope === "port-to-door" || draft.service_scope === "door-to-door";
  const selfImport = draft.importer_exists === "yes";
  const noImporter = draft.importer_exists === "no" || draft.importer_exists === "unknown";

  return (
    <div className="grid gap-3 fcl-form">
      <section className="panel p-3">
        <h2 className="text-sm font-semibold text-slate-950">联系与主体</h2>
        <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          <LabeledInput required label="客户 / 公司名称" value={draft.customer_name ?? ""} onChange={(value) => onDraftChange("customer_name", value || null)} />
          <LabeledInput required label="联系人及联系方式" placeholder="姓名 / 邮箱 / 电话" value={draft.contact ?? ""} onChange={(value) => onDraftChange("contact", value || null)} />
          <SelectField required label="客户类型 / 业务角色" value={draft.customer_type ?? ""} options={optionList(FCL_CUSTOMER_TYPES)} onChange={(value) => onDraftChange("customer_type", (value || null) as FCLQuoteDraft["customer_type"])} />
        </div>
      </section>

      <section className="panel p-3">
        <h2 className="text-sm font-semibold text-slate-950">路线与服务</h2>
        <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          <LabeledInput required label="起运城市 / 港口 POL" value={draft.pol ?? ""} onChange={(value) => onDraftChange("pol", value || null)} />
          <LabeledInput required label="目的城市 / 港口 POD" value={draft.pod ?? ""} onChange={(value) => onDraftChange("pod", value || null)} />
          <LabeledInput label="目的邮编（到门必填）" value={draft.destination_postal_code ?? ""} onChange={(value) => onDraftChange("destination_postal_code", value || null)} />
          <LabeledInput label="完整收货地址（到门必填）" placeholder="例如：123 Example St." value={draft.destination_address ?? ""} onChange={(value) => onDraftChange("destination_address", value || null)} />
          <SelectField required label="交付范围" value={draft.service_scope ?? ""} options={SERVICE_SCOPES} onChange={(value) => onDraftChange("service_scope", (value || null) as FCLServiceScope | null)} />
          <LabeledInput label="船东（可选）" value={draft.carrier ?? ""} onChange={(value) => onDraftChange("carrier", value || null)} />
          <LabeledInput label="渠道 / 服务偏好（可选）" value={draft.service_preference ?? ""} onChange={(value) => onDraftChange("service_preference", value || null)} />
        </div>
        <div className="mt-4">
          <CheckboxGrid
            label="希望的服务环节（可多选）"
            options={SERVICE_STAGE_OPTIONS}
            values={draft.service_stages ?? []}
            onToggle={(value) => onToggleServiceStage(value as FCLServiceStage)}
          />
        </div>
      </section>

      <section className="panel p-3">
        <h2 className="text-sm font-semibold text-slate-950">货物与柜型</h2>
        <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          <LabeledInput required label="中文 / 英文品名" placeholder="例如：木制家具 / wooden furniture" value={draft.cargo_name ?? ""} onChange={(value) => onDraftChange("cargo_name", value || null)} />
          <LabeledInput label="材质 / 用途 / 品牌 / 型号" value={draft.cargo_details ?? ""} onChange={(value) => onDraftChange("cargo_details", value || null)} />
          <LabeledInput required label="件数" type="number" min={1} value={draft.declared_piece_count === null || draft.declared_piece_count === undefined ? "" : String(draft.declared_piece_count)} onChange={(value) => onDraftChange("declared_piece_count", value === "" ? null : Number(value))} />
          <LabeledInput required label="总毛重 KG" type="number" min={0} value={draft.declared_total_weight_kg === null || draft.declared_total_weight_kg === undefined ? "" : String(draft.declared_total_weight_kg)} onChange={(value) => onDraftChange("declared_total_weight_kg", value === "" ? null : value)} />
          <LabeledInput required label="总体积 CBM" type="number" min={0} value={draft.declared_total_volume_cbm === null || draft.declared_total_volume_cbm === undefined ? "" : String(draft.declared_total_volume_cbm)} onChange={(value) => onDraftChange("declared_total_volume_cbm", value === "" ? null : value)} />
          <SelectField label="可否叠放" value={draft.stackable === null || draft.stackable === undefined ? "" : draft.stackable ? "yes" : "no"} options={[{ value: "yes", label: "可以叠放" }, { value: "no", label: "不可叠放" }]} onChange={(value) => onDraftChange("stackable", value === "" ? null : value === "yes")} />
        </div>

        <div className="mt-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-800">柜型柜量</h3>
            <button
              className="btn-secondary px-3 py-1 text-xs"
              type="button"
              onClick={() => onDraftChange("containers", [...draft.containers, { container_type: "40GP", quantity: 1 }])}
            >
              + 增加柜型
            </button>
          </div>
          <div className="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {draft.containers.map((container, index) => (
              <div key={`${index}-${container.container_type}`} className="flex gap-2 rounded-md border border-slate-200 p-2">
                <input
                  className="field-input flex-1"
                  value={container.container_type}
                  onChange={(event) => onContainerChange(index, { container_type: event.target.value })}
                  placeholder="20GP / 40GP / 40HQ"
                />
                <input
                  className="field-input w-20"
                  type="number"
                  min={1}
                  value={container.quantity}
                  onChange={(event) => onContainerChange(index, { quantity: Math.max(1, Number(event.target.value) || 1) })}
                />
                <button
                  className="btn-danger px-2 text-xs"
                  type="button"
                  disabled={draft.containers.length <= 1}
                  onClick={() => onDraftChange("containers", draft.containers.filter((_, itemIndex) => itemIndex !== index))}
                >
                  删除
                </button>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-800">货物分项（尺寸 / 重量，可空）</h3>
            <button
              className="btn-secondary px-3 py-1 text-xs"
              type="button"
              onClick={() => onDraftChange("cargo_items", [...draft.cargo_items, { quantity: 1, dimension_unit: "cm", weight_unit: "kg" }])}
            >
              + 增加分项
            </button>
          </div>
          <div className="mt-2 overflow-x-auto">
            {draft.cargo_items.length ? (
              <table className="w-full min-w-[680px] text-left text-sm">
                <thead>
                  <tr className="text-xs text-slate-500">
                    <th className="py-1 pr-2">货名</th>
                    <th className="py-1 pr-2">数量</th>
                    <th className="py-1 pr-2">长</th>
                    <th className="py-1 pr-2">宽</th>
                    <th className="py-1 pr-2">高</th>
                    <th className="py-1 pr-2">尺寸单位</th>
                    <th className="py-1 pr-2">单件重</th>
                    <th className="py-1 pr-2">重量单位</th>
                    <th className="py-1 pr-2">分项总重 KG</th>
                    <th className="py-1 pr-2">分项总体积 CBM</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {draft.cargo_items.map((item, index) => (
                    <tr key={index} className="border-t border-slate-100">
                      <td className="py-1 pr-2"><input className="field-input" value={item.name ?? ""} onChange={(event) => onCargoItemChange(index, { name: event.target.value || null })} /></td>
                      <td className="py-1 pr-2"><input className="field-input w-20" type="number" min={1} value={item.quantity} onChange={(event) => onCargoItemChange(index, { quantity: Math.max(1, Number(event.target.value) || 1) })} /></td>
                      <td className="py-1 pr-2"><input className="field-input w-24" type="number" value={String(item.length ?? "")} onChange={(event) => onCargoItemChange(index, { length: event.target.value === "" ? null : event.target.value })} /></td>
                      <td className="py-1 pr-2"><input className="field-input w-24" type="number" value={String(item.width ?? "")} onChange={(event) => onCargoItemChange(index, { width: event.target.value === "" ? null : event.target.value })} /></td>
                      <td className="py-1 pr-2"><input className="field-input w-24" type="number" value={String(item.height ?? "")} onChange={(event) => onCargoItemChange(index, { height: event.target.value === "" ? null : event.target.value })} /></td>
                      <td className="py-1 pr-2">
                        <select className="field-input" value={item.dimension_unit ?? "cm"} onChange={(event) => onCargoItemChange(index, { dimension_unit: event.target.value as FCLCargoItem["dimension_unit"] })}>
                          {["mm", "cm", "m", "in"].map((unit) => <option key={unit} value={unit}>{unit}</option>)}
                        </select>
                      </td>
                      <td className="py-1 pr-2"><input className="field-input w-24" type="number" value={item.weight ?? ""} onChange={(event) => onCargoItemChange(index, { weight: event.target.value === "" ? null : event.target.value })} /></td>
                      <td className="py-1 pr-2">
                        <select className="field-input" value={item.weight_unit ?? "kg"} onChange={(event) => onCargoItemChange(index, { weight_unit: event.target.value as FCLCargoItem["weight_unit"] })}>
                          {["g", "kg", "lb"].map((unit) => <option key={unit} value={unit}>{unit}</option>)}
                        </select>
                      </td>
                      <td className="py-1 pr-2"><input className="field-input w-24" type="number" value={item.total_weight_kg ?? ""} onChange={(event) => onCargoItemChange(index, { total_weight_kg: event.target.value === "" ? null : event.target.value })} /></td>
                      <td className="py-1 pr-2"><input className="field-input w-28" type="number" value={item.total_volume_cbm ?? ""} onChange={(event) => onCargoItemChange(index, { total_volume_cbm: event.target.value === "" ? null : event.target.value })} /></td>
                      <td className="py-1 pr-2"><button className="btn-danger px-2 text-xs" type="button" onClick={() => onDraftChange("cargo_items", draft.cargo_items.filter((_, itemIndex) => itemIndex !== index))}>删除</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="text-sm text-slate-500">暂无分项；可填写上方声明总量，或增加分项让系统按 L×W×H×数量重算并校验。</p>
            )}
          </div>
        </div>
      </section>

      <details className="panel p-3">
        <summary className="cursor-pointer select-none text-sm font-semibold text-slate-950">货值与申报</summary>
        <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          <LabeledInput label="货值（进口 / 包税时必填）" type="number" min={0} value={draft.cargo_value === null || draft.cargo_value === undefined ? "" : String(draft.cargo_value)} onChange={(value) => onDraftChange("cargo_value", value === "" ? null : value)} />
          <SelectField label="货值币种" value={draft.cargo_value_currency ?? ""} options={[{ value: "USD", label: "USD" }, { value: "CAD", label: "CAD" }, { value: "CNY", label: "CNY" }]} onChange={(value) => onDraftChange("cargo_value_currency", value || null)} />
          <LabeledInput label="HS 编码（清关前必填 / 确认）" placeholder="6-10 位" value={draft.hs_code ?? ""} onChange={(value) => onDraftChange("hs_code", value || null)} />
          <LabeledInput label="原产地（进口必填）" value={draft.origin_country ?? ""} onChange={(value) => onDraftChange("origin_country", value || null)} />
        </div>
      </details>

      <section className="panel p-3">
        <h2 className="text-sm font-semibold text-slate-950">特殊属性</h2>
        <CheckboxGrid
          required
          label="特殊属性（必选至少一项）"
          options={SPECIAL_ATTRIBUTE_OPTIONS}
          values={draft.special_attributes}
          onToggle={(value) => onToggleSpecial(value as FCLSpecialAttribute)}
        />
        {dangerousOrBattery && (
          <TextAreaField
            required
            className="mt-3"
            label="SDS / UN 编号 / 电池资料（危险品、带电必填）"
            rows={2}
            value={draft.sds_un_info ?? ""}
            onChange={(value) => onDraftChange("sds_un_info", value || null)}
          />
        )}
        {woodSelected && (
          <div className="mt-3">
            <SelectField
              required
              label="木质包装 / IPPC 情况（选“待确认”将进入人工复核）"
              value={draft.wood_packaging ?? ""}
              options={optionList(FCL_WOOD_PACKAGING)}
              onChange={(value) => onDraftChange("wood_packaging", value || null)}
            />
          </div>
        )}
      </section>

      <section className="panel p-3">
        <h2 className="text-sm font-semibold text-slate-950">时间</h2>
        <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          <LabeledInput required label="预计出货 / 备货日期" type="date" value={draft.ready_date ?? ""} onChange={(value) => onDraftChange("ready_date", value || null)} />
          <LabeledInput label="目标 ETD" type="date" value={draft.target_etd ?? ""} onChange={(value) => onDraftChange("target_etd", value || null)} />
          <LabeledInput label="期望到门日期（建议必填）" type="date" value={draft.expected_delivery_date ?? ""} onChange={(value) => onDraftChange("expected_delivery_date", value || null)} />
          <SelectField label="时限性质（硬性时限需人工确认）" value={draft.deadline_strictness ?? ""} options={optionList(FCL_DEADLINE_STRICTNESS)} onChange={(value) => onDraftChange("deadline_strictness", value || null)} />
          <LabeledInput label="可接受中转 / 待拼天数" type="number" min={0} value={draft.acceptable_transit_days === null || draft.acceptable_transit_days === undefined ? "" : String(draft.acceptable_transit_days)} onChange={(value) => onDraftChange("acceptable_transit_days", value === "" ? null : Number(value))} />
        </div>
      </section>

      <details className="panel p-3">
        <summary className="cursor-pointer select-none text-sm font-semibold text-slate-950">贸易与进口（含必填：是否有加拿大进口商）</summary>
        <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          <SelectField label="贸易条款" value={draft.trade_terms ?? ""} options={optionList(FCL_TRADE_TERMS)} onChange={(value) => onDraftChange("trade_terms", value || null)} />
          <SelectField label="中国出口主体及报关能力" value={draft.export_declaration ?? ""} options={optionList(FCL_EXPORT_DECLARATIONS)} onChange={(value) => onDraftChange("export_declaration", value || null)} />
          <SelectField required label="是否有加拿大进口商" value={draft.importer_exists ?? ""} options={optionList(FCL_IMPORTER_EXISTS)} onChange={(value) => onDraftChange("importer_exists", value || null)} />
          {selfImport && (
            <>
              <LabeledInput label="加拿大进口商法定名称" value={draft.importer_legal_name ?? ""} onChange={(value) => onDraftChange("importer_legal_name", value || null)} />
              <SelectField label="BN / RM 账号状态" value={draft.bn_rm_status ?? ""} options={optionList(FCL_BN_RM_STATUSES)} onChange={(value) => onDraftChange("bn_rm_status", value || null)} />
              <SelectField label="CARM 门户及报关授权状态" value={draft.carm_status ?? ""} options={optionList(FCL_CARM_STATUSES)} onChange={(value) => onDraftChange("carm_status", value || null)} />
              <SelectField label="是否已有报关行" value={draft.has_broker ?? ""} options={optionList(FCL_BROKER_OPTIONS)} onChange={(value) => onDraftChange("has_broker", value || null)} />
            </>
          )}
          {noImporter && (
            <SelectField required label="是否希望包税（无进口商时必填）" value={draft.tax_included ?? ""} options={optionList(FCL_TAX_INCLUDED)} onChange={(value) => onDraftChange("tax_included", value || null)} />
          )}
        </div>
      </details>

      <details className="panel p-3">
        <summary className="cursor-pointer select-none text-sm font-semibold text-slate-950">服务与派送（到门时含必填）</summary>
        <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {!noImporter && (
            <SelectField label="是否希望包税" value={draft.tax_included ?? ""} options={optionList(FCL_TAX_INCLUDED)} onChange={(value) => onDraftChange("tax_included", value || null)} />
          )}
          <SelectField label="优先目标" value={draft.priority_goal ?? ""} options={optionList(FCL_PRIORITY_GOALS)} onChange={(value) => onDraftChange("priority_goal", value || null)} />
          <SelectField label="地址类型（到门必填）" value={draft.address_type ?? ""} options={optionList(FCL_ADDRESS_TYPES)} onChange={(value) => onDraftChange("address_type", value || null)} />
          <SelectField label="尾板需求" value={draft.tail_lift ?? ""} options={optionList(FCL_YES_NO_UNKNOWN)} onChange={(value) => onDraftChange("tail_lift", value || null)} />
          <SelectField label="叉车 / 装卸平台" value={draft.forklift ?? ""} options={optionList(FCL_YES_NO_UNKNOWN)} onChange={(value) => onDraftChange("forklift", value || null)} />
          <LabeledInput label="预约需求与时间窗" placeholder="例如：工作日 9-16 点" value={draft.appointment_window ?? ""} onChange={(value) => onDraftChange("appointment_window", value || null)} />
          <LabeledInput label="平台仓代码 / 标签 / 预约资料" placeholder="例如：YYZ4" value={draft.platform_warehouse ?? ""} onChange={(value) => onDraftChange("platform_warehouse", value || null)} />
        </div>
      </details>

      <section className="panel p-3">
        <h2 className="text-sm font-semibold text-slate-950">确认与备注</h2>
        <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          <label className="flex min-h-8 items-center gap-2 text-sm text-slate-700">
            <input
              className="h-4 w-4 rounded border-slate-300 text-teal-700"
              type="checkbox"
              checked={draft.declaration_acknowledged === true}
              onChange={(event) => onDraftChange("declaration_acknowledged", event.target.checked || null)}
            />
            已确认如实申报
          </label>
          <LabeledInput label="备注 / 补充说明" placeholder="可选" value={draft.notes ?? ""} onChange={(value) => onDraftChange("notes", value || null)} />
        </div>
      </section>

      {parsed && (
        <section className="panel p-3">
          <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm">
            <p className="font-semibold text-slate-700">确定性货物重算（服务端 Decimal）</p>
            <p className="mt-1 text-slate-600">
              件数 {parsed.cargo_recalculation.piece_count ?? "—"} / 总毛重 {parsed.cargo_recalculation.total_weight_kg ?? "—"} KG / 总体积 {parsed.cargo_recalculation.total_volume_cbm ?? "—"} CBM
            </p>
            {parsed.cargo_recalculation.conflicts.length > 0 && (
              <p className="mt-1 text-amber-700">冲突：{parsed.cargo_recalculation.conflicts.join("、")}</p>
            )}
            {parsed.missing_fields.length > 0 && (
              <p className="mt-1 text-amber-700">缺失必填：{parsed.missing_fields.join("、")}（提交后将进入人工复核）</p>
            )}
          </div>
        </section>
      )}
    </div>
  );
}

function LabeledInput({
  label,
  value,
  type = "text",
  required = false,
  placeholder,
  min,
  onChange,
}: {
  label: string;
  value: string;
  type?: string;
  required?: boolean;
  placeholder?: string;
  min?: number;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block text-sm">
      <span className="text-xs font-semibold text-slate-600">{label}{required ? " *" : ""}</span>
      <input className="field-input mt-1 w-full" type={type} min={min} placeholder={placeholder} value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function SelectField({
  label,
  value,
  options,
  required = false,
  onChange,
}: {
  label: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  required?: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block text-sm">
      <span className="text-xs font-semibold text-slate-600">{label}{required ? " *" : ""}</span>
      <select className="field-input mt-1 w-full" value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">未选择</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
    </label>
  );
}

function TextAreaField({
  label,
  value,
  rows = 3,
  required = false,
  className = "",
  onChange,
}: {
  label: string;
  value: string;
  rows?: number;
  required?: boolean;
  className?: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className={`block text-sm ${className}`}>
      <span className="text-xs font-semibold text-slate-600">{label}{required ? " *" : ""}</span>
      <textarea className="field-input mt-1 w-full" rows={rows} value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function CheckboxGrid({
  label,
  options,
  values,
  required = false,
  onToggle,
}: {
  label: string;
  options: Array<{ value: string; label: string }>;
  values: string[];
  required?: boolean;
  onToggle: (value: string) => void;
}) {
  return (
    <div>
      <p className="text-xs font-semibold text-slate-600">{label}{required ? " *" : ""}</p>
      <div className="mt-1 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {options.map((option) => (
          <label key={option.value} className="flex min-h-8 items-center gap-2 text-sm text-slate-700">
            <input
              className="h-4 w-4 rounded border-slate-300 text-teal-700"
              type="checkbox"
              checked={values.includes(option.value)}
              onChange={() => onToggle(option.value)}
            />
            {option.label}
          </label>
        ))}
      </div>
    </div>
  );
}

function FclResultPanel({
  manual,
  onNewInquiry,
  response,
}: {
  manual: boolean;
  onNewInquiry: () => void;
  response: FCLAutoQuoteResponse;
}) {
  const quote = response.quote_result;
  return (
    <section className="panel p-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase text-teal-700">AI 整柜报价结果</p>
          <h2 className="mt-1 text-xl font-semibold text-slate-950">
            {manual ? "报价待人工复核" : "报价已完成"}
          </h2>
          <p className="mt-1 text-sm text-slate-500">{quote?.quote_id ?? "未生成报价编号"}</p>
        </div>
        <button className="btn-secondary" type="button" onClick={onNewInquiry}>新询价</button>
      </div>

      {manual && (
        <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm leading-6 text-amber-800">
          未生成可直接发送客户的确定金额。原因：{(quote?.manual_reasons ?? []).join("、") || "需要人工确认"}。
        </div>
      )}

      {quote && (
        <div className="mt-3 grid gap-3 xl:grid-cols-2">
          <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
            <h3 className="text-sm font-semibold text-slate-700">费用明细（仅公开项）</h3>
            <div className="mt-2 overflow-x-auto">
              <table className="w-full min-w-[480px] text-left text-sm">
                <thead>
                  <tr className="text-xs text-slate-500">
                    <th className="py-1 pr-2">项目</th>
                    <th className="py-1 pr-2">数量</th>
                    <th className="py-1 pr-2">单价</th>
                    <th className="py-1 pr-2">金额</th>
                  </tr>
                </thead>
                <tbody>
                  {quote.fee_items.filter((item) => ["both", "quoteOnly", "merged"].includes(item.display_mode)).map((item) => (
                    <tr key={item.item_name} className="border-t border-slate-200">
                      <td className="py-2 pr-2">{item.item_name}</td>
                      <td className="py-2 pr-2">{item.quantity} {item.unit}</td>
                      <td className="py-2 pr-2">{item.unit_price === null || item.unit_price === "" ? "—" : `${item.currency} ${item.unit_price}`}</td>
                      <td className="py-2 pr-2">{item.amount === null || item.amount === "" ? "按实际/人工确认" : `${item.currency} ${item.amount}`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-3 space-y-1 text-sm">
              {Object.entries(quote.totals_by_currency).map(([currency, amount]) => (
                <div key={currency} className="flex justify-between"><span>{currency} 合计</span><strong>{currency} {amount}</strong></div>
              ))}
              {quote.settlement_currency && quote.converted_total !== null && quote.converted_total !== undefined && (
                <div className="flex justify-between border-t border-slate-300 pt-1 text-base font-bold">
                  <span>折算合计</span><span>{quote.settlement_currency} {quote.converted_total}</span>
                </div>
              )}
            </div>
          </div>

          <div className="grid content-start gap-3">
            <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
              <h3 className="text-sm font-semibold text-slate-700">客户回复</h3>
              <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words text-sm leading-6 text-slate-700">
                {response.customer_reply || "人工复核单不生成可直接发送的报价话术。"}
              </pre>
              <div className="mt-3">
                <QuoteCopyButton text={response.customer_reply ?? ""} disabled={manual || !response.customer_reply} />
              </div>
            </div>
            <div className="flex flex-wrap gap-3">
              <button
                className="btn-primary"
                type="button"
                disabled={manual}
                onClick={() => quote && printFclQuoteHtml(quote)}
              >
                打印 A4 报价单 / 另存为 PDF
              </button>
              <button className="btn-secondary" type="button" onClick={onNewInquiry}>再报一票</button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
