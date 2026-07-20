import {
  FormEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type ReactNode,
} from "react";
import {
  getZonePricingConfig,
  importZonePriceMatrixSpreadsheet,
  listZonePriceMatrix,
  previewZonePriceMatrixImport,
  updateZonePricingConfig,
  upsertZonePriceMatrix,
  type MoneyValue,
  type ZonePriceMatrixListResponse,
  type ZonePriceMatrixPayload,
  type ZonePriceMatrixRecord,
  type ZonePriceImportPreview,
  type ZonePriceImportResult,
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
type PricingFieldKey = Exclude<
  keyof ZonePricingConfig,
  "fuel_percent_by_zone" | "zone_price_enabled" | "max_auto_quote_zone" | "zone_price_enabled_by_zone"
>;

const pricingFields: Array<{
  key: PricingFieldKey;
  label: string;
  suffix: string;
  step: number;
  hint: string;
}> = [
  { key: "fuel_percent", label: "默认燃油附加比例", suffix: "%", step: 0.01, hint: "分区未单独配置时使用。" },
  { key: "residential_fee_usd", label: "住宅附加费", suffix: "USD", step: 0.01, hint: "地址类型为住宅时收取。" },
  { key: "liftgate_fee_usd", label: "尾板费", suffix: "USD", step: 0.01, hint: "需要 liftgate 时收取。" },
  { key: "pallet_jack_fee_usd", label: "手叉车费", suffix: "USD", step: 0.01, hint: "需要 pallet jack 时收取。" },
  { key: "appointment_fee_usd", label: "预约费", suffix: "USD", step: 0.01, hint: "需要 appointment 时收取。" },
  { key: "detention_half_hour_fee_usd", label: "等待半小时费", suffix: "USD", step: 0.01, hint: "超过免费等待后按半小时向上取整。" },
  { key: "detention_free_minutes", label: "免费等待分钟", suffix: "分钟", step: 1, hint: "等待时间超过该分钟数后开始计费。" },
];

export default function PricingSettingsPage() {
  const [pricingConfig, setPricingConfig] = useState<ZonePricingConfig | null>(null);
  const [savedFuelPercentByZone, setSavedFuelPercentByZone] = useState<Record<string, MoneyValue>>({});
  const [savedZonePriceEnabledByZone, setSavedZonePriceEnabledByZone] = useState<Record<string, boolean>>({});
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
  const [activeSection, setActiveSection] = useState<PricingSettingsSection>("matrix");
  const [selectedZoneKey, setSelectedZoneKey] = useState("all");
  const [isImportOpen, setIsImportOpen] = useState(false);

  useEffect(() => {
    void loadAll();
  }, []);

  const matrixRows = useMemo(() => buildMatrixRows(matrix?.records ?? []), [matrix?.records]);
  const visibleMatrixRows = useMemo(
    () =>
      selectedZoneKey === "all"
        ? matrixRows
        : matrixRows.filter((row) => `${row.origin}|${row.zone}` === selectedZoneKey),
    [matrixRows, selectedZoneKey],
  );
  const fuelGroups = useMemo(() => buildFuelGroups(matrixRows, selectedZoneKey), [matrixRows, selectedZoneKey]);
  const changedCells = useMemo(() => {
    if (!matrix) {
      return [];
    }
    const recordsByKey = new Map(matrix.records.map((record) => [cellKey(record.origin, record.zone, record.billing_pallets), record]));
    return Object.entries(draftCells)
      .map(([key, value]) => ({ key, value, record: recordsByKey.get(key), parts: parseCellKey(key) }))
      .filter((entry) => entry.parts && entry.value.trim() && entry.value.trim() !== formatInputValue(entry.record?.base_price_usd));
  }, [draftCells, matrix]);
  const changedFuelZones = useMemo(() => {
    const current = pricingConfig?.fuel_percent_by_zone ?? {};
    const keys = new Set([...Object.keys(current), ...Object.keys(savedFuelPercentByZone)]);
    return Array.from(keys).filter(
      (key) => formatInputValue(current[key]) !== formatInputValue(savedFuelPercentByZone[key]),
    );
  }, [pricingConfig?.fuel_percent_by_zone, savedFuelPercentByZone]);
  const changedZoneSwitches = useMemo(() => {
    const current = pricingConfig?.zone_price_enabled_by_zone ?? {};
    const keys = new Set([...Object.keys(current), ...Object.keys(savedZonePriceEnabledByZone)]);
    return Array.from(keys).filter((key) => current[key] !== savedZonePriceEnabledByZone[key]);
  }, [pricingConfig?.zone_price_enabled_by_zone, savedZonePriceEnabledByZone]);
  const enabledZoneCount = useMemo(
    () => matrixRows.filter((row) => isZonePriceEnabled(pricingConfig, row.origin, row.zone)).length,
    [
      matrixRows,
      pricingConfig?.zone_price_enabled,
      pricingConfig?.max_auto_quote_zone,
      pricingConfig?.zone_price_enabled_by_zone,
    ],
  );
  const changedCount = changedCells.length + changedFuelZones.length + changedZoneSwitches.length;

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
      setSavedFuelPercentByZone({ ...nextPricing.fuel_percent_by_zone });
      setSavedZonePriceEnabledByZone({ ...nextPricing.zone_price_enabled_by_zone });
      setMatrix(nextMatrix);
      setDraftCells(buildDraftCells(nextMatrix.records));
      setSelectedZoneKey("all");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "价格配置加载失败");
    } finally {
      setIsLoading(false);
    }
  }

  async function loadMatrix(nextFilters: MatrixFilters = filters) {
    setIsLoading(true);
    setError(null);
    setNotice(null);
    try {
      const nextMatrix = await listZonePriceMatrix({ ...nextFilters, limit: 5000 });
      setMatrix(nextMatrix);
      setDraftCells(buildDraftCells(nextMatrix.records));
      setSelectedZoneKey("all");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "分区价格表加载失败");
    } finally {
      setIsLoading(false);
    }
  }

  async function savePricingChanges() {
    if (!pricingConfig) {
      return;
    }
    setError(null);
    setNotice(null);
    setIsSavingPricing(true);
    try {
      const saved = await updateZonePricingConfig(normalizePricingPayload(pricingConfig));
      setPricingConfig(saved);
      setSavedFuelPercentByZone({ ...saved.fuel_percent_by_zone });
      setSavedZonePriceEnabledByZone({ ...saved.zone_price_enabled_by_zone });
      setNotice("分区开关、燃油和附加费配置已保存，下一票报价会直接使用新配置。");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "燃油和附加费配置保存失败");
    } finally {
      setIsSavingPricing(false);
    }
  }

  async function savePricing(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await savePricingChanges();
  }

  async function saveMatrixChanges() {
    if (!changedCount) {
      setNotice("没有需要保存的分区价格修改。");
      return;
    }
    setError(null);
    setNotice(null);
    setIsSavingMatrix(true);
    try {
      const requests: Array<Promise<unknown>> = changedCells.map((entry) => {
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
        });
      if ((changedFuelZones.length || changedZoneSwitches.length) && pricingConfig) {
        requests.push(
          updateZonePricingConfig(normalizePricingPayload(pricingConfig)).then((saved) => {
            setPricingConfig(saved);
            setSavedFuelPercentByZone({ ...saved.fuel_percent_by_zone });
            setSavedZonePriceEnabledByZone({ ...saved.zone_price_enabled_by_zone });
          }),
        );
      }
      await Promise.all(requests);
      const savedCount = changedCount;
      await loadMatrix();
      setNotice(`已保存 ${savedCount} 项价格修改。`);
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

  function updatePricingField(key: PricingFieldKey, value: string) {
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

  function updateZoneFuelPercent(origin: string, zone: number, value: string) {
    setPricingConfig((current) => {
      if (!current) {
        return current;
      }
      const key = zoneFuelKey(origin, zone);
      const next = { ...(current.fuel_percent_by_zone ?? {}) };
      if (value.trim()) {
        next[key] = value;
      } else {
        delete next[key];
      }
      return { ...current, fuel_percent_by_zone: next };
    });
  }

  function updateZonePriceEnabled(origin: string, zone: number, enabled: boolean) {
    setPricingConfig((current) => {
      if (!current) {
        return current;
      }
      if (!current.zone_price_enabled) {
        return current;
      }
      const key = zoneFuelKey(origin, zone);
      const next = { ...(current.zone_price_enabled_by_zone ?? {}) };
      const defaultEnabled = current.max_auto_quote_zone === null || zone <= current.max_auto_quote_zone;
      if (enabled === defaultEnabled) {
        delete next[key];
      } else {
        next[key] = enabled;
      }
      return { ...current, zone_price_enabled_by_zone: next };
    });
  }

  return (
    <div className="pricing-page-v2" data-active-section={activeSection}>
      <header className="pricing-page-header">
        <div className="pricing-heading">
          <div className="pricing-breadcrumb" aria-label="当前位置">
            <span>运价管理</span>
            <span aria-hidden="true">/</span>
            <strong>价格配置</strong>
          </div>
          <h1>价格配置</h1>
          <p>维护 Zone 基础派送费、分区开关、燃油比例和附加费。前台只读取报价结果，不在浏览器计算价格。</p>
        </div>
        <div className="pricing-page-actions">
          <button className="btn-secondary" type="button" onClick={loadAll} disabled={isLoading}>
            <PricingIcon name="refresh" />
            {isLoading ? "读取中..." : "重新读取"}
          </button>
          <button className="btn-primary" type="button" onClick={saveMatrixChanges} disabled={isSavingMatrix || changedCount === 0}>
            <PricingIcon name="save" />
            {isSavingMatrix ? "保存中..." : `保存所有修改${changedCount ? ` · ${changedCount}` : ""}`}
          </button>
        </div>
      </header>

      {(error || notice) && (
        <div className={`pricing-feedback ${error ? "is-error" : "is-success"}`} role={error ? "alert" : "status"}>
          <PricingIcon name={error ? "alert" : "check"} />
          <span>{error || notice}</span>
        </div>
      )}

      <nav className="pricing-tabs" aria-label="价格配置分区">
        {([
          ["fees", "附加费规则", "全局规则"],
          ["new-price", "新增价格", "单条覆盖"],
          ["matrix", "价格矩阵", "Zone 管理"],
        ] as Array<[PricingSettingsSection, string, string]>).map(([section, label, meta]) => (
          <button
            key={section}
            className={activeSection === section ? "is-active" : ""}
            type="button"
            aria-selected={activeSection === section}
            onClick={() => setActiveSection(section)}
          >
            <span>{label}</span>
            <small>{meta}</small>
          </button>
        ))}
      </nav>

      {activeSection === "fees" && (
        <form className="pricing-panel pricing-fee-panel" onSubmit={savePricing}>
          <div className="pricing-panel-heading">
            <div>
              <span className="pricing-eyebrow">全局配置</span>
              <h2>燃油和附加费</h2>
              <p>默认燃油比例只在对应 Zone 没有单独覆盖时使用，其他费用继续全局生效。</p>
            </div>
            <button className="btn-primary" type="submit" disabled={!pricingConfig || isSavingPricing}>
              <PricingIcon name="save" />
              {isSavingPricing ? "保存中..." : "保存费用配置"}
            </button>
          </div>

          <div className="pricing-fee-layout">
            <section className="pricing-default-fuel">
              <div className="pricing-card-icon"><PricingIcon name="fuel" /></div>
              <span className="pricing-card-label">默认燃油附加比例</span>
              <div className="pricing-big-input">
                <input
                  type="number"
                  min={0}
                  step="0.01"
                  inputMode="decimal"
                  value={formatInputValue(pricingConfig?.fuel_percent)}
                  onChange={(event) => updatePricingField("fuel_percent", event.target.value)}
                  aria-label="默认燃油附加比例"
                />
                <span>%</span>
              </div>
              <p>未设置分区覆盖时，报价基础费会按这个比例增加。</p>
              <div className="pricing-inline-note"><PricingIcon name="info" />在“价格矩阵”里可以逐个 Zone 修改燃油比例。</div>
            </section>

            <div className="pricing-accessorial-grid">
              {pricingFields.filter((field) => field.key !== "fuel_percent").map((field) => (
                <label key={field.key} className="pricing-field-card">
                  <span className="pricing-card-label">{field.label}</span>
                  <div className="pricing-input-with-unit">
                    <input
                      type="number"
                      inputMode="decimal"
                      min={0}
                      step={field.step}
                      value={formatInputValue(pricingConfig?.[field.key])}
                      onChange={(event) => updatePricingField(field.key, event.target.value)}
                    />
                    <span>{field.suffix}</span>
                  </div>
                  <small>{field.hint}</small>
                </label>
              ))}
            </div>
          </div>
        </form>
      )}

      {activeSection === "new-price" && (
        <form className="pricing-panel pricing-new-price-panel" onSubmit={addOrUpdatePrice}>
          <div className="pricing-panel-heading">
            <div>
              <span className="pricing-eyebrow">单条覆盖</span>
              <h2>新增 / 覆盖 Zone 价格</h2>
              <p>用于临时补价或修正单个始发仓、Zone、托数的基础派送费。</p>
            </div>
            <span className="pricing-help-chip">保存后立即生效</span>
          </div>
          <div className="pricing-form-grid">
            <TextInput label="始发仓" value={newPrice.origin} onChange={(value) => setNewPrice((current) => ({ ...current, origin: value }))} />
            <TextInput label="Zone" type="number" value={newPrice.zone} onChange={(value) => setNewPrice((current) => ({ ...current, zone: value }))} />
            <TextInput label="托数" type="number" value={newPrice.billing_pallets} onChange={(value) => setNewPrice((current) => ({ ...current, billing_pallets: value }))} />
            <TextInput label="基础派送费 USD" type="number" step="0.01" value={newPrice.base_price_usd} onChange={(value) => setNewPrice((current) => ({ ...current, base_price_usd: value }))} />
            <TextInput label="来源备注" value={newPrice.source} onChange={(value) => setNewPrice((current) => ({ ...current, source: value }))} />
          </div>
          <div className="pricing-form-footer">
            <p>提交相同的始发仓 + Zone + 托数会覆盖原有基础价格。</p>
            <button className="btn-primary" type="submit" disabled={isSavingMatrix}>
              <PricingIcon name="plus" />
              {isSavingMatrix ? "保存中..." : "新增或覆盖"}
            </button>
          </div>
        </form>
      )}

      {activeSection === "matrix" && (
        <section className="pricing-matrix-workspace">
          <div className="pricing-command-bar">
            <div className="pricing-command-copy">
              <span className="pricing-eyebrow">Zone 管理</span>
              <h2>价格矩阵与分区状态</h2>
              <p>先选始发仓或 Zone，再维护分区开关与燃油附加；关闭的分区会转人工报价。</p>
            </div>
            <div className="pricing-filter-row">
              <FilterSelect label="始发仓" value={filters.origin} options={matrix?.origins ?? []} onChange={(value) => setFilters((current) => ({ ...current, origin: value }))} />
              <FilterSelect label="Zone" value={String(filters.zone)} options={(matrix?.zones ?? []).map(String)} onChange={(value) => setFilters((current) => ({ ...current, zone: value ? Number(value) : "" }))} />
              <FilterSelect label="托数" value={String(filters.billing_pallets)} options={(matrix?.billing_pallets ?? []).map(String)} onChange={(value) => setFilters((current) => ({ ...current, billing_pallets: value ? Number(value) : "" }))} />
              <button className="btn-secondary" type="button" onClick={() => void loadMatrix()} disabled={isLoading}>
                <PricingIcon name="filter" />
                筛选
              </button>
              <button className="pricing-quiet-button" type="button" onClick={() => { const cleared = { origin: "", zone: "", billing_pallets: "" } as MatrixFilters; setFilters(cleared); setSelectedZoneKey("all"); void loadMatrix(cleared); }}>
                重置
              </button>
            </div>
          </div>

          <div className="pricing-summary-strip">
            <Metric icon="rows" label="当前显示" value={`${matrix?.records.length ?? 0} 条`} />
            <Metric icon="check" label="可报价分区" value={`${enabledZoneCount} / ${matrixRows.length}`} />
            <Metric icon="warehouse" label="始发仓" value={(matrix?.origins ?? []).join(" / ") || "-"} />
            <Metric icon="pallet" label="托数列" value={`${matrix?.billing_pallets.length ?? 0} 列`} />
          </div>

          <div className="pricing-workspace-grid">
            <aside className="pricing-zone-rail" aria-label="始发仓和 Zone 列表">
              <div className="pricing-rail-heading">
                <div>
                  <span>快速定位</span>
                  <strong>始发仓 / Zone</strong>
                </div>
                <span className="pricing-rail-count">{matrixRows.length}</span>
              </div>
              <button className={`pricing-zone-item ${selectedZoneKey === "all" ? "is-active" : ""}`} type="button" onClick={() => setSelectedZoneKey("all")}>
                <span className="pricing-zone-item-icon"><PricingIcon name="rows" /></span>
                <span><strong>全部分区</strong><small>{matrixRows.length} 个 Zone</small></span>
              </button>
              <div className="pricing-zone-list">
                {matrixRows.map((row) => {
                  const key = `${row.origin}|${row.zone}`;
                  const enabled = isZonePriceEnabled(pricingConfig, row.origin, row.zone);
                  return (
                    <button className={`pricing-zone-item ${selectedZoneKey === key ? "is-active" : ""} ${enabled ? "" : "is-disabled"}`} key={key} type="button" onClick={() => setSelectedZoneKey(key)}>
                      <span className="pricing-zone-code">Z{String(row.zone).padStart(2, "0")}</span>
                      <span><strong>{row.origin}</strong><small>{row.records.size} 个托数价格 · {enabled ? "启用" : "已关闭"}</small></span>
                      <PricingIcon name="chevron" />
                    </button>
                  );
                })}
              </div>
            </aside>

            <div className="pricing-matrix-main">
              <section className="pricing-panel pricing-fuel-editor">
                <div className="pricing-panel-heading compact">
                  <div>
                    <span className="pricing-eyebrow">可覆盖配置</span>
                    <h3>分区开关与燃油比例</h3>
                    <p>全局上限决定默认状态，单区开关可以覆盖；全局总开关关闭时所有分区均转人工。</p>
                  </div>
                  <div className="pricing-save-state">
                    <span className={changedFuelZones.length + changedZoneSwitches.length ? "is-dirty" : "is-saved"}>
                      <PricingIcon name={changedFuelZones.length + changedZoneSwitches.length ? "alert" : "check"} />
                      {changedFuelZones.length + changedZoneSwitches.length
                        ? `${changedFuelZones.length + changedZoneSwitches.length} 项未保存`
                        : "已同步"}
                    </span>
                    <button className="btn-secondary" type="button" onClick={() => setIsImportOpen(true)}>
                      <PricingIcon name="upload" />
                      表格导入
                    </button>
                    <button className="btn-secondary" type="button" onClick={() => void savePricingChanges()} disabled={!pricingConfig || isSavingPricing || changedFuelZones.length + changedZoneSwitches.length === 0}>
                      {isSavingPricing ? "保存中..." : "保存分区配置"}
                    </button>
                  </div>
                </div>

                <div className="pricing-fuel-groups">
                  {fuelGroups.length ? fuelGroups.map((group) => (
                    <div className="pricing-fuel-group" key={group.origin}>
                      <div className="pricing-fuel-group-heading">
                        <span className="pricing-origin-mark"><PricingIcon name="warehouse" /></span>
                        <div><strong>{group.origin}</strong><small>按 Zone 独立覆盖</small></div>
                      </div>
                      <div className="pricing-fuel-grid">
                        {group.rows.map((row) => {
                          const fuelKey = zoneFuelKey(row.origin, row.zone);
                          const fuelValue = pricingConfig?.fuel_percent_by_zone?.[fuelKey];
                          const fuelChanged = formatInputValue(fuelValue) !== formatInputValue(savedFuelPercentByZone[fuelKey]);
                          const zoneEnabled = isZonePriceEnabled(pricingConfig, row.origin, row.zone);
                          const switchChanged = pricingConfig?.zone_price_enabled_by_zone?.[fuelKey] !== savedZonePriceEnabledByZone[fuelKey];
                          return (
                            <div className={`pricing-fuel-cell ${fuelChanged || switchChanged ? "is-dirty" : ""} ${zoneEnabled ? "" : "is-disabled"}`} key={fuelKey}>
                              <div className="pricing-fuel-cell-head">
                                <span>ZONE {row.zone}</span>
                                <label className="pricing-zone-switch">
                                  <input
                                    type="checkbox"
                                    checked={zoneEnabled}
                                    onChange={(event) => updateZonePriceEnabled(row.origin, row.zone, event.target.checked)}
                                    aria-label={`${row.origin} Zone ${row.zone} 价格${zoneEnabled ? "已启用" : "已关闭"}`}
                                    disabled={!pricingConfig?.zone_price_enabled}
                                  />
                                  <span aria-hidden="true"><i /></span>
                                  <strong>{!pricingConfig?.zone_price_enabled ? "全局关闭" : zoneEnabled ? "启用" : "已关闭"}</strong>
                                </label>
                              </div>
                              <div className="pricing-input-with-unit">
                                <input
                                  type="number"
                                  min={0}
                                  step="0.01"
                                  inputMode="decimal"
                                  value={formatInputValue(fuelValue)}
                                  placeholder={formatInputValue(pricingConfig?.fuel_percent) || "0"}
                                  onChange={(event) => updateZoneFuelPercent(row.origin, row.zone, event.target.value)}
                                  aria-label={`${row.origin} Zone ${row.zone} 燃油附加比例`}
                                  disabled={!zoneEnabled}
                                />
                                <span>%</span>
                              </div>
                              <small>{zoneEnabled ? (fuelValue === undefined || fuelValue === null || fuelValue === "" ? `默认 ${formatInputValue(pricingConfig?.fuel_percent) || "0"}%` : "已覆盖") : "价格保留，不参与自动报价"}</small>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )) : <div className="pricing-empty-state">暂无分区数据，请先读取价格矩阵。</div>}
                </div>
              </section>

              <section className="pricing-panel pricing-price-panel">
                <div className="pricing-panel-heading compact">
                  <div>
                    <span className="pricing-eyebrow">基础派送费</span>
                    <h3>按托数编辑价格</h3>
                    <p>黄色输入框表示当前页面有未保存修改。</p>
                  </div>
                  <span className="pricing-record-count">{visibleMatrixRows.length} 个 Zone</span>
                </div>
                <div className="pricing-table-wrap">
                  <table className="pricing-price-table">
                    <thead>
                      <tr>
                        <th className="pricing-sticky-col pricing-origin-col">始发仓</th>
                        <th className="pricing-sticky-col pricing-zone-col">Zone</th>
                        {(matrix?.billing_pallets ?? []).map((pallet) => <th key={pallet}>{pallet} 托</th>)}
                      </tr>
                    </thead>
                    <tbody>
                      {visibleMatrixRows.length ? visibleMatrixRows.map((row) => {
                        const zoneEnabled = isZonePriceEnabled(pricingConfig, row.origin, row.zone);
                        return (
                          <tr className={zoneEnabled ? "" : "is-disabled"} key={`${row.origin}-${row.zone}`}>
                            <td className="pricing-sticky-col pricing-origin-col"><strong>{row.origin}</strong></td>
                            <td className="pricing-sticky-col pricing-zone-col">
                              <span className="pricing-zone-badge">ZONE {row.zone}</span>
                              {!zoneEnabled && <small className="pricing-zone-disabled-badge">已关闭</small>}
                            </td>
                            {(matrix?.billing_pallets ?? []).map((pallet) => {
                              const key = cellKey(row.origin, row.zone, pallet);
                              const record = row.records.get(pallet);
                              const dirty = draftCells[key] !== undefined && draftCells[key] !== formatInputValue(record?.base_price_usd);
                              return (
                                <td key={key}>
                                  <input
                                    className={dirty ? "is-dirty" : ""}
                                    type="number"
                                    min={0}
                                    step="0.01"
                                    inputMode="decimal"
                                    value={draftCells[key] ?? ""}
                                    placeholder="—"
                                    onChange={(event) => setDraftCells((current) => ({ ...current, [key]: event.target.value }))}
                                    aria-label={`${row.origin} Zone ${row.zone} ${pallet} 托基础派送费`}
                                    disabled={!zoneEnabled}
                                  />
                                </td>
                              );
                            })}
                          </tr>
                        );
                      }) : (
                        <tr><td className="pricing-table-empty" colSpan={(matrix?.billing_pallets.length ?? 0) + 2}>暂无匹配的分区价格。</td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
                <div className="pricing-table-footer">
                  <span>当前显示 {visibleMatrixRows.length} 个 Zone · {matrix?.billing_pallets.length ?? 0} 个托数列</span>
                  <button className="btn-primary" type="button" onClick={saveMatrixChanges} disabled={isSavingMatrix || changedCount === 0}>
                    <PricingIcon name="save" />
                    {isSavingMatrix ? "保存中..." : `保存所有修改${changedCount ? ` · ${changedCount}` : ""}`}
                  </button>
                </div>
              </section>
            </div>
          </div>
        </section>
      )}

      <ZonePriceImportDialog
        open={isImportOpen}
        matrixRows={matrixRows}
        pallets={matrix?.billing_pallets ?? []}
        pricingConfig={pricingConfig}
        unsavedCount={changedCount}
        onClose={() => setIsImportOpen(false)}
        onImported={async (result) => {
          await loadAll();
          setNotice(
            `表格导入完成：新增 ${result.inserted_count} 条，覆盖 ${result.updated_count} 条${
              result.fuel_updated_count ? `，更新 ${result.fuel_updated_count} 个燃油比例` : ""
            }。`,
          );
        }}
      />
    </div>
  );
}

function ZonePriceImportDialog({
  open,
  matrixRows,
  pallets,
  pricingConfig,
  unsavedCount,
  onClose,
  onImported,
}: {
  open: boolean;
  matrixRows: ReturnType<typeof buildMatrixRows>;
  pallets: number[];
  pricingConfig: ZonePricingConfig | null;
  unsavedCount: number;
  onClose: () => void;
  onImported: (result: ZonePriceImportResult) => Promise<void>;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ZonePriceImportPreview | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isImporting, setIsImporting] = useState(false);

  useEffect(() => {
    if (!open) {
      return;
    }
    setFile(null);
    setPreview(null);
    setLocalError(null);
    setIsDragging(false);
    setIsPreviewing(false);
    setIsImporting(false);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    window.requestAnimationFrame(() => closeButtonRef.current?.focus());
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  if (!open) {
    return null;
  }

  async function selectFile(nextFile: File | undefined) {
    if (!nextFile) {
      return;
    }
    const extension = nextFile.name.split(".").pop()?.toLowerCase();
    if (!extension || !["csv", "xlsx", "xls"].includes(extension)) {
      setFile(null);
      setPreview(null);
      setLocalError("请选择 CSV、XLSX 或 XLS 表格文件。");
      return;
    }
    if (nextFile.size > 10 * 1024 * 1024) {
      setFile(null);
      setPreview(null);
      setLocalError("表格不能超过 10 MB。");
      return;
    }

    setFile(nextFile);
    setPreview(null);
    setLocalError(null);
    setIsPreviewing(true);
    try {
      setPreview(await previewZonePriceMatrixImport(nextFile));
    } catch (caught) {
      setLocalError(caught instanceof Error ? caught.message : "表格校验失败，请检查文件后重试。");
    } finally {
      setIsPreviewing(false);
    }
  }

  function handleDrop(event: DragEvent<HTMLButtonElement>) {
    event.preventDefault();
    setIsDragging(false);
    if (!isPreviewing && !isImporting) {
      void selectFile(event.dataTransfer.files[0]);
    }
  }

  async function confirmImport() {
    if (!file || !preview?.can_import || unsavedCount > 0) {
      return;
    }
    setLocalError(null);
    setIsImporting(true);
    try {
      const result = await importZonePriceMatrixSpreadsheet(file);
      await onImported(result);
      onClose();
    } catch (caught) {
      setLocalError(caught instanceof Error ? caught.message : "表格导入失败，请稍后重试。");
    } finally {
      setIsImporting(false);
    }
  }

  const step = preview ? 3 : file ? 2 : 1;

  return (
    <div
      className="pricing-import-backdrop"
      onMouseDown={(event) => {
        if (event.currentTarget === event.target && !isImporting) {
          onClose();
        }
      }}
    >
      <section
        className="pricing-import-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="pricing-import-title"
        aria-describedby="pricing-import-description"
      >
        <header className="pricing-import-header">
          <div>
            <span className="pricing-eyebrow">批量维护</span>
            <h2 id="pricing-import-title">导入价格矩阵</h2>
            <p id="pricing-import-description">上传后先校验并预览，确认后才会写入价格和分区燃油比例。</p>
          </div>
          <button
            ref={closeButtonRef}
            className="pricing-import-close"
            type="button"
            aria-label="关闭导入窗口"
            onClick={onClose}
            disabled={isImporting}
          >
            <PricingIcon name="close" />
          </button>
        </header>

        <div className="pricing-import-body">
          <ol className="pricing-import-steps" aria-label="导入步骤">
            {["选择表格", "校验数据", "确认导入"].map((label, index) => {
              const number = index + 1;
              return (
                <li className={number < step ? "is-complete" : number === step ? "is-active" : ""} key={label}>
                  <span>{number < step ? <PricingIcon name="check" /> : number}</span>
                  <strong>{label}</strong>
                </li>
              );
            })}
          </ol>

          {unsavedCount > 0 && (
            <div className="pricing-import-alert is-warning" role="alert">
              <PricingIcon name="alert" />
              <span>当前页面还有 {unsavedCount} 项未保存修改。请先保存或重新读取，再确认导入。</span>
            </div>
          )}

          <div className="pricing-import-tools">
            <div>
              <strong>选择价格表</strong>
              <span>支持宽表（1托、2托…）和明细表，最大 10 MB</span>
            </div>
            <button
              className="pricing-template-button"
              type="button"
              onClick={() => downloadZoneMatrixTemplate(matrixRows, pallets, pricingConfig)}
            >
              <PricingIcon name="download" />
              下载当前矩阵模板
            </button>
          </div>

          <input
            ref={fileInputRef}
            className="pricing-import-file-input"
            type="file"
            accept=".csv,.xlsx,.xls,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
            onChange={(event) => {
              void selectFile(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
          <button
            className={`pricing-import-dropzone ${isDragging ? "is-dragging" : ""} ${file ? "has-file" : ""}`}
            type="button"
            onClick={() => fileInputRef.current?.click()}
            onDragEnter={(event) => {
              event.preventDefault();
              setIsDragging(true);
            }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                setIsDragging(false);
              }
            }}
            onDrop={handleDrop}
            disabled={isPreviewing || isImporting}
          >
            <span className="pricing-import-file-icon"><PricingIcon name={file ? "file" : "upload"} /></span>
            {file ? (
              <span className="pricing-import-file-copy">
                <strong>{file.name}</strong>
                <small>{formatFileSize(file.size)} · 点击可更换文件</small>
              </span>
            ) : (
              <span className="pricing-import-file-copy">
                <strong>拖拽表格到这里，或点击选择文件</strong>
                <small>CSV · XLSX · XLS</small>
              </span>
            )}
            {isPreviewing && <span className="pricing-import-loading">正在校验…</span>}
          </button>

          {localError && (
            <div className="pricing-import-alert is-error" role="alert">
              <PricingIcon name="alert" />
              <span>{localError}</span>
            </div>
          )}

          {preview && (
            <div className="pricing-import-preview">
              <div className={`pricing-import-validation ${preview.can_import ? "is-valid" : "is-invalid"}`}>
                <span><PricingIcon name={preview.can_import ? "check" : "alert"} /></span>
                <div>
                  <strong>{preview.can_import ? "校验通过，可以导入" : "发现问题，暂不能导入"}</strong>
                  <small>
                    读取 {preview.source_row_count} 行，解析出 {preview.row_count} 条价格
                    {preview.invalid_row_count ? `，${preview.invalid_row_count} 行需修正` : ""}
                  </small>
                </div>
              </div>

              <dl className="pricing-import-summary">
                <div><dt>价格记录</dt><dd>{preview.row_count}</dd></div>
                <div><dt>新增</dt><dd>{preview.inserted_count}</dd></div>
                <div><dt>覆盖</dt><dd>{preview.updated_count}</dd></div>
                <div><dt>燃油比例</dt><dd>{preview.fuel_updated_count}</dd></div>
              </dl>

              {preview.errors.length > 0 && (
                <div className="pricing-import-issues is-error">
                  <strong>需要修正</strong>
                  <ul>
                    {preview.errors.slice(0, 6).map((issue, index) => (
                      <li key={`${issue.row ?? "file"}-${issue.field ?? "row"}-${index}`}>
                        {issue.row ? `第 ${issue.row} 行：` : ""}{issue.message}
                      </li>
                    ))}
                  </ul>
                  {preview.errors.length > 6 && <small>另有 {preview.errors.length - 6} 个问题未展开。</small>}
                </div>
              )}

              {preview.warnings.length > 0 && (
                <div className="pricing-import-issues is-warning">
                  <strong>提示</strong>
                  <ul>
                    {preview.warnings.map((issue, index) => <li key={`${issue.field ?? "warning"}-${index}`}>{issue.message}</li>)}
                  </ul>
                </div>
              )}

              {preview.preview_rows.length > 0 && (
                <div className="pricing-import-table-wrap">
                  <table className="pricing-import-table">
                    <thead>
                      <tr>
                        <th>表格行</th>
                        <th>始发仓</th>
                        <th>Zone</th>
                        <th>托数</th>
                        <th>基础派送费</th>
                        <th>燃油</th>
                        <th>处理</th>
                      </tr>
                    </thead>
                    <tbody>
                      {preview.preview_rows.map((row) => (
                        <tr key={`${row.row}-${row.origin}-${row.zone}-${row.billing_pallets}`}>
                          <td>{row.row}</td>
                          <td><strong>{row.origin}</strong></td>
                          <td>{row.zone}</td>
                          <td>{row.billing_pallets} 托</td>
                          <td>${formatInputValue(row.base_price_usd)}</td>
                          <td>{row.fuel_percent === null ? "—" : `${formatInputValue(row.fuel_percent)}%`}</td>
                          <td><span className={`pricing-import-action is-${row.action}`}>{row.action === "insert" ? "新增" : "覆盖"}</span></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {preview.row_count > preview.preview_rows.length && (
                    <span className="pricing-import-table-note">仅预览前 {preview.preview_rows.length} 条，确认后会导入全部有效记录。</span>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        <footer className="pricing-import-footer">
          <span>相同“始发仓 + Zone + 托数”的记录会被覆盖，不会产生重复价格。</span>
          <div>
            <button className="btn-secondary" type="button" onClick={onClose} disabled={isImporting}>取消</button>
            <button
              className="btn-primary"
              type="button"
              onClick={() => void confirmImport()}
              disabled={!file || !preview?.can_import || unsavedCount > 0 || isImporting}
            >
              <PricingIcon name="upload" />
              {isImporting ? "正在导入…" : `确认导入${preview?.row_count ? ` · ${preview.row_count}` : ""}`}
            </button>
          </div>
        </footer>
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

function Metric({ icon, label, value }: { icon: PricingIconName; label: string; value: string }) {
  return (
    <div className="pricing-summary-item">
      <span className="pricing-summary-icon"><PricingIcon name={icon} /></span>
      <div>
        <dt>{label}</dt>
        <dd>{value}</dd>
      </div>
    </div>
  );
}

type PricingIconName =
  | "alert"
  | "check"
  | "chevron"
  | "close"
  | "download"
  | "file"
  | "filter"
  | "fuel"
  | "info"
  | "pallet"
  | "plus"
  | "refresh"
  | "rows"
  | "save"
  | "upload"
  | "warehouse";

function PricingIcon({ name }: { name: PricingIconName }) {
  const paths: Record<PricingIconName, ReactNode> = {
    alert: <path d="M12 3 2.8 20h18.4L12 3Zm0 5.3v5.1m0 3.25h.01" />,
    check: <path d="m5 12 4.2 4L19 6.5" />,
    chevron: <path d="m9 6 6 6-6 6" />,
    close: <path d="m6 6 12 12M18 6 6 18" />,
    download: <><path d="M12 3v12m0 0 4-4m-4 4-4-4" /><path d="M5 19h14" /></>,
    file: <><path d="M6 3h8l4 4v14H6z" /><path d="M14 3v5h5M9 13h6m-6 4h6" /></>,
    filter: <path d="M4 5h16M7 12h10m-6 7h2" />,
    fuel: <path d="M7 20V5.5A1.5 1.5 0 0 1 8.5 4h5A1.5 1.5 0 0 1 15 5.5V20M5 20h12M9 8h4m-4 3h4m6-3 1.5 1.5v5a1.5 1.5 0 0 1-3 0v-4" />,
    info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v5m0-8h.01" /></>,
    pallet: <path d="M4 8h16v8H4zM7 8V5h10v3M7 16v3m5-3v3m5-3v3" />,
    plus: <path d="M12 5v14M5 12h14" />,
    refresh: <path d="M20 11a8 8 0 0 0-14.7-4L4 9m0 0V4m0 5h5M4 13a8 8 0 0 0 14.7 4L20 15m0 0v5m0-5h-5" />,
    rows: <path d="M5 6h14M5 12h14M5 18h14M2.5 6h.01M2.5 12h.01M2.5 18h.01" />,
    save: <><path d="M5 3h12l2 2v16H5z" /><path d="M8 3v6h8V3m-8 13h8" /></>,
    upload: <><path d="M12 16V4m0 0 4 4m-4-4-4 4" /><path d="M5 20h14" /></>,
    warehouse: <path d="M3 20V8l9-5 9 5v12M6 20v-7h12v7M9 16h6" />,
  };
  return (
    <svg aria-hidden="true" className="pricing-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      {paths[name]}
    </svg>
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

function buildFuelGroups(
  rows: Array<{ origin: string; zone: number; records: Map<number, ZonePriceMatrixRecord> }>,
  selectedZoneKey: string,
): Array<{ origin: string; rows: Array<{ origin: string; zone: number; records: Map<number, ZonePriceMatrixRecord> }> }> {
  const groups = new Map<string, Array<{ origin: string; zone: number; records: Map<number, ZonePriceMatrixRecord> }>>();
  rows
    .filter((row) => selectedZoneKey === "all" || `${row.origin}|${row.zone}` === selectedZoneKey)
    .forEach((row) => {
      const group = groups.get(row.origin) ?? [];
      group.push(row);
      groups.set(row.origin, group);
    });
  return Array.from(groups.entries())
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([origin, groupRows]) => ({ origin, rows: groupRows.sort((left, right) => left.zone - right.zone) }));
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

function zoneFuelKey(origin: string, zone: number): string {
  return `${origin.trim().toLowerCase()}|${zone}`;
}

function isZonePriceEnabled(
  config: ZonePricingConfig | null,
  origin: string,
  zone: number,
): boolean {
  if (!config?.zone_price_enabled) {
    return false;
  }
  const key = zoneFuelKey(origin, zone);
  if (key in config.zone_price_enabled_by_zone) {
    return config.zone_price_enabled_by_zone[key];
  }
  return config.max_auto_quote_zone === null || zone <= config.max_auto_quote_zone;
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
    fuel_percent_by_zone: { ...config.fuel_percent_by_zone },
    zone_price_enabled: Boolean(config.zone_price_enabled),
    max_auto_quote_zone: config.max_auto_quote_zone === null
      ? null
      : Math.max(1, Number(config.max_auto_quote_zone) || 1),
    zone_price_enabled_by_zone: { ...config.zone_price_enabled_by_zone },
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

function downloadZoneMatrixTemplate(
  rows: ReturnType<typeof buildMatrixRows>,
  pallets: number[],
  pricingConfig: ZonePricingConfig | null,
) {
  const templatePallets = pallets.length
    ? [...pallets].sort((left, right) => left - right)
    : Array.from({ length: 26 }, (_, index) => index + 1);
  const header = [
    "始发仓",
    "Zone",
    "燃油附加比例(%)",
    ...templatePallets.map((pallet) => `${pallet}托`),
    "来源备注",
    "更新日期",
  ];
  const dataRows: Array<Array<string | number>> = rows.length
    ? rows.map((row) => {
        const firstRecord = row.records.values().next().value as ZonePriceMatrixRecord | undefined;
        return [
          row.origin,
          row.zone,
          formatInputValue(pricingConfig?.fuel_percent_by_zone?.[zoneFuelKey(row.origin, row.zone)]),
          ...templatePallets.map((pallet) => formatInputValue(row.records.get(pallet)?.base_price_usd)),
          firstRecord?.source ?? "",
          firstRecord?.last_updated ?? todayString(),
        ];
      })
    : [["toronto", 1, "", ...templatePallets.map(() => ""), "供应商报价表", todayString()]];
  const csv = `\ufeff${[header, ...dataRows]
    .map((values) => values.map(escapeCsvCell).join(","))
    .join("\r\n")}`;
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `Zone价格矩阵导入模板_${todayString()}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function escapeCsvCell(value: string | number): string {
  const text = String(value ?? "");
  const safeText = /^[=+\-@]/.test(text) ? `'${text}` : text;
  return `"${safeText.replace(/"/g, '""')}"`;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function todayString(): string {
  return new Date().toISOString().slice(0, 10);
}
