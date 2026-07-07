import { FormEvent, type ReactNode, useEffect, useMemo, useState } from "react";
import {
  getQuoteWorkbenchConfig,
  updateQuoteWorkbenchConfig,
  type AddressType,
  type PackagingType,
  type ProvinceAlias,
  type QuoteWorkbenchConfig,
  type WorkbenchOption,
} from "../api/client";

type SettingsTab = "basic" | "options" | "risks" | "template" | "advanced";

const tabs: Array<{ id: SettingsTab; label: string }> = [
  { id: "basic", label: "基础文案" },
  { id: "options", label: "识别与默认值" },
  { id: "risks", label: "风险与标签" },
  { id: "template", label: "报价话术" },
  { id: "advanced", label: "高级 JSON" },
];

export default function QuoteSettingsPage() {
  const [config, setConfig] = useState<QuoteWorkbenchConfig | null>(null);
  const [jsonDraft, setJsonDraft] = useState("");
  const [activeTab, setActiveTab] = useState<SettingsTab>("basic");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    void loadConfig();
  }, []);

  const currentJson = useMemo(
    () => (config ? JSON.stringify(config, null, 2) : ""),
    [config],
  );

  async function loadConfig() {
    setError(null);
    setNotice(null);
    try {
      const nextConfig = await getQuoteWorkbenchConfig();
      setConfig(nextConfig);
      setJsonDraft(JSON.stringify(nextConfig, null, 2));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "报价配置加载失败");
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!config) {
      return;
    }
    setError(null);
    setNotice(null);
    const validationErrors = validateWorkbenchConfig(config);
    if (validationErrors.length > 0) {
      setError(formatValidationErrors(validationErrors));
      return;
    }
    setIsSaving(true);
    try {
      const saved = await updateQuoteWorkbenchConfig(config);
      setConfig(saved);
      setJsonDraft(JSON.stringify(saved, null, 2));
      setNotice("报价工作台配置已保存");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "报价配置保存失败");
    } finally {
      setIsSaving(false);
    }
  }

  function importJsonDraft() {
    setError(null);
    setNotice(null);
    try {
      const parsed = JSON.parse(jsonDraft) as unknown;
      const validationErrors = validateWorkbenchConfig(parsed);
      if (validationErrors.length > 0) {
        setError(formatValidationErrors(validationErrors));
        return;
      }
      setConfig(parsed as QuoteWorkbenchConfig);
      setNotice("JSON 已载入表单，检查无误后点击保存配置");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "JSON 格式错误");
    }
  }

  function update<K extends keyof QuoteWorkbenchConfig>(
    key: K,
    value: QuoteWorkbenchConfig[K],
  ) {
    setConfig((current) => (current ? { ...current, [key]: value } : current));
  }

  function updateParser<K extends keyof QuoteWorkbenchConfig["parser"]>(
    key: K,
    value: QuoteWorkbenchConfig["parser"][K],
  ) {
    setConfig((current) =>
      current ? { ...current, parser: { ...current.parser, [key]: value } } : current,
    );
  }

  function updateDefaults<K extends keyof QuoteWorkbenchConfig["defaults"]>(
    key: K,
    value: QuoteWorkbenchConfig["defaults"][K],
  ) {
    setConfig((current) =>
      current ? { ...current, defaults: { ...current.defaults, [key]: value } } : current,
    );
  }

  function updateRisks<K extends keyof QuoteWorkbenchConfig["risks"]>(
    key: K,
    value: QuoteWorkbenchConfig["risks"][K],
  ) {
    setConfig((current) =>
      current ? { ...current, risks: { ...current.risks, [key]: value } } : current,
    );
  }

  function updateTemplate<K extends keyof QuoteWorkbenchConfig["copy_template"]>(
    key: K,
    value: QuoteWorkbenchConfig["copy_template"][K],
  ) {
    setConfig((current) =>
      current
        ? { ...current, copy_template: { ...current.copy_template, [key]: value } }
        : current,
    );
  }

  if (!config) {
    return (
      <div className="mx-auto flex max-w-4xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
        <section className="panel p-6">
          <h1 className="text-2xl font-semibold text-slate-950">报价工作台后台配置</h1>
          <p className="mt-3 text-sm leading-6 text-slate-600">
            {error ? `配置加载失败：${error}` : "正在读取配置..."}
          </p>
          <button className="btn-primary mt-5" type="button" onClick={loadConfig}>
            重新读取
          </button>
        </section>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
      <header className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-sm font-medium text-blue-800">Quote Settings</p>
          <h1 className="mt-1 text-2xl font-semibold text-slate-950">
            报价工作台后台配置
          </h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
            这里保存 `/quote` 前台读取的配置。销售前台只消费配置，不维护业务规则。
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <a className="btn-secondary" href="../quote">
            打开前台
          </a>
          <button className="btn-secondary" type="button" onClick={loadConfig} disabled={isSaving}>
            重新读取
          </button>
        </div>
      </header>

      {error && (
        <div
          className="whitespace-pre-line rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900"
          role="alert"
        >
          {error}
        </div>
      )}
      {notice && (
        <div
          className="rounded-md border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-900"
          role="status"
        >
          {notice}
        </div>
      )}

      <form className="grid gap-6" onSubmit={handleSubmit}>
        <nav className="flex flex-wrap gap-2" aria-label="报价配置分组">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              className={`min-h-11 rounded-md px-4 py-2 text-sm font-semibold transition focus:outline-none focus:ring-2 focus:ring-blue-700 focus:ring-offset-2 ${
                activeTab === tab.id
                  ? "bg-blue-700 text-white"
                  : "border border-slate-300 bg-white text-slate-800 hover:bg-slate-50"
              }`}
              type="button"
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </nav>

        {activeTab === "basic" && (
          <ConfigSection title="基础文案" description="控制前台标题、按钮、状态标签和示例内容。">
            <div className="grid gap-4 md:grid-cols-2">
              <TextField label="页面标题" value={config.title} onChange={(value) => update("title", value)} />
              <TextField label="页面副标题" value={config.subtitle} onChange={(value) => update("subtitle", value)} />
              <TextField label="输入面板标题" value={config.input_title} onChange={(value) => update("input_title", value)} />
              <TextField label="输入框标签" value={config.input_label} onChange={(value) => update("input_label", value)} />
              <TextField label="主按钮" value={config.primary_button_label} onChange={(value) => update("primary_button_label", value)} />
              <TextField label="清空按钮" value={config.clear_button_label} onChange={(value) => update("clear_button_label", value)} />
              <TextField label="导入按钮" value={config.import_button_label} onChange={(value) => update("import_button_label", value)} />
            </div>
            <TextareaField label="示例输入" value={config.sample_input} onChange={(value) => update("sample_input", value)} minHeight="220px" />
            <StringListEditor
              label="支持格式提示"
              values={config.format_hints}
              onChange={(values) => update("format_hints", values)}
            />
            <KeyValueEditor
              label="状态标签"
              value={config.status_labels}
              onChange={(value) => update("status_labels", value)}
            />
          </ConfigSection>
        )}

        {activeTab === "options" && (
          <ConfigSection title="识别与默认值" description="控制前台可选项、解析规则和提交给后端的默认字段。">
            <div className="grid gap-6 xl:grid-cols-2">
              <OptionListEditor label="包装类型选项" values={config.packaging_options} onChange={(values) => update("packaging_options", values)} />
              <OptionListEditor label="地址类型选项" values={config.address_type_options} onChange={(values) => update("address_type_options", values)} />
              <OptionListEditor label="附加服务选项" values={config.service_options} onChange={(values) => update("service_options", values)} />
              <div className="grid gap-4 rounded-md border border-slate-200 p-4">
                <h3 className="section-title">默认提交值</h3>
                <SelectField
                  label="默认包装类型"
                  value={config.defaults.packaging_type}
                  options={config.packaging_options}
                  onChange={(value) => updateDefaults("packaging_type", value as PackagingType)}
                />
                <SelectField
                  label="默认地址类型"
                  value={config.defaults.address_type}
                  options={config.address_type_options}
                  onChange={(value) => updateDefaults("address_type", value as AddressType)}
                />
                <SelectField
                  label="是否可堆叠"
                  value={config.defaults.is_stackable === null ? "null" : String(config.defaults.is_stackable)}
                  options={[
                    { value: "null", label: "待确认" },
                    { value: "true", label: "是" },
                    { value: "false", label: "否" },
                  ]}
                  onChange={(value) => updateDefaults("is_stackable", value === "null" ? null : value === "true")}
                />
                <NumberField
                  label="显式托盘数"
                  value={config.defaults.explicit_pallet_count ?? ""}
                  onChange={(value) => updateDefaults("explicit_pallet_count", value === "" ? null : toInteger(value, 1))}
                  min={1}
                />
                <NumberField
                  label="默认等待时间（分钟）"
                  value={config.defaults.detention_minutes}
                  onChange={(value) => updateDefaults("detention_minutes", toInteger(value, 0))}
                  min={0}
                />
                <CheckboxField label="默认需要尾板" checked={config.defaults.requires_liftgate} onChange={(checked) => updateDefaults("requires_liftgate", checked)} />
                <CheckboxField label="默认需要手叉车" checked={config.defaults.requires_pallet_jack} onChange={(checked) => updateDefaults("requires_pallet_jack", checked)} />
                <CheckboxField label="默认需要预约" checked={config.defaults.requires_appointment} onChange={(checked) => updateDefaults("requires_appointment", checked)} />
                <CheckboxField label="默认推送企业微信" checked={config.defaults.notify_wecom} onChange={(checked) => updateDefaults("notify_wecom", checked)} />
              </div>
            </div>

            <div className="grid gap-4 rounded-md border border-slate-200 p-4">
              <h3 className="section-title">解析规则</h3>
              <div className="grid gap-4 md:grid-cols-2">
                <TextField label="加拿大邮编正则" value={config.parser.postal_code_pattern} onChange={(value) => updateParser("postal_code_pattern", value)} />
                <TextField label="默认国家" value={config.parser.default_country} onChange={(value) => updateParser("default_country", value)} />
              </div>
              <CheckboxField
                label="允许用空格分隔长宽高重量"
                checked={config.parser.allow_space_dimension_separator}
                onChange={(checked) => updateParser("allow_space_dimension_separator", checked)}
              />
              <StringListEditor label="尺寸分隔符" values={config.parser.dimension_separators} onChange={(values) => updateParser("dimension_separators", values)} compact />
              <StringListEditor label="重量单位" values={config.parser.weight_units} onChange={(values) => updateParser("weight_units", values)} compact />
              <StringListEditor label="国家别名" values={config.parser.country_aliases} onChange={(values) => updateParser("country_aliases", values)} compact />
            </div>
          </ConfigSection>
        )}

        {activeTab === "risks" && (
          <ConfigSection title="风险与标签" description="控制前台风险提示、后端风险标签中文名和省份别名。">
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <NumberField label="重货密度阈值 KG/CBM" value={config.risks.dense_density_kg_per_cbm} onChange={(value) => updateRisks("dense_density_kg_per_cbm", toNumber(value, 0))} min={0} step={1} />
              <NumberField label="泡货密度阈值 KG/CBM" value={config.risks.light_density_kg_per_cbm} onChange={(value) => updateRisks("light_density_kg_per_cbm", toNumber(value, 0))} min={0} step={1} />
              <NumberField label="超长边阈值 cm" value={config.risks.oversized_longest_side_cm} onChange={(value) => updateRisks("oversized_longest_side_cm", toNumber(value, 0))} min={0} step={1} />
              <NumberField label="重单件阈值 kg" value={config.risks.heavy_single_piece_kg} onChange={(value) => updateRisks("heavy_single_piece_kg", toNumber(value, 0))} min={0} step={1} />
            </div>
            <StringListEditor
              label="核心城市名单"
              values={config.risks.core_city_names}
              onChange={(values) => updateRisks("core_city_names", values)}
            />
            <KeyValueEditor
              label="附加费中文名"
              value={config.accessorial_labels}
              onChange={(value) => update("accessorial_labels", value)}
            />
            <KeyValueEditor
              label="后端风险标签中文名"
              value={config.backend_risk_tag_labels}
              onChange={(value) => update("backend_risk_tag_labels", value)}
            />
            <ProvinceListEditor
              values={config.provinces}
              onChange={(values) => update("provinces", values)}
            />
          </ConfigSection>
        )}

        {activeTab === "template" && (
          <ConfigSection title="报价话术" description="控制复制给客户的销售报价文本。金额仍然只来自后端 Quote Engine。">
            <div className="grid gap-4 md:grid-cols-3">
              <TextField label="币种显示" value={config.copy_template.currency_code} onChange={(value) => updateTemplate("currency_code", value)} />
              <NumberField label="报价有效期（天）" value={config.copy_template.valid_days} onChange={(value) => updateTemplate("valid_days", toInteger(value, 1))} min={1} />
              <TextField label="人工复核金额文案" value={config.copy_template.manual_price_text} onChange={(value) => updateTemplate("manual_price_text", value)} />
            </div>
            <StringListEditor label="费用包含" values={config.copy_template.included_items} onChange={(values) => updateTemplate("included_items", values)} />
            <StringListEditor label="费用不含" values={config.copy_template.excluded_items} onChange={(values) => updateTemplate("excluded_items", values)} />
            <TextareaField label="报价备注" value={config.copy_template.remark} onChange={(value) => updateTemplate("remark", value)} minHeight="160px" />
          </ConfigSection>
        )}

        {activeTab === "advanced" && (
          <ConfigSection title="高级 JSON" description="用于导出、排障或批量替换配置；日常维护优先使用上面的可视化表单。">
            <div className="flex flex-wrap gap-3">
              <button className="btn-secondary" type="button" onClick={() => setJsonDraft(currentJson)}>
                从当前表单生成 JSON
              </button>
              <button className="btn-secondary" type="button" onClick={importJsonDraft}>
                用 JSON 覆盖表单
              </button>
            </div>
            <TextareaField
              label="配置 JSON"
              value={jsonDraft}
              onChange={setJsonDraft}
              minHeight="560px"
              mono
            />
          </ConfigSection>
        )}

        <div className="sticky bottom-0 z-10 flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 bg-slate-100/95 px-1 py-4 backdrop-blur">
          <p className="text-sm text-slate-600">
            保存后前台 `/quote` 下次刷新会读取新配置。
          </p>
          <button className="btn-primary" type="submit" disabled={isSaving}>
            {isSaving ? "保存中..." : "保存配置"}
          </button>
        </div>
      </form>
    </div>
  );
}

