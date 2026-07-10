import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  getZonePricingConfig,
  listZonePriceMatrix,
  updateZonePricingConfig,
  upsertZonePriceMatrix,
  type MoneyValue,
  type ZonePriceMatrixListResponse,
  type ZonePriceMatrixPayload,
  type ZonePriceMatrixRecord,
  type ZonePricingConfig,
} from "../api/client";

type MatrixFilters = {
  origin: string;
  zone: number | "";
  billing_pallets: number | "";
};

type NewPriceDraft = {
  origin: string;
  zone: string;
  billing_pallets: string;
  base_price_usd: string;
  source: string;
};

type PricingSettingsSection = "fees" | "new-price" | "matrix";

const pricingFields: Array<{
  key: keyof ZonePricingConfig;
  label: string;
  suffix: string;
  step: number;
  hint: string;
}> = [
  { key: "fuel_percent", label: "燃油附加比例", suffix: "%", step: 0.01, hint: "按基础派送费百分比计算。" },
  { key: "residential_fee_usd", label: "住宅附加费", suffix: "USD", step: 0.01, hint: "地址类型为住宅时收取。" },
  { key: "liftgate_fee_usd", label: "尾板费", suffix: "USD", step: 0.01, hint: "需要 liftgate 时收取。" },
  { key: "pallet_jack_fee_usd", label: "手叉车费", suffix: "USD", step: 0.01, hint: "需要 pallet jack 时收取。" },
  { key: "appointment_fee_usd", label: "预约费", suffix: "USD", step: 0.01, hint: "需要 appointment 时收取。" },
  { key: "detention_half_hour_fee_usd", label: "等待半小时费", suffix: "USD", step: 0.01, hint: "超过免费等待后按半小时向上取整。" },
  { key: "detention_free_minutes", label: "免费等待分钟", suffix: "分钟", step: 1, hint: "等待时间超过该分钟数后开始计费。" },
];

