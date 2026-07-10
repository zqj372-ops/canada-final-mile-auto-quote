import { FormEvent, useEffect, useState } from "react";
import {
  createAIConfig,
  createAIAgentModelConfig,
  deleteAIConfig,
  discoverAIModels,
  getAIAgentModelAssignment,
  listAIConfigs,
  listAIProviderPresets,
  setAIAgentModelAssignment,
  setDefaultAIConfig,
  testAIConfig,
  updateAIConfig,
  type AIProviderPreset,
  type AIModelConfigPayload,
  type AIModelConfigPublic,
  type DiscoveredModel,
} from "../api/client";

interface FormState {
  id: number | null;
  name: string;
  provider: string;
  base_url: string;
  api_key: string;
  model_name: string;
  temperature: string;
  max_tokens: string;
  timeout_seconds: string;
  purpose: string;
  enabled: boolean;
  is_default: boolean;
}

interface ImportState {
  provider: string;
  base_url: string;
  api_key: string;
  model_name: string;
  purpose: string;
  is_default: boolean;
  use_for_hermes: boolean;
}

type AISettingsSection = "hermes" | "import" | "manual" | "configs";

const emptyForm: FormState = {
  id: null,
  name: "",
  provider: "openai",
  base_url: "",
  api_key: "",
  model_name: "",
  temperature: "0",
  max_tokens: "800",
  timeout_seconds: "30",
  purpose: "general",
  enabled: true,
  is_default: false,
};

const emptyImport: ImportState = {
  provider: "openai",
  base_url: "https://api.openai.com/v1",
  api_key: "",
  model_name: "",
  purpose: "general",
  is_default: false,
  use_for_hermes: false,
};

const fallbackProviders = ["openai", "openrouter", "deepseek", "qwen", "moonshot", "zhipu", "custom"];
const purposes = ["field_extraction", "sales_note", "address_type", "general"];

