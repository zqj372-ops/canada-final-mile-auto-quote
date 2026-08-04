import { useEffect, useState, type FormEvent } from "react";
import {
  createFCLRateCard,
  getFCLConfig,
  listFCLRateCards,
  publishFCLConfig,
  publishFCLRateCard,
  updateFCLConfigDraft,
  updateFCLRateCard,
  validateFCLConfig,
  type FCLConfigAdminSnapshot,
  type FCLExchangeRate,
  type FCLFeeLinePayload,
  type FCLQuoteConfig,
  type FCLRateCardPayload,
  type FCLRateCardRecord,
} from "../api/client";
import { FCL_REQUIRED_FIELD_LABELS } from "../components/fclFieldLabels";

type Tab = "rateCards" | "config";

const UNIT_OPTIONS = ["container", "shipment", "piece", "kg", "cbm"] as const;
const CURRENCY_OPTIONS = ["USD", "CAD", "CNY"] as const;
const PRICING_OPTIONS = ["auto", "actual", "manual", "quote_required"] as const;
const DISPLAY_OPTIONS = ["both", "quoteOnly", "hiddenIncluded", "hiddenExcluded", "merged"] as const;
const REQUIRED_FIELD_OPTIONS = Object.entries(FCL_REQUIRED_FIELD_LABELS).map(([value, label]) => ({
  value,
  label,
}));

function emptyFeeLine(): FCLFeeLinePayload {
  return {
    item_name: "",
    unit: "shipment",
    currency: "USD",
    pricing_status: "auto",
    display_mode: "both",
    include_in_quote: true,
  };
}

function emptyCard(): FCLRateCardPayload {
  return {
    pol: "",
    pod: "",
    container_type: "40GP",
    priority: 100,
    enabled: true,
    fee_lines: [emptyFeeLine()],
  };
}