export default function PricingSettingsPage() {
  const [pricingConfig, setPricingConfig] = useState<ZonePricingConfig | null>(null);
  const [matrix, setMatrix] = useState<ZonePriceMatrixListResponse | null>(null);
  const [filters, setFilters] = useState<MatrixFilters>({ origin: "", zone: "", billing_pallets: "" });
  const [draftCells, setDraftCells] = useState<Record<string, string>>({});
  const [newPrice, setNewPrice] = useState<NewPriceDraft>({
    origin: "toronto",
    zone: "",
    billing_pallets: "",
    base_price_usd: "",
    source: "admin-ui",
  });
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isSavingPricing, setIsSavingPricing] = useState(false);
  const [isSavingMatrix, setIsSavingMatrix] = useState(false);
  const [activeSection, setActiveSection] = useState<PricingSettingsSection>("fees");

  useEffect(() => {
    void loadAll();
  }, []);

  const matrixRows = useMemo(() => buildMatrixRows(matrix?.records ?? []), [matrix?.records]);
  const changedCells = useMemo(() => {
    if (!matrix) {
      return [];
    }
    const recordsByKey = new Map(matrix.records.map((record) => [cellKey(record.origin, record.zone, record.billing_pallets), record]));
    return Object.entries(draftCells)
      .map(([key, value]) => ({ key, value, record: recordsByKey.get(key), parts: parseCellKey(key) }))
      .filter((entry) => entry.parts && entry.value.trim() && entry.value.trim() !== formatInputValue(entry.record?.base_price_usd));
  }, [draftCells, matrix]);

  async function loadAll() {
    setIsLoading(true);
    setError(null);
    setNotice(null);
    try {
      const [nextPricing, nextMatrix] = await Promise.all([
        getZonePricingConfig(),
        listZonePriceMatrix({ limit: 5000 }),
      ]);
      setPricingConfig(nextPricing);
      setMatrix(nextMatrix);
      setDraftCells(buildDraftCells(nextMatrix.records));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "价格配置加载失败");
    } finally {
      setIsLoading(false);
    }
  }

  async function loadMatrix() {
    setIsLoading(true);
    setError(null);
    setNotice(null);
    try {
      const nextMatrix = await listZonePriceMatrix({ ...filters, limit: 5000 });
      setMatrix(nextMatrix);
      setDraftCells(buildDraftCells(nextMatrix.records));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "分区价格表加载失败");
    } finally {
      setIsLoading(false);
    }
  }

  async function savePricing(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!pricingConfig) {
      return;
    }
    setError(null);
    setNotice(null);
    setIsSavingPricing(true);
    try {
      const saved = await updateZonePricingConfig(normalizePricingPayload(pricingConfig));
      setPricingConfig(saved);
      setNotice("燃油和附加费配置已保存，下一票报价会直接使用新配置。");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "燃油和附加费配置保存失败");
    } finally {
      setIsSavingPricing(false);
    }
  }

  async function saveMatrixChanges() {
    if (!changedCells.length) {
      setNotice("没有需要保存的分区价格修改。");
      return;
    }
    setError(null);
    setNotice(null);
    setIsSavingMatrix(true);
    try {
      await Promise.all(
        changedCells.map((entry) => {
          const parts = entry.parts;
          if (!parts) {
            throw new Error("价格单元格标识无效");
          }
          return upsertZonePriceMatrix({
            origin: parts.origin,
            zone: parts.zone,
            billing_pallets: parts.billing_pallets,
            base_price_usd: entry.value,
            source: entry.record?.source || "admin-ui",
            last_updated: todayString(),
          });
        }),
      );
      const savedCount = changedCells.length;
      await loadMatrix();
      setNotice(`已保存 ${savedCount} 个价格单元格。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "分区价格保存失败");
    } finally {
      setIsSavingMatrix(false);
    }
  }

  async function addOrUpdatePrice(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const payload = buildNewPricePayload(newPrice);
    if (!payload) {
      setError("请填写始发仓、Zone、托数和基础派送费。");
      return;
    }
    setError(null);
    setNotice(null);
    setIsSavingMatrix(true);
    try {
      await upsertZonePriceMatrix(payload);
      setNewPrice((current) => ({ ...current, zone: "", billing_pallets: "", base_price_usd: "" }));
      await loadMatrix();
      setNotice("已新增或覆盖一个分区价格。");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "新增分区价格失败");
    } finally {
      setIsSavingMatrix(false);
    }
  }

  function updatePricingField(key: keyof ZonePricingConfig, value: string) {
    setPricingConfig((current) => {
      if (!current) {
        return current;
      }
      if (key === "detention_free_minutes") {
        return { ...current, [key]: Math.max(0, Number.parseInt(value || "0", 10) || 0) };
      }
      return { ...current, [key]: value };
    });
  }

  return (
    <div
      className="pricing-settings-page mx-auto flex max-w-[1600px] flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8"
      data-active-section={activeSection}
    >
      <header className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-sm font-semibold text-blue-800">Pricing Settings</p>
          <h1 className="mt-1 text-2xl font-semibold text-slate-950">价格配置</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
            后台维护 Zone 基础派送费、燃油比例和附加费。前台只读取报价结果，不在浏览器计算价格。
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <button className="btn-secondary" type="button" onClick={loadAll} disabled={isLoading}>
            {isLoading ? "读取中..." : "重新读取"}
          </button>
          <button className="btn-primary" type="button" onClick={saveMatrixChanges} disabled={isSavingMatrix || changedCells.length === 0}>
            {isSavingMatrix ? "保存中..." : `保存价格修改${changedCells.length ? ` (${changedCells.length})` : ""}`}
          </button>
        </div>
      </header>

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

      <nav className="settings-section-tabs" aria-label="价格配置分区">
        {([
          ["fees", "附加费规则"],
          ["new-price", "新增价格"],
          ["matrix", "价格矩阵"],
        ] as Array<[PricingSettingsSection, string]>).map(([section, label]) => (
          <button
            key={section}
            className={activeSection === section ? "settings-section-tab-active" : ""}
            type="button"
            onClick={() => setActiveSection(section)}
          >
            {label}
          </button>
        ))}
      </nav>

      <section className="pricing-settings-forms">
        <form className="panel pricing-settings-section pricing-settings-fees grid gap-4 p-5" onSubmit={savePricing}>
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="section-title">燃油和附加费</h2>
              <p className="mt-1 text-sm leading-6 text-slate-600">
                这些值由 Quote Engine 服务端读取，保存后下一票报价立即生效。
              </p>
            </div>
            <button className="btn-primary min-h-10 px-3 py-1" type="submit" disabled={!pricingConfig || isSavingPricing}>
              {isSavingPricing ? "保存中..." : "保存费用配置"}
            </button>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
            {pricingFields.map((field) => (
              <label key={field.key} className="rounded-md border border-slate-200 bg-slate-50 p-3">
                <span className="field-label">{field.label}</span>
                <div className="mt-2 grid grid-cols-[1fr_auto] overflow-hidden rounded-md border border-slate-300 bg-white">
                  <input
                    className="min-h-10 min-w-0 px-3 py-2 text-sm font-semibold text-slate-950 outline-none"
                    type="number"
                    inputMode="decimal"
                    min={0}
                    step={field.step}
                    value={formatInputValue(pricingConfig?.[field.key])}
                    onChange={(event) => updatePricingField(field.key, event.target.value)}
                  />
                  <span className="grid min-w-16 place-items-center border-l border-slate-200 bg-slate-100 px-2 text-xs font-semibold text-slate-600">
                    {field.suffix}
                  </span>
                </div>
                <span className="field-hint">{field.hint}</span>
              </label>
            ))}
          </div>
        </form>

        <form className="panel pricing-settings-section pricing-settings-new-price grid gap-4 p-5" onSubmit={addOrUpdatePrice}>
          <div>
            <h2 className="section-title">新增 / 覆盖单条 Zone 价格</h2>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              用于临时补价或修正单个 `origin + zone + 托数` 的基础派送费。
            </p>
          </div>
          <div className="grid gap-3 md:grid-cols-5">
            <TextInput label="始发仓" value={newPrice.origin} onChange={(value) => setNewPrice((current) => ({ ...current, origin: value }))} />
            <TextInput label="Zone" type="number" value={newPrice.zone} onChange={(value) => setNewPrice((current) => ({ ...current, zone: value }))} />
            <TextInput label="托数" type="number" value={newPrice.billing_pallets} onChange={(value) => setNewPrice((current) => ({ ...current, billing_pallets: value }))} />
            <TextInput label="基础派送费 USD" type="number" step="0.01" value={newPrice.base_price_usd} onChange={(value) => setNewPrice((current) => ({ ...current, base_price_usd: value }))} />
            <TextInput label="来源备注" value={newPrice.source} onChange={(value) => setNewPrice((current) => ({ ...current, source: value }))} />
          </div>
          <div className="flex justify-end">
            <button className="btn-primary" type="submit" disabled={isSavingMatrix}>
              新增或覆盖
            </button>
          </div>
        </form>
      </section>

      <section className="panel pricing-settings-section pricing-settings-matrix grid gap-4 p-5">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <h2 className="section-title">Zone 基础派送费矩阵</h2>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              行是始发仓 + Zone，列是计费托数。单元格金额来自 `zone_price_matrix.base_price_usd`。
            </p>
          </div>
          <div className="grid gap-2 sm:grid-cols-4">
            <FilterSelect label="始发仓" value={filters.origin} options={matrix?.origins ?? []} onChange={(value) => setFilters((current) => ({ ...current, origin: value }))} />
            <FilterSelect label="Zone" value={String(filters.zone)} options={(matrix?.zones ?? []).map(String)} onChange={(value) => setFilters((current) => ({ ...current, zone: value ? Number(value) : "" }))} />
            <FilterSelect label="托数" value={String(filters.billing_pallets)} options={(matrix?.billing_pallets ?? []).map(String)} onChange={(value) => setFilters((current) => ({ ...current, billing_pallets: value ? Number(value) : "" }))} />
            <button className="btn-secondary self-end" type="button" onClick={loadMatrix} disabled={isLoading}>
              筛选
            </button>
          </div>
        </div>

        <div className="grid gap-3 rounded-md border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700 sm:grid-cols-4">
          <Metric label="当前显示" value={`${matrix?.records.length ?? 0} 条`} />
          <Metric label="总匹配" value={`${matrix?.total ?? 0} 条`} />
          <Metric label="始发仓" value={(matrix?.origins ?? []).join(" / ") || "-"} />
          <Metric label="托数列" value={(matrix?.billing_pallets ?? []).join(" / ") || "-"} />
        </div>

        <div className="overflow-x-auto rounded-md border border-slate-200">
          <table className="min-w-[900px] w-full border-collapse text-left text-sm">
            <thead className="bg-slate-100 text-xs uppercase text-slate-600">
              <tr>
                <th className="sticky left-0 z-10 border-b border-r border-slate-200 bg-slate-100 px-3 py-2 font-semibold">始发仓</th>
                <th className="sticky left-[118px] z-10 border-b border-r border-slate-200 bg-slate-100 px-3 py-2 font-semibold">Zone</th>
                {(matrix?.billing_pallets ?? []).map((pallet) => (
                  <th key={pallet} className="border-b border-slate-200 px-2 py-2 text-center font-semibold">
                    {pallet} 托
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 bg-white">
              {matrixRows.length ? (
                matrixRows.map((row) => (
                  <tr key={`${row.origin}-${row.zone}`} className="hover:bg-blue-50/40">
                    <td className="sticky left-0 z-10 w-[118px] border-r border-slate-200 bg-inherit px-3 py-2 font-semibold text-slate-950">
                      {row.origin}
                    </td>
                    <td className="sticky left-[118px] z-10 w-[72px] border-r border-slate-200 bg-inherit px-3 py-2 font-semibold text-slate-950">
                      {row.zone}
                    </td>
                    {(matrix?.billing_pallets ?? []).map((pallet) => {
                      const key = cellKey(row.origin, row.zone, pallet);
                      const record = row.records.get(pallet);
                      return (
                        <td key={key} className="min-w-28 border-l border-slate-100 px-1.5 py-1.5">
                          <input
                            className={`w-full rounded-md border px-2 py-1.5 text-right font-mono text-sm outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-600/20 ${
                              draftCells[key] !== undefined && draftCells[key] !== formatInputValue(record?.base_price_usd)
                                ? "border-amber-400 bg-amber-50 text-amber-950"
                                : "border-slate-200 bg-white text-slate-950"
                            }`}
                            value={draftCells[key] ?? ""}
                            placeholder="-"
                            inputMode="decimal"
                            onChange={(event) => setDraftCells((current) => ({ ...current, [key]: event.target.value }))}
                            aria-label={`${row.origin} Zone ${row.zone} ${pallet} 托基础派送费`}
                          />
                        </td>
                      );
                    })}
                  </tr>
                ))
              ) : (
                <tr>
                  <td className="px-3 py-8 text-center text-slate-500" colSpan={(matrix?.billing_pallets.length ?? 0) + 2}>
                    暂无匹配的分区价格。
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-slate-600">
            黄色单元格表示未保存修改。保存后 Quote Engine 会从数据库读取新基础价。
          </p>
          <button className="btn-primary" type="button" onClick={saveMatrixChanges} disabled={isSavingMatrix || changedCells.length === 0}>
            {isSavingMatrix ? "保存中..." : `保存价格修改${changedCells.length ? ` (${changedCells.length})` : ""}`}
          </button>
        </div>
      </section>
    </div>
  );
}

function TextInput({
  label,
  value,
  onChange,
  type = "text",
  step,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  step?: string;
}) {
  return (
    <label>
      <span className="field-label">{label}</span>
      <input
        className="field-input"
        type={type}
        step={step}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
}) {
  return (
    <label>
      <span className="field-label text-xs">{label}</span>
      <select className="field-input min-h-10 py-1 text-sm" value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">全部</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="metric-label">{label}</dt>
      <dd className="metric-value break-words">{value}</dd>
    </div>
  );
}

function buildMatrixRows(records: ZonePriceMatrixRecord[]): Array<{
  origin: string;
  zone: number;
  records: Map<number, ZonePriceMatrixRecord>;
}> {
  const rows = new Map<string, { origin: string; zone: number; records: Map<number, ZonePriceMatrixRecord> }>();
  records.forEach((record) => {
    const key = `${record.origin}|${record.zone}`;
    const row = rows.get(key) ?? { origin: record.origin, zone: record.zone, records: new Map() };
    row.records.set(record.billing_pallets, record);
    rows.set(key, row);
  });
  return Array.from(rows.values()).sort((left, right) => {
    if (left.origin !== right.origin) {
      return left.origin.localeCompare(right.origin);
    }
    return left.zone - right.zone;
  });
}

function buildDraftCells(records: ZonePriceMatrixRecord[]): Record<string, string> {
  return Object.fromEntries(
    records.map((record) => [
      cellKey(record.origin, record.zone, record.billing_pallets),
      formatInputValue(record.base_price_usd),
    ]),
  );
}

function cellKey(origin: string, zone: number, billingPallets: number): string {
  return `${origin}|${zone}|${billingPallets}`;
}

function parseCellKey(key: string): { origin: string; zone: number; billing_pallets: number } | null {
  const [origin, zoneValue, palletValue] = key.split("|");
  const zone = Number(zoneValue);
  const billingPallets = Number(palletValue);
  if (!origin || !Number.isFinite(zone) || !Number.isFinite(billingPallets)) {
    return null;
  }
  return { origin, zone, billing_pallets: billingPallets };
}

function formatInputValue(value: MoneyValue | undefined): string {
  if (value === null || value === undefined) {
    return "";
  }
  return String(value);
}

function normalizePricingPayload(config: ZonePricingConfig): ZonePricingConfig {
  return {
    fuel_percent: formatInputValue(config.fuel_percent) || "0",
    residential_fee_usd: formatInputValue(config.residential_fee_usd) || "0",
    liftgate_fee_usd: formatInputValue(config.liftgate_fee_usd) || "0",
    pallet_jack_fee_usd: formatInputValue(config.pallet_jack_fee_usd) || "0",
    appointment_fee_usd: formatInputValue(config.appointment_fee_usd) || "0",
    detention_half_hour_fee_usd: formatInputValue(config.detention_half_hour_fee_usd) || "0",
    detention_free_minutes: Math.max(0, Number(config.detention_free_minutes) || 0),
  };
}

function buildNewPricePayload(draft: NewPriceDraft): ZonePriceMatrixPayload | null {
  const zone = Number(draft.zone);
  const billingPallets = Number(draft.billing_pallets);
  const price = Number(draft.base_price_usd);
  if (!draft.origin.trim() || !Number.isFinite(zone) || !Number.isFinite(billingPallets) || !Number.isFinite(price)) {
    return null;
  }
  return {
    origin: draft.origin.trim(),
    zone,
    billing_pallets: billingPallets,
    base_price_usd: draft.base_price_usd,
    source: draft.source.trim() || "admin-ui",
    last_updated: todayString(),
  };
}

function todayString(): string {
  return new Date().toISOString().slice(0, 10);
}
