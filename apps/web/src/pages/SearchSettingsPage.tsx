import { FormEvent, useEffect, useState } from "react";
import {
  createSearchConfig,
  deleteSearchConfig,
  listSearchConfigs,
  setDefaultSearchConfig,
  testSearchConfig,
  updateSearchConfig,
  type SearchApiConfigPayload,
  type SearchApiConfigPublic,
} from "../api/client";

interface FormState {
  id: number | null;
  name: string;
  provider: string;
  base_url: string;
  api_key: string;
  purpose: string;
  enabled: boolean;
  is_default: boolean;
}

const emptyForm: FormState = {
  id: null,
  name: "",
  provider: "tavily",
  base_url: "https://api.tavily.com",
  api_key: "",
  purpose: "general",
  enabled: true,
  is_default: false,
};

const providers = ["tavily", "custom"];
const purposes = ["address_research", "market_research", "general"];

export default function SearchSettingsPage() {
  const [configs, setConfigs] = useState<SearchApiConfigPublic[]>([]);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<number | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    void loadConfigs();
  }, []);

  async function loadConfigs() {
    setError(null);
    try {
      setConfigs(await listSearchConfigs());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "搜索配置加载失败");
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    setIsSaving(true);
    try {
      const payload = buildPayload(form);
      if (form.id) {
        await updateSearchConfig(form.id, payload);
        setNotice("搜索配置已更新");
      } else {
        await createSearchConfig({
          ...payload,
          name: payload.name || "",
          api_key: payload.api_key || "",
        });
        setNotice("搜索配置已新增");
      }
      setForm(emptyForm);
      await loadConfigs();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "搜索配置保存失败");
    } finally {
      setIsSaving(false);
    }
  }

  async function handleDelete(config: SearchApiConfigPublic) {
    setError(null);
    setNotice(null);
    try {
      await deleteSearchConfig(config.id);
      setNotice(`已删除 ${config.name}`);
      await loadConfigs();
      if (form.id === config.id) {
        setForm(emptyForm);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "搜索配置删除失败");
    }
  }

  async function handleSetDefault(config: SearchApiConfigPublic) {
    setError(null);
    setNotice(null);
    try {
      await setDefaultSearchConfig(config.id);
      setNotice(`${config.name} 已设为默认搜索配置`);
      await loadConfigs();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "设置默认失败");
    }
  }

  async function handleTest(config: SearchApiConfigPublic) {
    setError(null);
    setNotice(null);
    setTestingId(config.id);
    try {
      const response = await testSearchConfig(config.id);
      setNotice(
        response.success
          ? `搜索测试成功，返回 ${response.result_count} 条，耗时 ${response.latency_ms}ms`
          : `搜索测试失败：${response.error || "unknown error"} (${response.latency_ms}ms)`,
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "搜索测试失败");
    } finally {
      setTestingId(null);
    }
  }

  function edit(config: SearchApiConfigPublic) {
    setForm({
      id: config.id,
      name: config.name,
      provider: config.provider,
      base_url: config.base_url ?? "https://api.tavily.com",
      api_key: "",
      purpose: config.purpose,
      enabled: config.enabled,
      is_default: config.is_default,
    });
    setNotice("编辑模式：api_key 留空表示不修改当前密钥");
  }

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
      <header>
        <p className="text-sm font-medium text-blue-800">Search Settings</p>
        <h1 className="mt-1 text-2xl font-semibold text-slate-950">
          搜索 API 配置
        </h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
          用于 AI 自动报价时查询地址情况和市场行情参考。搜索结果只能生成风险备注，不能决定或修改报价金额。
        </p>
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

      <div className="grid gap-6 xl:grid-cols-[0.75fr_1.25fr]">
        <section className="panel p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="section-title">{form.id ? "编辑搜索配置" : "新增搜索配置"}</h2>
              <p className="mt-1 text-sm leading-6 text-slate-600">
                API Key 加密存储，接口只返回 masked key。Tavily 为默认推荐。
              </p>
            </div>
            <button className="btn-secondary" type="button" onClick={() => setForm(emptyForm)}>
              新建
            </button>
          </div>

          <form className="mt-5 grid gap-4" onSubmit={handleSubmit}>
            <TextField label="name *" value={form.name} onChange={(value) => update("name", value)} required />
            <label>
              <span className="field-label">provider</span>
              <select className="field-input" value={form.provider} onChange={(event) => update("provider", event.target.value)}>
                {providers.map((provider) => (
                  <option key={provider} value={provider}>
                    {provider}
                  </option>
                ))}
              </select>
            </label>
            <TextField label="base_url" value={form.base_url} onChange={(value) => update("base_url", value)} placeholder="https://api.tavily.com" />
            <label>
              <span className="field-label">api_key {form.id ? "" : "*"}</span>
              <input
                className="field-input"
                type="password"
                value={form.api_key}
                onChange={(event) => update("api_key", event.target.value)}
                autoComplete="new-password"
                required={!form.id}
              />
              {form.id && <p className="field-hint">留空表示不修改当前密钥</p>}
            </label>
            <label>
              <span className="field-label">purpose</span>
              <select className="field-input" value={form.purpose} onChange={(event) => update("purpose", event.target.value)}>
                {purposes.map((purpose) => (
                  <option key={purpose} value={purpose}>
                    {purpose}
                  </option>
                ))}
              </select>
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <CheckboxField label="enabled" checked={form.enabled} onChange={(value) => update("enabled", value)} />
              <CheckboxField label="is_default" checked={form.is_default} onChange={(value) => update("is_default", value)} />
            </div>
            <button className="btn-primary" type="submit" disabled={isSaving}>
              {isSaving ? "保存中..." : form.id ? "保存配置" : "新增配置"}
            </button>
          </form>
        </section>

        <section className="panel p-5">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="section-title">搜索配置列表</h2>
              <p className="mt-1 text-sm text-slate-600">
                搜索结果只进入 AI 参考上下文，不进入价格计算。
              </p>
            </div>
            <button className="btn-secondary" type="button" onClick={() => void loadConfigs()}>
              刷新
            </button>
          </div>

          <div className="mt-5 grid gap-4">
            {configs.length === 0 ? (
              <p className="rounded-md bg-slate-50 p-4 text-sm text-slate-600">
                还没有搜索 API 配置。
              </p>
            ) : (
              configs.map((config) => (
                <article key={config.id} className="rounded-md border border-slate-200 p-4">
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-base font-semibold text-slate-950">{config.name}</h3>
                        {config.is_default && (
                          <span className="rounded-md bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-800">
                            默认
                          </span>
                        )}
                        {!config.enabled && (
                          <span className="rounded-md bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-600">
                            disabled
                          </span>
                        )}
                      </div>
                      <dl className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                        <FieldValue label="provider" value={config.provider} />
                        <FieldValue label="purpose" value={config.purpose} />
                        <FieldValue label="masked_api_key" value={config.masked_api_key || "未设置"} />
                        <FieldValue label="base_url" value={config.base_url || "默认"} />
                        <FieldValue label="created_at" value={formatDate(config.created_at)} />
                        <FieldValue label="updated_at" value={formatDate(config.updated_at)} />
                      </dl>
                    </div>
                    <div className="grid min-w-40 gap-2 sm:grid-cols-2 lg:grid-cols-1">
                      <button className="btn-secondary" type="button" onClick={() => edit(config)}>
                        编辑
                      </button>
                      <button
                        className="btn-secondary"
                        type="button"
                        onClick={() => void handleSetDefault(config)}
                        disabled={config.is_default}
                      >
                        设为默认
                      </button>
                      <button
                        className="btn-secondary"
                        type="button"
                        onClick={() => void handleTest(config)}
                        disabled={testingId === config.id}
                      >
                        {testingId === config.id ? "测试中..." : "测试搜索"}
                      </button>
                      <button className="btn-danger" type="button" onClick={() => void handleDelete(config)}>
                        删除
                      </button>
                    </div>
                  </div>
                </article>
              ))
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function TextField({
  label,
  value,
  onChange,
  placeholder,
  required = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  required?: boolean;
}) {
  return (
    <label>
      <span className="field-label">{label}</span>
      <input
        className="field-input"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        required={required}
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

function FieldValue({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="metric-label">{label}</dt>
      <dd className="metric-value break-words font-mono tabular-nums">{value}</dd>
    </div>
  );
}

function buildPayload(form: FormState): SearchApiConfigPayload {
  const payload: SearchApiConfigPayload = {
    name: form.name.trim(),
    provider: form.provider,
    base_url: optionalText(form.base_url),
    purpose: form.purpose,
    enabled: form.enabled,
    is_default: form.is_default,
  };
  if (form.api_key.trim()) {
    payload.api_key = form.api_key.trim();
  }
  return payload;
}

function optionalText(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function formatDate(value: string | null): string {
  if (!value) {
    return "未返回";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