export default function FclSettingsPage() {
  const [tab, setTab] = useState<Tab>("rateCards");
  const [snapshot, setSnapshot] = useState<FCLConfigAdminSnapshot | null>(null);
  const [cards, setCards] = useState<FCLRateCardRecord[]>([]);
  const [configDraft, setConfigDraft] = useState<FCLQuoteConfig | null>(null);
  const [editor, setEditor] = useState<FCLRateCardPayload | null>(null);
  const [editorId, setEditorId] = useState<number | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    void loadAll();
  }, []);

  async function loadAll() {
    setError(null);
    try {
      const [nextSnapshot, nextCards] = await Promise.all([getFCLConfig(), listFCLRateCards()]);
      setSnapshot(nextSnapshot);
      setConfigDraft(nextSnapshot.draft);
      setCards(nextCards);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "FCL 设置加载失败");
    }
  }

  function openNewCard() {
    setEditor(emptyCard());
    setEditorId(null);
    setError(null);
  }

  function openCard(card: FCLRateCardRecord) {
    const { id: _id, status: _status, created_at: _created, updated_at: _updated, ...payload } = card;
    setEditor(payload);
    setEditorId(card.id);
    setError(null);
  }

  async function saveConfig(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    if (!configDraft) {
      return;
    }
    try {
      const payload = normalizeConfig(configDraft);
      const saved = await updateFCLConfigDraft(payload);
      setSnapshot(saved);
      setConfigDraft(saved.draft);
      setNotice("整柜报价配置草稿已保存");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "配置保存失败");
    }
  }

  async function validateDraft() {
    setError(null);
    setNotice(null);
    try {
      const result = await validateFCLConfig();
      setNotice(result.valid ? "草稿校验通过，可以发布。" : `草稿校验失败：${result.errors.join("；")}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "校验失败");
    }
  }

  async function publishDraft() {
    setError(null);
    setNotice(null);
    setIsSaving(true);
    try {
      const result = await publishFCLConfig();
      setNotice(`已发布版本 ${result.published_version}；新报价将使用该版本，历史报价保持原快照。`);
      await loadAll();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "发布失败");
    } finally {
      setIsSaving(false);
    }
  }

  async function saveCard() {
    if (!editor) {
      return;
    }
    setError(null);
    setNotice(null);
    setIsSaving(true);
    try {
      const payload: FCLRateCardPayload = {
        ...editor,
        fee_lines: editor.fee_lines.map((line) => ({
          ...line,
          sales_unit_price: line.sales_unit_price === "" ? null : line.sales_unit_price,
          cost_unit_price: line.cost_unit_price === "" ? null : line.cost_unit_price,
          vendor: line.vendor || null,
          internal_note: line.internal_note || null,
        })),
      };
      if (editorId === null) {
        await createFCLRateCard(payload);
      } else {
        await updateFCLRateCard(editorId, payload);
      }
      setEditor(null);
      setEditorId(null);
      await loadAll();
      setNotice("费率卡草稿已保存；发布后才会参与报价。");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "费率卡保存失败");
    } finally {
      setIsSaving(false);
    }
  }

  async function publishCard(record: FCLRateCardRecord) {
    setError(null);
    setNotice(null);
    try {
      await publishFCLRateCard(record.id);
      await loadAll();
      setNotice(`费率卡 #${record.id} 已发布；已发布卡片不可再编辑，改价请新建草稿。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "费率卡发布失败");
    }
  }

  if (!snapshot) {
    return (
      <div className="mx-auto flex max-w-4xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
        <section className="panel p-6">
          <h1 className="text-2xl font-semibold text-slate-950">整柜报价设置</h1>
          <p className="mt-3 text-sm leading-6 text-slate-600">
            {error ? `加载失败：${error}` : "正在读取配置..."}
          </p>
          <button className="btn-primary mt-5" type="button" onClick={() => void loadAll()}>重新读取</button>
        </section>
      </div>
    );
  }

  return (
    <div className="quote-settings-page mx-auto flex max-w-7xl flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
      <header className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-sm font-medium text-blue-800">FCL Settings</p>
          <h1 className="mt-1 text-2xl font-semibold text-slate-950">整柜报价设置</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
            费率卡、销售规则、汇率与报价模板采用草稿 → 校验 → 发布。未发布草稿不参与报价；成本、供应商和内部备注仅后台可见。
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <button className="btn-secondary" type="button" onClick={() => void validateDraft()}>校验草稿</button>
          <button className="btn-primary" type="button" onClick={() => void publishDraft()} disabled={isSaving}>
            发布配置（当前版本 {snapshot.published_version}）
          </button>
          <a className="btn-secondary" href="../quote">打开前台</a>
        </div>
      </header>

      {error && <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">{error}</div>}
      {notice && <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">{notice}</div>}

      <nav className="sales-tabs" aria-label="整柜报价设置分类">
        <button className={tab === "rateCards" ? "sales-tab-active" : ""} type="button" onClick={() => setTab("rateCards")}>
          费率卡
        </button>
        <button className={tab === "config" ? "sales-tab-active" : ""} type="button" onClick={() => setTab("config")}>
          规则 / 汇率 / 模板
        </button>
      </nav>

      {tab === "rateCards" && (
        <section className="panel p-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-950">费率卡</h2>
              <p className="mt-1 text-sm text-slate-600">
                按 POL / POD / 柜型匹配；船东、渠道、船期与优先级可选。费率行可同时维护销售价、成本价、供应商和内部备注。
              </p>
            </div>
            <button className="btn-primary" type="button" onClick={openNewCard}>新增费率卡</button>
          </div>

          {editor && (
            <RateCardEditor
              editor={editor}
              isSaving={isSaving}
              onCancel={() => { setEditor(null); setEditorId(null); }}
              onChange={setEditor}
              onSave={() => void saveCard()}
            />
          )}

          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead>
                <tr className="bg-slate-50 text-xs text-slate-500">
                  <th className="px-3 py-2">ID</th>
                  <th className="px-3 py-2">线路 / 柜型</th>
                  <th className="px-3 py-2">船东 / 服务</th>
                  <th className="px-3 py-2">有效期</th>
                  <th className="px-3 py-2">优先级</th>
                  <th className="px-3 py-2">状态</th>
                  <th className="px-3 py-2">操作</th>
                </tr>
              </thead>
              <tbody>
                {cards.map((card) => (
                  <tr key={card.id} className="border-t border-slate-100">
                    <td className="px-3 py-2">#{card.id}</td>
                    <td className="px-3 py-2">{card.pol} → {card.pod}<div className="text-xs text-slate-500">{card.container_type}{card.service_scope ? ` / ${card.service_scope}` : ""}</div></td>
                    <td className="px-3 py-2">{card.carrier || "—"}<div className="text-xs text-slate-500">{card.service || "—"}</div></td>
                    <td className="px-3 py-2">{card.effective_from || "—"} ~ {card.effective_to || "—"}</td>
                    <td className="px-3 py-2">{card.priority}</td>
                    <td className="px-3 py-2">
                      <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${card.status === "published" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-700"}`}>
                        {card.status === "published" ? "已发布" : "草稿"}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex gap-2">
                        {card.status === "draft" && <button className="btn-secondary px-2 py-1 text-xs" type="button" onClick={() => openCard(card)}>编辑</button>}
                        {card.status === "draft" && <button className="btn-primary px-2 py-1 text-xs" type="button" onClick={() => void publishCard(card)}>发布</button>}
                        {card.status === "published" && <span className="text-xs text-slate-400">不可编辑（快照）</span>}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {tab === "config" && (
        <section className="panel p-4">
          <h2 className="text-lg font-semibold text-slate-950">规则 / 汇率 / 模板草稿</h2>
          <p className="mt-1 text-sm text-slate-600">
            可视化编辑销售规则、别名、汇率与报价单模板；保存为草稿，校验通过并发布后新报价才会使用。
          </p>
          {configDraft && (
            <form onSubmit={(event) => void saveConfig(event)}>
              <ConfigForm
                config={configDraft}
                onChange={setConfigDraft}
              />
              <div className="mt-3 flex flex-wrap gap-3">
                <button className="btn-primary" type="submit" disabled={isSaving}>保存草稿</button>
                <button className="btn-secondary" type="button" onClick={() => setConfigDraft(snapshot.draft)}>还原为已加载草稿</button>
              </div>
            </form>
          )}
          <div className="mt-4 rounded-md border border-slate-200 bg-slate-50 p-3 text-sm">
            <p className="font-semibold text-slate-700">已发布配置版本：{snapshot.published_version}</p>
            <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap text-xs text-slate-600">
              {snapshot.published ? JSON.stringify(snapshot.published, null, 2) : "尚未发布；发布后历史报价继续使用旧快照。"}
            </pre>
          </div>
        </section>
      )}
    </div>
  );
}

function RateCardEditor({
  editor,
  isSaving,
  onCancel,
  onChange,
  onSave,
}: {
  editor: FCLRateCardPayload;
  isSaving: boolean;
  onCancel: () => void;
  onChange: (value: FCLRateCardPayload) => void;
  onSave: () => void;
}) {
  function update<K extends keyof FCLRateCardPayload>(key: K, value: FCLRateCardPayload[K]) {
    onChange({ ...editor, [key]: value });
  }

  function updateLine(index: number, value: Partial<FCLFeeLinePayload>) {
    onChange({
      ...editor,
      fee_lines: editor.fee_lines.map((line, lineIndex) => lineIndex === index ? { ...line, ...value } : line),
    });
  }

  return (
    <div className="mt-4 rounded-md border border-blue-200 bg-blue-50/40 p-4">
      <h3 className="text-base font-semibold text-slate-950">编辑费率卡</h3>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <label className="block text-sm"><span className="text-xs font-semibold text-slate-600">POL</span><input className="field-input mt-1 w-full" value={editor.pol} onChange={(event) => update("pol", event.target.value)} /></label>
        <label className="block text-sm"><span className="text-xs font-semibold text-slate-600">POD</span><input className="field-input mt-1 w-full" value={editor.pod} onChange={(event) => update("pod", event.target.value)} /></label>
        <label className="block text-sm"><span className="text-xs font-semibold text-slate-600">柜型</span><input className="field-input mt-1 w-full" value={editor.container_type} onChange={(event) => update("container_type", event.target.value)} placeholder="20GP / 40GP / 40HQ" /></label>
        <label className="block text-sm"><span className="text-xs font-semibold text-slate-600">船东（可选）</span><input className="field-input mt-1 w-full" value={editor.carrier ?? ""} onChange={(event) => update("carrier", event.target.value || null)} /></label>
        <label className="block text-sm"><span className="text-xs font-semibold text-slate-600">渠道/服务（可选）</span><input className="field-input mt-1 w-full" value={editor.service ?? ""} onChange={(event) => update("service", event.target.value || null)} /></label>
        <label className="block text-sm"><span className="text-xs font-semibold text-slate-600">服务范围</span>
          <select className="field-input mt-1 w-full" value={editor.service_scope ?? ""} onChange={(event) => update("service_scope", (event.target.value || null) as FCLRateCardPayload["service_scope"])}>
            <option value="">不限</option>
            {["port-to-port", "door-to-port", "port-to-door", "door-to-door"].map((scope) => <option key={scope} value={scope}>{scope}</option>)}
          </select>
        </label>
        <label className="block text-sm"><span className="text-xs font-semibold text-slate-600">生效日期</span><input className="field-input mt-1 w-full" type="date" value={editor.effective_from ?? ""} onChange={(event) => update("effective_from", event.target.value || null)} /></label>
        <label className="block text-sm"><span className="text-xs font-semibold text-slate-600">失效日期</span><input className="field-input mt-1 w-full" type="date" value={editor.effective_to ?? ""} onChange={(event) => update("effective_to", event.target.value || null)} /></label>
        <label className="block text-sm"><span className="text-xs font-semibold text-slate-600">ETD（可选）</span><input className="field-input mt-1 w-full" type="date" value={editor.etd_date ?? ""} onChange={(event) => update("etd_date", event.target.value || null)} /></label>
        <label className="block text-sm"><span className="text-xs font-semibold text-slate-600">船名航次（可选）</span><input className="field-input mt-1 w-full" value={editor.vessel_voyage ?? ""} onChange={(event) => update("vessel_voyage", event.target.value || null)} /></label>
        <label className="block text-sm"><span className="text-xs font-semibold text-slate-600">优先级（越小越优先）</span><input className="field-input mt-1 w-full" type="number" min={1} value={editor.priority ?? 100} onChange={(event) => update("priority", Number(event.target.value) || 100)} /></label>
        <label className="block text-sm"><span className="text-xs font-semibold text-slate-600">来源/备注</span><input className="field-input mt-1 w-full" value={editor.source ?? ""} onChange={(event) => update("source", event.target.value || null)} /></label>
        <label className="flex min-h-10 items-center gap-2 text-sm"><input className="h-4 w-4 rounded border-slate-300 text-teal-700" type="checkbox" checked={Boolean(editor.enabled)} onChange={(event) => update("enabled", event.target.checked)} />启用</label>
      </div>

      <h4 className="mt-5 text-sm font-semibold text-slate-800">费用行（成本/供应商/内部备注仅后台可见）</h4>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[1100px] text-left text-xs">
          <thead>
            <tr className="text-slate-500">
              <th className="py-1 pr-2">项目名</th>
              <th className="py-1 pr-2">说明</th>
              <th className="py-1 pr-2">单位</th>
              <th className="py-1 pr-2">币种</th>
              <th className="py-1 pr-2">销售单价</th>
              <th className="py-1 pr-2">成本单价</th>
              <th className="py-1 pr-2">计价</th>
              <th className="py-1 pr-2">显示模式</th>
              <th className="py-1 pr-2">包含</th>
              <th className="py-1 pr-2">公开备注</th>
              <th className="py-1 pr-2">供应商</th>
              <th className="py-1 pr-2">内部备注</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {editor.fee_lines.map((line, index) => (
              <tr key={index} className="border-t border-slate-200 align-top">
                <td className="py-1 pr-2"><input className="field-input w-28" value={line.item_name} onChange={(event) => updateLine(index, { item_name: event.target.value })} /></td>
                <td className="py-1 pr-2"><input className="field-input w-32" value={line.description ?? ""} onChange={(event) => updateLine(index, { description: event.target.value })} /></td>
                <td className="py-1 pr-2">
                  <select className="field-input w-24" value={line.unit} onChange={(event) => updateLine(index, { unit: event.target.value as FCLFeeLinePayload["unit"] })}>
                    {UNIT_OPTIONS.map((unit) => <option key={unit} value={unit}>{unit}</option>)}
                  </select>
                </td>
                <td className="py-1 pr-2">
                  <select className="field-input w-20" value={line.currency} onChange={(event) => updateLine(index, { currency: event.target.value as FCLFeeLinePayload["currency"] })}>
                    {CURRENCY_OPTIONS.map((currency) => <option key={currency} value={currency}>{currency}</option>)}
                  </select>
                </td>
                <td className="py-1 pr-2"><input className="field-input w-24" type="number" min={0} value={line.sales_unit_price ?? ""} onChange={(event) => updateLine(index, { sales_unit_price: event.target.value })} /></td>
                <td className="py-1 pr-2"><input className="field-input w-24" type="number" min={0} value={line.cost_unit_price ?? ""} onChange={(event) => updateLine(index, { cost_unit_price: event.target.value })} /></td>
                <td className="py-1 pr-2">
                  <select className="field-input w-28" value={line.pricing_status ?? "auto"} onChange={(event) => updateLine(index, { pricing_status: event.target.value as FCLFeeLinePayload["pricing_status"] })}>
                    {PRICING_OPTIONS.map((option) => <option key={option} value={option}>{option}</option>)}
                  </select>
                </td>
                <td className="py-1 pr-2">
                  <select className="field-input w-28" value={line.display_mode ?? "both"} onChange={(event) => updateLine(index, { display_mode: event.target.value as FCLFeeLinePayload["display_mode"] })}>
                    {DISPLAY_OPTIONS.map((option) => <option key={option} value={option}>{option}</option>)}
                  </select>
                </td>
                <td className="py-1 pr-2"><input className="h-4 w-4" type="checkbox" checked={Boolean(line.include_in_quote)} onChange={(event) => updateLine(index, { include_in_quote: event.target.checked })} /></td>
                <td className="py-1 pr-2"><input className="field-input w-32" value={line.public_note ?? ""} onChange={(event) => updateLine(index, { public_note: event.target.value })} /></td>
                <td className="py-1 pr-2"><input className="field-input w-28" value={line.vendor ?? ""} onChange={(event) => updateLine(index, { vendor: event.target.value || null })} /></td>
                <td className="py-1 pr-2"><input className="field-input w-32" value={line.internal_note ?? ""} onChange={(event) => updateLine(index, { internal_note: event.target.value || null })} /></td>
                <td className="py-1 pr-2"><button className="btn-danger px-2 text-xs" type="button" disabled={editor.fee_lines.length <= 1} onClick={() => onChange({ ...editor, fee_lines: editor.fee_lines.filter((_, lineIndex) => lineIndex !== index) })}>删除</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex flex-wrap gap-3">
        <button className="btn-secondary px-3 py-1 text-xs" type="button" onClick={() => onChange({ ...editor, fee_lines: [...editor.fee_lines, emptyFeeLine()] })}>
          + 增加费用行
        </button>
        <button className="btn-primary" type="button" onClick={onSave} disabled={isSaving}>保存费率卡</button>
        <button className="btn-secondary" type="button" onClick={onCancel}>取消</button>
      </div>
    </div>
  );
}

function normalizeConfig(config: FCLQuoteConfig): FCLQuoteConfig {
  function cleanMap(value: Record<string, string>): Record<string, string> {
    return Object.fromEntries(
      Object.entries(value)
        .filter(([key, item]) => key.trim() && String(item).trim())
        .map(([key, item]) => [key.trim(), String(item).trim()]),
    );
  }
  return {
    ...config,
    markup_percent: String(config.markup_percent ?? 0) || "0",
    markup_fixed: String(config.markup_fixed ?? 0) || "0",
    default_quote_valid_days: Number(config.default_quote_valid_days) || 7,
    settlement_currency: config.settlement_currency?.trim() ? config.settlement_currency.trim() : null,
    port_aliases: cleanMap(config.port_aliases),
    container_aliases: cleanMap(config.container_aliases),
    exchange_rates: config.exchange_rates.map((rate) => ({
      ...rate,
      from_currency: String(rate.from_currency).trim().toUpperCase(),
      to_currency: String(rate.to_currency).trim().toUpperCase(),
      rate: rate.rate === "" || rate.rate === null || rate.rate === undefined ? "0" : rate.rate,
      effective_from: rate.effective_from || null,
      effective_to: rate.effective_to || null,
    })),
    terms: config.terms.map((term) => term.trim()).filter(Boolean),
    company_name: config.company_name.trim(),
    company_address: config.company_address.trim(),
    company_phone: config.company_phone.trim(),
    company_email: config.company_email.trim(),
    company_logo: config.company_logo.trim(),
    footer: config.footer.trim(),
    renderer_version: config.renderer_version.trim() || "fcl-html-v1",
  };
}

function ConfigForm({
  config,
  onChange,
}: {
  config: FCLQuoteConfig;
  onChange: (value: FCLQuoteConfig) => void;
}) {
  function update<K extends keyof FCLQuoteConfig>(key: K, value: FCLQuoteConfig[K]) {
    onChange({ ...config, [key]: value });
  }

  function updateRate(index: number, patch: Partial<FCLExchangeRate>) {
    onChange({
      ...config,
      exchange_rates: config.exchange_rates.map((rate, rateIndex) =>
        rateIndex === index ? { ...rate, ...patch } : rate,
      ),
    });
  }

  function toggleRequiredField(value: string) {
    const has = config.required_fields.includes(value);
    update(
      "required_fields",
      has
        ? config.required_fields.filter((item) => item !== value)
        : [...config.required_fields, value],
    );
  }

  return (
    <div className="mt-4 grid gap-5">
      <section className="rounded-md border border-slate-200 p-4">
        <h3 className="text-base font-semibold text-slate-950">销售规则</h3>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <label className="block text-sm">
            <span className="text-xs font-semibold text-slate-600">加价 %（成本价基础上）</span>
            <input className="field-input mt-1 w-full" type="number" min={0} step="0.01" value={String(config.markup_percent ?? 0)} onChange={(event) => update("markup_percent", event.target.value)} />
          </label>
          <label className="block text-sm">
            <span className="text-xs font-semibold text-slate-600">固定加价（每票）</span>
            <input className="field-input mt-1 w-full" type="number" min={0} step="0.01" value={String(config.markup_fixed ?? 0)} onChange={(event) => update("markup_fixed", event.target.value)} />
          </label>
          <label className="block text-sm">
            <span className="text-xs font-semibold text-slate-600">报价默认有效期（天）</span>
            <input className="field-input mt-1 w-full" type="number" min={1} max={365} value={config.default_quote_valid_days} onChange={(event) => update("default_quote_valid_days", Number(event.target.value) || 7)} />
          </label>
          <label className="block text-sm">
            <span className="text-xs font-semibold text-slate-600">结算币种（可选）</span>
            <select className="field-input mt-1 w-full" value={config.settlement_currency ?? ""} onChange={(event) => update("settlement_currency", (event.target.value || null) as FCLQuoteConfig["settlement_currency"])}>
              <option value="">默认按币种分别汇总</option>
              {CURRENCY_OPTIONS.map((currency) => <option key={currency} value={currency}>{currency}</option>)}
            </select>
          </label>
        </div>
        <div className="mt-4">
          <p className="text-sm font-semibold text-slate-700">必填字段（缺失即进入人工复核）</p>
          <div className="mt-2 grid gap-2 sm:grid-cols-3 xl:grid-cols-6">
            {REQUIRED_FIELD_OPTIONS.map((option) => (
              <label key={option.value} className="flex min-h-10 items-center gap-2 text-sm text-slate-700">
                <input
                  className="h-4 w-4 rounded border-slate-300 text-teal-700"
                  type="checkbox"
                  checked={config.required_fields.includes(option.value)}
                  onChange={() => toggleRequiredField(option.value)}
                />
                {option.label}
              </label>
            ))}
          </div>
        </div>
      </section>

      <section className="rounded-md border border-slate-200 p-4">
        <h3 className="text-base font-semibold text-slate-950">港口 / 柜型别名</h3>
        <div className="mt-3 grid gap-4 xl:grid-cols-2">
          <AliasRows
            title="港口别名（别名 → 规范代码）"
            values={config.port_aliases}
            onChange={(value) => update("port_aliases", value)}
          />
          <AliasRows
            title="柜型别名（别名 → 规范柜型）"
            values={config.container_aliases}
            onChange={(value) => update("container_aliases", value)}
          />
        </div>
      </section>

      <section className="rounded-md border border-slate-200 p-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-base font-semibold text-slate-950">汇率快照</h3>
            <p className="mt-1 text-sm text-slate-600">缺失或过期时，涉及该币种的报价会停在人工复核，不生成可发送金额。</p>
          </div>
          <button
            className="btn-secondary px-3 py-1 text-xs"
            type="button"
            onClick={() => update("exchange_rates", [...config.exchange_rates, { from_currency: "USD", to_currency: "CNY", rate: "" }])}
          >
            + 增加汇率
          </button>
        </div>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead>
              <tr className="bg-slate-50 text-xs text-slate-500">
                <th className="px-3 py-2">从币种</th>
                <th className="px-3 py-2">到币种</th>
                <th className="px-3 py-2">汇率</th>
                <th className="px-3 py-2">生效日期</th>
                <th className="px-3 py-2">失效日期</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {config.exchange_rates.map((rate, index) => (
                <tr key={index} className="border-t border-slate-100">
                  <td className="px-3 py-2">
                    <select className="field-input w-24" value={rate.from_currency} onChange={(event) => updateRate(index, { from_currency: event.target.value })}>
                      {CURRENCY_OPTIONS.map((currency) => <option key={currency} value={currency}>{currency}</option>)}
                    </select>
                  </td>
                  <td className="px-3 py-2">
                    <select className="field-input w-24" value={rate.to_currency} onChange={(event) => updateRate(index, { to_currency: event.target.value })}>
                      {CURRENCY_OPTIONS.map((currency) => <option key={currency} value={currency}>{currency}</option>)}
                    </select>
                  </td>
                  <td className="px-3 py-2">
                    <input className="field-input w-24" type="number" min={0} step="0.0001" value={String(rate.rate ?? "")} onChange={(event) => updateRate(index, { rate: event.target.value })} />
                  </td>
                  <td className="px-3 py-2">
                    <input className="field-input w-36" type="date" value={rate.effective_from ?? ""} onChange={(event) => updateRate(index, { effective_from: event.target.value || null })} />
                  </td>
                  <td className="px-3 py-2">
                    <input className="field-input w-36" type="date" value={rate.effective_to ?? ""} onChange={(event) => updateRate(index, { effective_to: event.target.value || null })} />
                  </td>
                  <td className="px-3 py-2">
                    <button
                      className="btn-danger px-2 py-1 text-xs"
                      type="button"
                      onClick={() => update("exchange_rates", config.exchange_rates.filter((_, rateIndex) => rateIndex !== index))}
                    >
                      删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {config.exchange_rates.length === 0 && (
            <p className="mt-2 text-sm text-slate-500">暂无汇率；默认多币种分别汇总。</p>
          )}
        </div>
      </section>

      <section className="rounded-md border border-slate-200 p-4">
        <h3 className="text-base font-semibold text-slate-950">报价单模板</h3>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="text-xs font-semibold text-slate-600">公司名称</span>
            <input className="field-input mt-1 w-full" value={config.company_name} onChange={(event) => update("company_name", event.target.value)} />
          </label>
          <label className="block text-sm">
            <span className="text-xs font-semibold text-slate-600">电话</span>
            <input className="field-input mt-1 w-full" value={config.company_phone} onChange={(event) => update("company_phone", event.target.value)} />
          </label>
          <label className="block text-sm sm:col-span-2">
            <span className="text-xs font-semibold text-slate-600">公司地址</span>
            <input className="field-input mt-1 w-full" value={config.company_address} onChange={(event) => update("company_address", event.target.value)} />
          </label>
          <label className="block text-sm">
            <span className="text-xs font-semibold text-slate-600">邮箱</span>
            <input className="field-input mt-1 w-full" value={config.company_email} onChange={(event) => update("company_email", event.target.value)} />
          </label>
          <label className="block text-sm">
            <span className="text-xs font-semibold text-slate-600">Logo URL（品牌资产确认后接入）</span>
            <input className="field-input mt-1 w-full" value={config.company_logo} onChange={(event) => update("company_logo", event.target.value)} placeholder="https://... 或留空" />
          </label>
        </div>
        <label className="mt-3 block text-sm">
          <span className="text-xs font-semibold text-slate-600">公开条款（每行一条）</span>
          <textarea
            className="field-input mt-1 min-h-28 w-full resize-y"
            value={config.terms.join("\n")}
            onChange={(event) => update("terms", event.target.value.split("\n"))}
          />
        </label>
        <label className="mt-3 block text-sm">
          <span className="text-xs font-semibold text-slate-600">页脚</span>
          <textarea
            className="field-input mt-1 min-h-16 w-full resize-y"
            value={config.footer}
            onChange={(event) => update("footer", event.target.value)}
          />
        </label>
        <label className="mt-3 block text-sm sm:w-72">
          <span className="text-xs font-semibold text-slate-600">渲染器版本（快照契约）</span>
          <input className="field-input mt-1 w-full" value={config.renderer_version} onChange={(event) => update("renderer_version", event.target.value)} />
        </label>
      </section>
    </div>
  );
}

function AliasRows({
  title,
  values,
  onChange,
}: {
  title: string;
  values: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
}) {
  const rows = Object.entries(values);

  function setRow(index: number, key: string, value: string) {
    const [oldKey] = rows[index] ?? ["", ""];
    const next = { ...values };
    if (oldKey !== "") {
      delete next[oldKey];
    }
    const trimmedKey = key.trim();
    next[trimmedKey || ""] = value;
    onChange(next);
  }

  function removeRow(index: number) {
    const [oldKey] = rows[index] ?? [];
    const next = { ...values };
    if (oldKey !== "") {
      delete next[oldKey];
    }
    onChange(next);
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold text-slate-800">{title}</h4>
        <button className="btn-secondary px-3 py-1 text-xs" type="button" onClick={() => onChange({ ...values, "": "" })}>
          + 增加
        </button>
      </div>
      <div className="mt-2 space-y-2">
        {rows.length === 0 && <p className="text-sm text-slate-500">暂无别名</p>}
        {rows.map(([key, value], index) => (
          <div key={index} className="flex gap-2">
            <input
              className="field-input flex-1"
              value={key}
              placeholder="别名，如 SHANGHAI"
              onChange={(event) => setRow(index, event.target.value, value)}
            />
            <input
              className="field-input flex-1"
              value={value}
              placeholder="规范值，如 CNSHA"
              onChange={(event) => setRow(index, key, event.target.value)}
            />
            <button className="btn-danger px-2 text-xs" type="button" onClick={() => removeRow(index)}>删除</button>
          </div>
        ))}
      </div>
    </div>
  );
}