export default function AISettingsPage() {
  const [configs, setConfigs] = useState<AIModelConfigPublic[]>([]);
  const [providerPresets, setProviderPresets] = useState<AIProviderPreset[]>([]);
  const [importForm, setImportForm] = useState<ImportState>(emptyImport);
  const [discoveredModels, setDiscoveredModels] = useState<DiscoveredModel[]>([]);
  const [hermesConfig, setHermesConfig] = useState<AIModelConfigPublic | null>(null);
  const [hermesSelection, setHermesSelection] = useState("");
  const [form, setForm] = useState<FormState>(emptyForm);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<number | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isDiscovering, setIsDiscovering] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [isSavingHermes, setIsSavingHermes] = useState(false);
  const [isTestingHermes, setIsTestingHermes] = useState(false);
  const [activeSection, setActiveSection] = useState<AISettingsSection>("hermes");

  useEffect(() => {
    void loadConfigs();
    void loadProviderPresets();
    void loadHermesConfig();
  }, []);

  async function loadConfigs() {
    setError(null);
    try {
      setConfigs(await listAIConfigs());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "AI 配置加载失败");
    }
  }

  async function loadProviderPresets() {
    try {
      const presets = await listAIProviderPresets();
      setProviderPresets(presets);
      const openai = presets.find((preset) => preset.provider === emptyImport.provider);
      if (openai?.base_url) {
        setImportForm((current) => ({ ...current, base_url: openai.base_url }));
      }
    } catch {
      setProviderPresets([]);
    }
  }

  async function loadHermesConfig() {
    try {
      const assignment = await getAIAgentModelAssignment("hermes");
      setHermesConfig(assignment.config);
      setHermesSelection(assignment.config ? String(assignment.config.id) : "");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Hermes Agent 配置加载失败");
    }
  }

  async function handleDiscoverModels() {
    setError(null);
    setNotice(null);
    setDiscoveredModels([]);
    if (!importForm.api_key.trim()) {
      setError("请先输入模型供应商 API Key");
      return;
    }
    if (!importForm.base_url.trim()) {
      setError("请先确认 base_url");
      return;
    }

    setIsDiscovering(true);
    try {
      const response = await discoverAIModels({
        provider: importForm.provider,
        base_url: importForm.base_url,
        api_key: importForm.api_key.trim(),
        timeout_seconds: 20,
      });
      setDiscoveredModels(response.models);
      if (response.models.length > 0) {
        setImportForm((current) => ({ ...current, model_name: response.models[0].id }));
      }
      setNotice(
        response.error
          ? `模型列表返回提示：${response.error}`
          : `已获取 ${response.models.length} 个模型${response.latency_ms ? `，耗时 ${response.latency_ms}ms` : ""}`,
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "模型列表获取失败");
    } finally {
      setIsDiscovering(false);
    }
  }

  async function handleImportModel() {
    setError(null);
    setNotice(null);
    if (!importForm.api_key.trim()) {
      setError("请先输入模型供应商 API Key");
      return;
    }
    if (!importForm.model_name.trim()) {
      setError("请先选择一个模型");
      return;
    }
    setIsImporting(true);
    try {
      const payload = {
        name: `${providerLabel(importForm.provider, providerPresets)} / ${importForm.model_name}`,
        provider: importForm.provider,
        base_url: optionalText(importForm.base_url),
        api_key: importForm.api_key.trim(),
        model_name: importForm.model_name.trim(),
        temperature: 0,
        max_tokens: 800,
        timeout_seconds: 30,
        purpose: importForm.purpose,
        enabled: true,
        is_default: importForm.is_default,
      };
      if (importForm.use_for_hermes) {
        const assignment = await createAIAgentModelConfig("hermes", payload);
        setHermesConfig(assignment.config);
        setHermesSelection(assignment.config ? String(assignment.config.id) : "");
      } else {
        await createAIConfig(payload);
      }
      setNotice(
        importForm.use_for_hermes
          ? "模型配置已导入并切换为 Hermes Agent 当前配置"
          : "模型配置已自动导入，可在列表中设为默认或测试连接",
      );
      setImportForm((current) => ({ ...current, api_key: "", model_name: "", use_for_hermes: false }));
      setDiscoveredModels([]);
      await Promise.all([loadConfigs(), loadHermesConfig()]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "模型配置导入失败");
    } finally {
      setIsImporting(false);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    if (!form.enabled && form.is_default) {
      setError("禁用的 AI 配置不能设为默认，请先启用或取消默认。");
      return;
    }
    setIsSaving(true);
    try {
      const payload = buildPayload(form);
      if (form.id) {
        await updateAIConfig(form.id, payload);
        setNotice("AI 配置已更新");
      } else {
        await createAIConfig({
          ...payload,
          name: payload.name || "",
          model_name: payload.model_name || "",
        });
        setNotice("AI 配置已新增");
      }
      setForm(emptyForm);
      await Promise.all([loadConfigs(), loadHermesConfig()]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "AI 配置保存失败");
    } finally {
      setIsSaving(false);
    }
  }

  async function handleDelete(config: AIModelConfigPublic) {
    if (!window.confirm(`确认删除 AI 配置「${config.name}」吗？`)) {
      return;
    }
    setError(null);
    setNotice(null);
    try {
      await deleteAIConfig(config.id);
      setNotice(`已删除 ${config.name}`);
      await Promise.all([loadConfigs(), loadHermesConfig()]);
      if (form.id === config.id) {
        setForm(emptyForm);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "AI 配置删除失败");
    }
  }

  async function handleSetDefault(config: AIModelConfigPublic) {
    setError(null);
    setNotice(null);
    if (!config.enabled) {
      setError("禁用的 AI 配置不能设为默认，请先启用后再设置。");
      return;
    }
    try {
      await setDefaultAIConfig(config.id);
      setNotice(`${config.name} 已设为默认`);
      await loadConfigs();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "设置默认失败");
    }
  }

  async function handleTest(config: AIModelConfigPublic) {
    setError(null);
    setNotice(null);
    setTestingId(config.id);
    try {
      const response = await testAIConfig(config.id);
      if (!response.success) {
        setError(`连接失败：${response.error || "unknown error"} (${response.latency_ms}ms)`);
        return;
      }
      setNotice(`连接成功，耗时 ${response.latency_ms}ms`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "测试连接失败");
    } finally {
      setTestingId(null);
    }
  }

  async function handleSaveHermesConfig() {
    const configId = Number(hermesSelection);
    if (!configId) {
      setError("请先选择 Hermes Agent 要使用的 API Key 与模型");
      return;
    }
    setError(null);
    setNotice(null);
    setIsSavingHermes(true);
    try {
      const assignment = await setAIAgentModelAssignment("hermes", configId);
      setHermesConfig(assignment.config);
      setNotice(
        assignment.config
          ? `Hermes Agent 已切换为 ${assignment.config.name} / ${assignment.config.model_name}`
          : "Hermes Agent 配置已更新",
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Hermes Agent 配置切换失败");
    } finally {
      setIsSavingHermes(false);
    }
  }

  async function handleTestHermesSelection() {
    const configId = Number(hermesSelection);
    if (!configId) {
      setError("请先选择要测试的模型配置");
      return;
    }
    setError(null);
    setNotice(null);
    setIsTestingHermes(true);
    try {
      const response = await testAIConfig(configId);
      if (!response.success) {
        setError(`Hermes 候选配置连接失败：${response.error || "unknown error"}`);
        return;
      }
      setNotice(`Hermes 候选配置连接成功，耗时 ${response.latency_ms}ms`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Hermes 候选配置测试失败");
    } finally {
      setIsTestingHermes(false);
    }
  }

  function edit(config: AIModelConfigPublic) {
    setForm({
      id: config.id,
      name: config.name,
      provider: config.provider,
      base_url: config.base_url ?? "",
      api_key: "",
      model_name: config.model_name,
      temperature: String(config.temperature),
      max_tokens: String(config.max_tokens),
      timeout_seconds: String(config.timeout_seconds),
      purpose: config.purpose,
      enabled: config.enabled,
      is_default: config.is_default,
    });
    setNotice("编辑模式：api_key 留空表示不修改密钥");
  }

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => {
      const next = { ...current, [key]: value };
      if (key === "enabled" && value === false) {
        next.is_default = false;
      }
      if (key === "is_default" && value === true && !next.enabled) {
        return current;
      }
      return next;
    });
  }

  function updateImport<K extends keyof ImportState>(key: K, value: ImportState[K]) {
    setImportForm((current) => ({ ...current, [key]: value }));
  }

  function selectImportProvider(provider: string) {
    const preset = providerPresets.find((item) => item.provider === provider);
    setImportForm((current) => ({
      ...current,
      provider,
      base_url: preset?.base_url ?? "",
      api_key: "",
      model_name: "",
    }));
    setDiscoveredModels([]);
  }

  const providerOptions = providerPresets.length
    ? providerPresets.map((preset) => preset.provider)
    : fallbackProviders;
  const enabledConfigs = configs.filter((config) => config.enabled);

  return (
    <div
      className="ai-settings-page mx-auto flex max-w-7xl flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8"
      data-active-section={activeSection}
    >
      <header>
        <p className="text-sm font-medium text-blue-800">AI Settings</p>
        <h1 className="mt-1 text-2xl font-semibold text-slate-950">
          大模型配置
        </h1>
      </header>

      <nav className="settings-section-tabs" aria-label="AI 模型配置分区">
        {([
          ["hermes", "Hermes"],
          ["import", "自动导入"],
          ["manual", "手动配置"],
          ["configs", `配置列表 ${configs.length}`],
        ] as Array<[AISettingsSection, string]>).map(([section, label]) => (
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

      {error && (
        <div
          className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900"
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

      <section className="panel ai-settings-section ai-settings-hermes overflow-hidden">
        <div className="border-b border-slate-200 bg-white px-5 py-5 text-slate-950 sm:px-6">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p className="text-sm font-semibold text-teal-700">Hermes Agent</p>
              <h2 className="mt-1 text-xl font-semibold">API Key 与模型切换</h2>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
                Hermes 使用独立绑定，切换不会改动 AI 报价的默认模型。密钥仅以加密形式保存。
              </p>
            </div>
            <div className="rounded-md border border-slate-200 bg-slate-50 px-4 py-3 lg:min-w-72">
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">当前使用</p>
              {hermesConfig ? (
                <div className="mt-2">
                  <p className="font-semibold text-slate-950">{hermesConfig.name}</p>
                  <p className="mt-1 text-sm text-slate-600">
                    {hermesConfig.provider} / {hermesConfig.model_name}
                  </p>
                  <p className="mt-1 font-mono text-xs text-slate-500">
                    {hermesConfig.masked_api_key || "未设置 API Key"}
                  </p>
                </div>
              ) : (
                <p className="mt-2 text-sm font-medium text-amber-700">未单独指定，当前回退到通用默认模型</p>
              )}
            </div>
          </div>
        </div>

        <div className="grid gap-4 p-5 sm:p-6 lg:grid-cols-[1fr_auto] lg:items-end">
          <label>
            <span className="field-label">选择 API Key / 模型配置</span>
            <select
              className="field-input"
              value={hermesSelection}
              onChange={(event) => setHermesSelection(event.target.value)}
            >
              <option value="">请选择已启用的配置</option>
              {enabledConfigs.map((config) => (
                <option key={config.id} value={config.id}>
                  {config.name} · {config.provider}/{config.model_name} · {config.masked_api_key || "无 Key"}
                </option>
              ))}
            </select>
            <p className="field-hint">
              如需新 Key 或新模型，可直接在下方“自动导入模型”中勾选用于 Hermes Agent。
            </p>
          </label>
          <div className="grid gap-2 sm:grid-cols-2 lg:min-w-72">
            <button
              className="btn-secondary"
              type="button"
              onClick={() => void handleTestHermesSelection()}
              disabled={!hermesSelection || isTestingHermes}
            >
              {isTestingHermes ? "测试中..." : "测试候选配置"}
            </button>
            <button
              className="btn-primary"
              type="button"
              onClick={() => void handleSaveHermesConfig()}
              disabled={!hermesSelection || isSavingHermes || Number(hermesSelection) === hermesConfig?.id}
            >
              {isSavingHermes ? "切换中..." : "切换 Hermes 配置"}
            </button>
          </div>
        </div>
      </section>

      <div className="ai-settings-sections">
        <div className="ai-settings-form-stack">
        <section className="panel ai-settings-section ai-settings-import p-5">
          <div>
            <h2 className="section-title">自动导入模型</h2>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              选择供应商后只输入 API Key，系统自动读取模型列表；选中后保存为可用模型配置。
            </p>
          </div>

          <div className="mt-5 grid gap-4">
            <label>
              <span className="field-label">模型供应商</span>
              <select
                className="field-input"
                value={importForm.provider}
                onChange={(event) => selectImportProvider(event.target.value)}
              >
                {providerOptions.map((provider) => (
                  <option key={provider} value={provider}>
                    {providerLabel(provider, providerPresets)}
                  </option>
                ))}
              </select>
            </label>
            <TextField
              label="base_url"
              value={importForm.base_url}
              onChange={(value) => updateImport("base_url", value)}
              placeholder="https://api.openai.com/v1"
            />
            <label>
              <span className="field-label">API Key</span>
              <input
                className="field-input"
                type="password"
                value={importForm.api_key}
                onChange={(event) => updateImport("api_key", event.target.value)}
                placeholder={providerHint(importForm.provider, providerPresets)}
                autoComplete="new-password"
              />
            </label>
            <button
              className="btn-secondary"
              type="button"
              onClick={() => void handleDiscoverModels()}
              disabled={isDiscovering}
            >
              {isDiscovering ? "正在获取模型..." : "获取模型列表"}
            </button>

            <label>
              <span className="field-label">选择模型</span>
              <select
                className="field-input"
                value={importForm.model_name}
                onChange={(event) => updateImport("model_name", event.target.value)}
                disabled={discoveredModels.length === 0}
              >
                <option value="">先获取模型列表</option>
                {discoveredModels.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.display_name || model.id}
                    {model.source === "recommended" ? " / 推荐" : ""}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span className="field-label">用途</span>
              <select
                className="field-input"
                value={importForm.purpose}
                onChange={(event) => updateImport("purpose", event.target.value)}
              >
                {purposes.map((purpose) => (
                  <option key={purpose} value={purpose}>
                    {purpose}
                  </option>
                ))}
              </select>
            </label>
            <CheckboxField
              label="保存后设为默认模型"
              checked={importForm.is_default}
              onChange={(value) => updateImport("is_default", value)}
            />
            <CheckboxField
              label="导入后切换给 Hermes Agent"
              checked={importForm.use_for_hermes}
              onChange={(value) => updateImport("use_for_hermes", value)}
            />
            <button
              className="btn-primary"
              type="button"
              onClick={() => void handleImportModel()}
              disabled={isImporting || !importForm.model_name}
            >
              {isImporting ? "正在导入..." : "导入并使用"}
            </button>
          </div>
        </section>

        <section className="panel ai-settings-section ai-settings-manual p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="section-title">{form.id ? "编辑配置" : "新增配置"}</h2>
              <p className="mt-1 text-sm leading-6 text-slate-600">
                API Key 使用密码输入框，接口返回只显示 masked key。
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
              <select
                className="field-input"
                value={form.provider}
                onChange={(event) => update("provider", event.target.value)}
              >
                {providerOptions.map((provider) => (
                  <option key={provider} value={provider}>
                    {providerLabel(provider, providerPresets)}
                  </option>
                ))}
              </select>
            </label>
            <TextField
              label="base_url"
              value={form.base_url}
              onChange={(value) => update("base_url", value)}
              placeholder="https://api.openai.com/v1"
            />
            <label>
              <span className="field-label">api_key</span>
              <input
                className="field-input"
                type="password"
                value={form.api_key}
                onChange={(event) => update("api_key", event.target.value)}
                autoComplete="new-password"
              />
              {form.id && <p className="field-hint">留空表示不修改当前密钥</p>}
            </label>
            <TextField
              label="model_name *"
              value={form.model_name}
              onChange={(value) => update("model_name", value)}
              required
            />
            <div className="grid gap-4 md:grid-cols-3">
              <NumberField label="temperature" value={form.temperature} onChange={(value) => update("temperature", value)} step="0.1" min="0" />
              <NumberField label="max_tokens" value={form.max_tokens} onChange={(value) => update("max_tokens", value)} step="1" min="1" />
              <NumberField label="timeout_seconds" value={form.timeout_seconds} onChange={(value) => update("timeout_seconds", value)} step="1" min="1" />
            </div>
            <label>
              <span className="field-label">purpose</span>
              <select
                className="field-input"
                value={form.purpose}
                onChange={(event) => update("purpose", event.target.value)}
              >
                {purposes.map((purpose) => (
                  <option key={purpose} value={purpose}>
                    {purpose}
                  </option>
                ))}
              </select>
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <CheckboxField label="enabled" checked={form.enabled} onChange={(value) => update("enabled", value)} />
              <CheckboxField label="is_default" checked={form.is_default} onChange={(value) => update("is_default", value)} disabled={!form.enabled} />
            </div>
            <button className="btn-primary" type="submit" disabled={isSaving}>
              {isSaving ? "保存中..." : form.id ? "保存配置" : "新增配置"}
            </button>
          </form>
        </section>
        </div>

        <section className="panel ai-settings-section ai-settings-configs p-5">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="section-title">配置列表</h2>
              <p className="mt-1 text-sm text-slate-600">
                不显示明文密钥，不向模型发送报价表或 SOP。
              </p>
            </div>
            <button className="btn-secondary" type="button" onClick={() => void loadConfigs()}>
              刷新
            </button>
          </div>

          <div className="mt-5 grid gap-4">
            {configs.length === 0 ? (
              <p className="rounded-md bg-slate-50 p-4 text-sm text-slate-600">
                还没有 AI 模型配置。
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
                        <FieldValue label="model_name" value={config.model_name} />
                        <FieldValue label="purpose" value={config.purpose} />
                        <FieldValue label="masked_api_key" value={config.masked_api_key || "未设置"} />
                        <FieldValue label="base_url" value={config.base_url || "未设置"} />
                        <FieldValue label="timeout" value={`${config.timeout_seconds}s`} />
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
                        disabled={config.is_default || !config.enabled}
                      >
                        设为默认
                      </button>
                      <button
                        className="btn-secondary"
                        type="button"
                        onClick={() => void handleTest(config)}
                        disabled={testingId === config.id}
                      >
                        {testingId === config.id ? "测试中..." : "测试连接"}
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

function NumberField({
  label,
  value,
  onChange,
  min,
  step,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  min?: string;
  step?: string;
}) {
  return (
    <label>
      <span className="field-label">{label}</span>
      <input
        className="field-input"
        type="number"
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
  disabled = false,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label className="flex min-h-11 items-center gap-3 rounded-md border border-slate-200 px-3 py-2">
      <input
        className="h-4 w-4 rounded border-slate-300 text-blue-700 focus:ring-blue-700"
        type="checkbox"
        checked={checked}
        disabled={disabled}
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

function buildPayload(form: FormState): AIModelConfigPayload {
  const payload: AIModelConfigPayload = {
    name: form.name.trim(),
    provider: form.provider,
    base_url: optionalText(form.base_url),
    model_name: form.model_name.trim(),
    temperature: Number(form.temperature),
    max_tokens: Number(form.max_tokens),
    timeout_seconds: Number(form.timeout_seconds),
    purpose: form.purpose,
    enabled: form.enabled,
    is_default: form.is_default,
  };
  if (form.api_key.trim()) {
    payload.api_key = form.api_key.trim();
  }
  return payload;
}

function providerLabel(provider: string, presets: AIProviderPreset[]): string {
  return presets.find((preset) => preset.provider === provider)?.label ?? provider;
}

function providerHint(provider: string, presets: AIProviderPreset[]): string {
  return presets.find((preset) => preset.provider === provider)?.api_key_hint ?? "输入 API Key";
}

function optionalText(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}