function ConfigSection({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section className="panel grid gap-5 p-5">
      <div>
        <h2 className="section-title">{title}</h2>
        <p className="mt-1 text-sm leading-6 text-slate-600">{description}</p>
      </div>
      {children}
    </section>
  );
}

function TextField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label>
      <span className="field-label">{label}</span>
      <input className="field-input" value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function TextareaField({
  label,
  value,
  onChange,
  minHeight = "120px",
  mono = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  minHeight?: string;
  mono?: boolean;
}) {
  return (
    <label>
      <span className="field-label">{label}</span>
      <textarea
        className={`field-input ${mono ? "font-mono text-sm leading-6" : ""}`}
        style={{ minHeight }}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        spellCheck={false}
      />
    </label>
  );
}

function NumberField({
  label,
  value,
  onChange,
  min,
  step = 1,
}: {
  label: string;
  value: number | string;
  onChange: (value: string) => void;
  min?: number;
  step?: number;
}) {
  return (
    <label>
      <span className="field-label">{label}</span>
      <input
        className="field-input"
        type="number"
        inputMode="decimal"
        value={value}
        min={min}
        step={step}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function CheckboxField({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex min-h-11 items-center gap-3 rounded-md border border-slate-200 px-3 py-2">
      <input
        className="h-4 w-4 rounded border-slate-300 text-blue-700 focus:ring-blue-700"
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className="text-sm font-medium text-slate-800">{label}</span>
    </label>
  );
}

function SelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: WorkbenchOption[];
  onChange: (value: string) => void;
}) {
  return (
    <label>
      <span className="field-label">{label}</span>
      <select className="field-input" value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function OptionListEditor({
  label,
  values,
  onChange,
}: {
  label: string;
  values: WorkbenchOption[];
  onChange: (values: WorkbenchOption[]) => void;
}) {
  return (
    <div className="grid gap-3 rounded-md border border-slate-200 p-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="section-title">{label}</h3>
        <button className="btn-secondary min-h-10 px-3 py-1" type="button" onClick={() => onChange([...values, { value: "", label: "" }])}>
          新增
        </button>
      </div>
      <div className="grid gap-3">
        {values.map((item, index) => (
          <div key={index} className="grid gap-3 rounded-md border border-slate-100 bg-slate-50 p-3 md:grid-cols-[1fr_1fr_auto]">
            <TextField label="值" value={item.value} onChange={(value) => updateOption(values, onChange, index, { ...item, value })} />
            <TextField label="显示名" value={item.label} onChange={(value) => updateOption(values, onChange, index, { ...item, label: value })} />
            <button className="btn-danger self-end px-3" type="button" onClick={() => onChange(values.filter((_, itemIndex) => itemIndex !== index))}>
              删除
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function StringListEditor({
  label,
  values,
  onChange,
  compact = false,
}: {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
  compact?: boolean;
}) {
  return (
    <label>
      <span className="field-label">{label}</span>
      <textarea
        className={`field-input ${compact ? "min-h-24" : "min-h-40"}`}
        value={values.join("\n")}
        onChange={(event) => onChange(splitLines(event.target.value))}
      />
      <span className="field-hint">每行一项</span>
    </label>
  );
}

function KeyValueEditor({
  label,
  value,
  onChange,
}: {
  label: string;
  value: Record<string, string>;
  onChange: (value: Record<string, string>) => void;
}) {
  const entries = Object.entries(value);
  return (
    <div className="grid gap-3 rounded-md border border-slate-200 p-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="section-title">{label}</h3>
        <button className="btn-secondary min-h-10 px-3 py-1" type="button" onClick={() => onChange({ ...value, "": "" })}>
          新增
        </button>
      </div>
      <div className="grid gap-3">
        {entries.map(([entryKey, entryValue], index) => (
          <div key={`${entryKey}-${index}`} className="grid gap-3 rounded-md border border-slate-100 bg-slate-50 p-3 md:grid-cols-[1fr_1fr_auto]">
            <TextField
              label="系统字段"
              value={entryKey}
              onChange={(nextKey) => {
                const nextEntries = [...entries];
                nextEntries[index] = [nextKey, entryValue];
                onChange(Object.fromEntries(nextEntries.filter(([key]) => key.trim())));
              }}
            />
            <TextField
              label="中文显示"
              value={entryValue}
              onChange={(nextValue) => {
                const nextEntries = [...entries];
                nextEntries[index] = [entryKey, nextValue];
                onChange(Object.fromEntries(nextEntries.filter(([key]) => key.trim())));
              }}
            />
            <button
              className="btn-danger self-end px-3"
              type="button"
              onClick={() => onChange(Object.fromEntries(entries.filter((_, itemIndex) => itemIndex !== index)))}
            >
              删除
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function ProvinceListEditor({
  values,
  onChange,
}: {
  values: ProvinceAlias[];
  onChange: (values: ProvinceAlias[]) => void;
}) {
  return (
    <div className="grid gap-3 rounded-md border border-slate-200 p-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="section-title">省份别名</h3>
        <button
          className="btn-secondary min-h-10 px-3 py-1"
          type="button"
          onClick={() => onChange([...values, { code: "", name: "", aliases: [] }])}
        >
          新增
        </button>
      </div>
      <div className="grid gap-3">
        {values.map((province, index) => (
          <div key={`${province.code}-${index}`} className="grid gap-3 rounded-md border border-slate-100 bg-slate-50 p-3 lg:grid-cols-[0.45fr_0.8fr_1.5fr_auto]">
            <TextField label="缩写" value={province.code} onChange={(code) => updateProvince(values, onChange, index, { ...province, code })} />
            <TextField label="省份名称" value={province.name} onChange={(name) => updateProvince(values, onChange, index, { ...province, name })} />
            <TextareaField
              label="别名"
              value={province.aliases.join("\n")}
              onChange={(text) => updateProvince(values, onChange, index, { ...province, aliases: splitLines(text) })}
              minHeight="96px"
            />
            <button className="btn-danger self-end px-3" type="button" onClick={() => onChange(values.filter((_, itemIndex) => itemIndex !== index))}>
              删除
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function updateOption(
  values: WorkbenchOption[],
  onChange: (values: WorkbenchOption[]) => void,
  index: number,
  nextValue: WorkbenchOption,
) {
  const next = [...values];
  next[index] = nextValue;
  onChange(next);
}

function updateProvince(
  values: ProvinceAlias[],
  onChange: (values: ProvinceAlias[]) => void,
  index: number,
  nextValue: ProvinceAlias,
) {
  const next = [...values];
  next[index] = nextValue;
  onChange(next);
}

function splitLines(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

type JsonRecord = Record<string, unknown>;

function validateWorkbenchConfig(value: unknown): string[] {
  const errors: string[] = [];
  const root = requireRecord(value, "配置", errors);
  if (!root) {
    return errors;
  }

  [
    ["title", "页面标题"],
    ["subtitle", "页面副标题"],
    ["input_title", "输入面板标题"],
    ["input_label", "输入框标签"],
    ["primary_button_label", "主按钮"],
    ["clear_button_label", "清空按钮"],
    ["import_button_label", "导入按钮"],
    ["sample_input", "示例输入"],
  ].forEach(([key, label]) => requireNonEmptyString(root[key], label, errors));

  requireStringArray(root.format_hints, "支持格式提示", errors, { minItems: 1 });
  requireStringMap(root.status_labels, "状态标签", errors, { minItems: 1 });
  requireStringMap(root.accessorial_labels, "附加费中文名", errors);
  requireStringMap(root.backend_risk_tag_labels, "后端风险标签中文名", errors);

  const packagingOptionValues = validateOptions(root.packaging_options, "包装类型选项", errors);
  const addressTypeOptionValues = validateOptions(root.address_type_options, "地址类型选项", errors);
  validateOptions(root.service_options, "附加服务选项", errors);
  validateProvinces(root.provinces, errors);
  validateParser(root.parser, errors);
  validateDefaults(root.defaults, packagingOptionValues, addressTypeOptionValues, errors);
  validateRisks(root.risks, errors);
  validateCopyTemplate(root.copy_template, errors);

  return errors;
}

function validateParser(value: unknown, errors: string[]) {
  const parser = requireRecord(value, "解析规则", errors);
  if (!parser) {
    return;
  }
  const pattern = requireNonEmptyString(parser.postal_code_pattern, "加拿大邮编正则", errors);
  if (pattern) {
    try {
      new RegExp(pattern);
    } catch {
      errors.push("加拿大邮编正则不是有效的正则表达式");
    }
  }
  requireNonEmptyString(parser.default_country, "默认国家", errors);
  requireBoolean(parser.allow_space_dimension_separator, "允许用空格分隔长宽高重量", errors);
  requireStringArray(parser.dimension_separators, "尺寸分隔符", errors, { minItems: 1 });
  requireStringArray(parser.weight_units, "重量单位", errors, { minItems: 1 });
  requireStringArray(parser.country_aliases, "国家别名", errors);
}

function validateDefaults(
  value: unknown,
  packagingOptionValues: string[],
  addressTypeOptionValues: string[],
  errors: string[],
) {
  const defaults = requireRecord(value, "默认提交值", errors);
  if (!defaults) {
    return;
  }
  const packagingType = requireNonEmptyString(defaults.packaging_type, "默认包装类型", errors);
  if (packagingType && !packagingOptionValues.includes(packagingType)) {
    errors.push("默认包装类型必须存在于包装类型选项中");
  }
  const addressType = requireNonEmptyString(defaults.address_type, "默认地址类型", errors);
  if (addressType && !addressTypeOptionValues.includes(addressType)) {
    errors.push("默认地址类型必须存在于地址类型选项中");
  }
  if (defaults.is_stackable !== null) {
    requireBoolean(defaults.is_stackable, "是否可堆叠", errors);
  }
  if (defaults.explicit_pallet_count !== null) {
    requireNumber(defaults.explicit_pallet_count, "显式托盘数", errors, { min: 1, integer: true });
  }
  requireBoolean(defaults.requires_liftgate, "默认需要尾板", errors);
  requireBoolean(defaults.requires_pallet_jack, "默认需要手叉车", errors);
  requireBoolean(defaults.requires_appointment, "默认需要预约", errors);
  requireNumber(defaults.detention_minutes, "默认等待时间", errors, { min: 0, integer: true });
  requireBoolean(defaults.notify_wecom, "默认推送企业微信", errors);
}

function validateRisks(value: unknown, errors: string[]) {
  const risks = requireRecord(value, "风险与标签", errors);
  if (!risks) {
    return;
  }
  requireNumber(risks.dense_density_kg_per_cbm, "重货密度阈值", errors, { min: 0 });
  requireNumber(risks.light_density_kg_per_cbm, "泡货密度阈值", errors, { min: 0 });
  requireNumber(risks.oversized_longest_side_cm, "超长边阈值", errors, { min: 0 });
  requireNumber(risks.heavy_single_piece_kg, "重单件阈值", errors, { min: 0 });
  requireStringArray(risks.core_city_names, "核心城市名单", errors);
}

function validateCopyTemplate(value: unknown, errors: string[]) {
  const copyTemplate = requireRecord(value, "报价话术", errors);
  if (!copyTemplate) {
    return;
  }
  requireNonEmptyString(copyTemplate.currency_code, "币种显示", errors);
  requireNumber(copyTemplate.valid_days, "报价有效期", errors, { min: 1, integer: true });
  requireNonEmptyString(copyTemplate.manual_price_text, "人工复核金额文案", errors);
  requireStringArray(copyTemplate.included_items, "费用包含", errors, { minItems: 1 });
  requireStringArray(copyTemplate.excluded_items, "费用不含", errors, { minItems: 1 });
  requireNonEmptyString(copyTemplate.remark, "报价备注", errors);
}

function validateOptions(value: unknown, label: string, errors: string[]): string[] {
  if (!Array.isArray(value) || value.length === 0) {
    errors.push(`${label}至少需要一项`);
    return [];
  }
  const optionValues: string[] = [];
  const seen = new Set<string>();
  value.forEach((item, index) => {
    const option = requireRecord(item, `${label}第 ${index + 1} 项`, errors);
    if (!option) {
      return;
    }
    const optionValue = requireNonEmptyString(option.value, `${label}第 ${index + 1} 项值`, errors);
    requireNonEmptyString(option.label, `${label}第 ${index + 1} 项显示名`, errors);
    if (!optionValue) {
      return;
    }
    optionValues.push(optionValue);
    if (seen.has(optionValue)) {
      errors.push(`${label}存在重复值：${optionValue}`);
    }
    seen.add(optionValue);
  });
  return optionValues;
}

function validateProvinces(value: unknown, errors: string[]) {
  if (!Array.isArray(value) || value.length === 0) {
    errors.push("省份别名至少需要一项");
    return;
  }
  value.forEach((item, index) => {
    const province = requireRecord(item, `省份别名第 ${index + 1} 项`, errors);
    if (!province) {
      return;
    }
    requireNonEmptyString(province.code, `省份别名第 ${index + 1} 项缩写`, errors);
    requireNonEmptyString(province.name, `省份别名第 ${index + 1} 项名称`, errors);
    requireStringArray(province.aliases, `省份别名第 ${index + 1} 项别名`, errors);
  });
}

function requireRecord(value: unknown, label: string, errors: string[]): JsonRecord | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    errors.push(`${label}必须是对象`);
    return null;
  }
  return value as JsonRecord;
}

function requireNonEmptyString(value: unknown, label: string, errors: string[]): string | null {
  if (typeof value !== "string" || !value.trim()) {
    errors.push(`${label}不能为空`);
    return null;
  }
  return value.trim();
}

function requireStringArray(
  value: unknown,
  label: string,
  errors: string[],
  options: { minItems?: number } = {},
) {
  if (!Array.isArray(value)) {
    errors.push(`${label}必须是数组`);
    return;
  }
  const minItems = options.minItems ?? 0;
  if (value.length < minItems) {
    errors.push(`${label}至少需要 ${minItems} 项`);
  }
  value.forEach((item, index) => {
    if (typeof item !== "string" || !item.trim()) {
      errors.push(`${label}第 ${index + 1} 项不能为空`);
    }
  });
}

function requireStringMap(
  value: unknown,
  label: string,
  errors: string[],
  options: { minItems?: number } = {},
) {
  const record = requireRecord(value, label, errors);
  if (!record) {
    return;
  }
  const entries = Object.entries(record);
  const minItems = options.minItems ?? 0;
  if (entries.length < minItems) {
    errors.push(`${label}至少需要 ${minItems} 项`);
  }
  entries.forEach(([key, entryValue]) => {
    if (!key.trim()) {
      errors.push(`${label}不能包含空字段名`);
    }
    if (typeof entryValue !== "string" || !entryValue.trim()) {
      errors.push(`${label}.${key || "(空字段)"} 不能为空`);
    }
  });
}

function requireBoolean(value: unknown, label: string, errors: string[]) {
  if (typeof value !== "boolean") {
    errors.push(`${label}必须是 true 或 false`);
  }
}

function requireNumber(
  value: unknown,
  label: string,
  errors: string[],
  options: { min?: number; integer?: boolean } = {},
) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    errors.push(`${label}必须是数字`);
    return;
  }
  if (options.integer && !Number.isInteger(value)) {
    errors.push(`${label}必须是整数`);
  }
  if (options.min !== undefined && value < options.min) {
    errors.push(`${label}不能小于 ${options.min}`);
  }
}

function formatValidationErrors(errors: string[]): string {
  return `配置校验未通过：\n- ${errors.slice(0, 12).join("\n- ")}${
    errors.length > 12 ? `\n- 还有 ${errors.length - 12} 个问题未显示` : ""
  }`;
}

function toNumber(value: string, min: number): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return min;
  }
  return Math.max(min, parsed);
}

function toInteger(value: string, min: number): number {
  return Math.trunc(toNumber(value, min));
}
