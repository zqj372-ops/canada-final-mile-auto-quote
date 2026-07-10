import { useEffect, useMemo, useState } from "react";
import {
  createAIAgentModelConfig,
  discoverAIModels,
  getAIAgentModelAssignment,
  listAIConfigs,
  listAIProviderPresets,
  setAIAgentModelAssignment,
  testAIConfig,
  type AIModelConfigPublic,
  type AIProviderPreset,
  type DiscoveredModel,
} from "../api/client";

interface HermesModelSwitcherProps {
  onConfigChange?: (config: AIModelConfigPublic | null) => void;
}

interface NewHermesConfig {
  provider: string;
  baseUrl: string;
  apiKey: string;
  modelName: string;
}

const fallbackProviders = ["openai", "openrouter", "deepseek", "qwen", "moonshot", "custom"];
const emptyNewConfig: NewHermesConfig = {
  provider: "openai",
  baseUrl: "https://api.openai.com/v1",
  apiKey: "",
  modelName: "",
};

export default function HermesModelSwitcher({ onConfigChange }: HermesModelSwitcherProps) {
  const [configs, setConfigs] = useState<AIModelConfigPublic[]>([]);
  const [presets, setPresets] = useState<AIProviderPreset[]>([]);
  const [currentConfig, setCurrentConfig] = useState<AIModelConfigPublic | null>(null);
  const [selectedConfigId, setSelectedConfigId] = useState("");
  const [newConfig, setNewConfig] = useState<NewHermesConfig>(emptyNewConfig);
  const [discoveredModels, setDiscoveredModels] = useState<DiscoveredModel[]>([]);
  const [showNewConfig, setShowNewConfig] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isSwitching, setIsSwitching] = useState(false);
  const [isDiscovering, setIsDiscovering] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    void loadSwitcher();
  }, []);

  async function loadSwitcher() {
    setIsLoading(true);
    setError(null);
    try {
      const [availableConfigs, assignment, providerPresets] = await Promise.all([
        listAIConfigs(),
        getAIAgentModelAssignment("hermes"),
        listAIProviderPresets().catch(() => []),
      ]);
      setConfigs(availableConfigs);
      setPresets(providerPresets);
      applyCurrentConfig(assignment.config);

      const openAI = providerPresets.find((preset) => preset.provider === "openai");
      if (openAI?.base_url) {
        setNewConfig((value) => ({ ...value, baseUrl: openAI.base_url }));
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Hermes 模型配置加载失败");
    } finally {
      setIsLoading(false);
    }
  }

  function applyCurrentConfig(config: AIModelConfigPublic | null) {
    setCurrentConfig(config);
    setSelectedConfigId(config ? String(config.id) : "");
    onConfigChange?.(config);
  }

  async function switchConfig() {
    const configId = Number(selectedConfigId);
    if (!configId) {
      setError("请选择 Hermes 要使用的 API Key 与模型。");
      return;
    }
    setIsSwitching(true);
    setError(null);
    setNotice(null);
    try {
      const assignment = await setAIAgentModelAssignment("hermes", configId);
      applyCurrentConfig(assignment.config);
      setNotice(`已切换，Hermes 下一次运行将使用 ${assignment.config?.model_name || "新配置"}。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Hermes 配置切换失败");
    } finally {
      setIsSwitching(false);
    }
  }

  async function testSelectedConfig() {
    const configId = Number(selectedConfigId);
    if (!configId) {
      setError("请先选择要测试的 API Key 与模型。");
      return;
    }
    setIsTesting(true);
    setError(null);
    setNotice(null);
    try {
      const result = await testAIConfig(configId);
      if (!result.success) {
        setError(`连接失败：${result.error || "供应商未返回错误详情"}`);
        return;
      }
      setNotice(`连接成功，模型响应耗时 ${result.latency_ms}ms。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "模型连接测试失败");
    } finally {
      setIsTesting(false);
    }
  }

  function selectProvider(provider: string) {
    const preset = presets.find((item) => item.provider === provider);
    setNewConfig({
      provider,
      baseUrl: preset?.base_url || "",
      apiKey: "",
      modelName: "",
    });
    setDiscoveredModels([]);
    setError(null);
    setNotice(null);
  }

  async function discoverModels() {
    if (!newConfig.apiKey.trim()) {
      setError("请先输入新的 API Key。");
      return;
    }
    if (!newConfig.baseUrl.trim()) {
      setError("请填写供应商 Base URL。");
      return;
    }
    setIsDiscovering(true);
    setError(null);
    setNotice(null);
    try {
      const result = await discoverAIModels({
        provider: newConfig.provider,
        base_url: newConfig.baseUrl.trim(),
        api_key: newConfig.apiKey.trim(),
        timeout_seconds: 20,
      });
      setDiscoveredModels(result.models);
      if (result.models.length > 0) {
        setNewConfig((value) => ({ ...value, modelName: result.models[0].id }));
      }
      setNotice(
        result.models.length
          ? `已读取 ${result.models.length} 个模型，请选择 Hermes 要使用的模型。`
          : `未读取到模型列表${result.error ? `：${result.error}` : "，可以手工填写模型 ID"}。`,
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "读取模型列表失败");
    } finally {
      setIsDiscovering(false);
    }
  }

  async function saveAndSwitch() {
    if (!newConfig.apiKey.trim()) {
      setError("请输入新的 API Key。");
      return;
    }
    if (!newConfig.modelName.trim()) {
      setError("请选择或填写 Hermes 要使用的模型 ID。");
      return;
    }
    setIsSaving(true);
    setError(null);
    setNotice(null);
    try {
      const providerName = providerLabel(newConfig.provider, presets);
      const assignment = await createAIAgentModelConfig("hermes", {
        name: `Hermes / ${providerName} / ${newConfig.modelName.trim()}`,
        provider: newConfig.provider,
        base_url: newConfig.baseUrl.trim() || null,
        api_key: newConfig.apiKey.trim(),
        model_name: newConfig.modelName.trim(),
        temperature: 0,
        max_tokens: 1200,
        timeout_seconds: 60,
        purpose: "general",
        enabled: true,
        is_default: false,
      });
      const refreshedConfigs = await listAIConfigs();
      setConfigs(refreshedConfigs);
      applyCurrentConfig(assignment.config);
      setNewConfig((value) => ({ ...value, apiKey: "", modelName: "" }));
      setDiscoveredModels([]);
      setShowNewConfig(false);
      setNotice(`新 API Key 已加密保存，Hermes 已切换到 ${assignment.config?.model_name || "新模型"}。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "保存 Hermes API Key 与模型失败");
    } finally {
      setIsSaving(false);
    }
  }

  const enabledConfigs = useMemo(() => configs.filter((config) => config.enabled), [configs]);
  const providerOptions = presets.length ? presets.map((preset) => preset.provider) : fallbackProviders;
  const selectedConfig = enabledConfigs.find((config) => config.id === Number(selectedConfigId)) ?? null;
  const activePreset = presets.find((preset) => preset.provider === newConfig.provider);
  const modelOptions = discoveredModels.length
    ? discoveredModels
    : (activePreset?.recommended_models || []).map((id) => ({
        id,
        display_name: id,
        owned_by: null,
        context_length: null,
        source: "recommended",
      }));

  return (
    <section className="overflow-hidden rounded-lg border border-teal-200 bg-white shadow-sm">
      <div className="grid gap-4 border-b border-slate-200 bg-teal-50/60 p-4 lg:grid-cols-[minmax(0,1fr)_minmax(16rem,0.55fr)] lg:items-center">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold text-teal-800">Hermes Agent Runtime</p>
            <span className={`rounded-full px-2 py-1 text-xs font-semibold ${currentConfig ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"}`}>
              {currentConfig ? "已绑定" : "未配置"}
            </span>
          </div>
          <h2 className="mt-1 text-lg font-semibold text-slate-950">API Key 与模型切换</h2>
          <p className="mt-1 text-sm leading-6 text-slate-600">
            这里的选择直接决定“运行 Hermes 诊断”使用哪个 Key 和模型，不影响报价解析的默认模型。
          </p>
        </div>
        <div className="rounded-md border border-white bg-white px-4 py-3 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">当前实际使用</p>
          {currentConfig ? (
            <div className="mt-2 min-w-0">
              <p className="truncate font-semibold text-slate-950">{currentConfig.model_name}</p>
              <p className="mt-1 truncate text-sm text-slate-600">
                {providerLabel(currentConfig.provider, presets)} · {currentConfig.masked_api_key || "未设置 Key"}
              </p>
            </div>
          ) : (
            <p className="mt-2 text-sm font-semibold text-amber-800">请先添加或选择一个配置</p>
          )}
        </div>
      </div>

      <div className="grid gap-3 p-4 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-end">
        <label className="min-w-0">
          <span className="field-label">已有 API Key / 模型</span>
          <select
            className="field-input"
            value={selectedConfigId}
            onChange={(event) => setSelectedConfigId(event.target.value)}
            disabled={isLoading}
          >
            <option value="">{isLoading ? "正在加载配置..." : "请选择配置"}</option>
            {enabledConfigs.map((config) => (
              <option key={config.id} value={config.id}>
                {config.model_name} · {providerLabel(config.provider, presets)} · {config.masked_api_key || "无 Key"}
              </option>
            ))}
          </select>
        </label>
        <div className="grid gap-2 sm:grid-cols-3">
          <button
            className="btn-secondary min-h-10 px-4 py-2"
            type="button"
            onClick={() => void testSelectedConfig()}
            disabled={!selectedConfig || isTesting}
          >
            {isTesting ? "测试中..." : "测试连接"}
          </button>
          <button
            className="btn-primary min-h-10 px-4 py-2"
            type="button"
            onClick={() => void switchConfig()}
            disabled={!selectedConfig || isSwitching || selectedConfig.id === currentConfig?.id}
          >
            {isSwitching ? "切换中..." : selectedConfig?.id === currentConfig?.id ? "当前配置" : "切换使用"}
          </button>
          <button
            className="btn-secondary min-h-10 px-4 py-2"
            type="button"
            aria-expanded={showNewConfig}
            onClick={() => setShowNewConfig((value) => !value)}
          >
            {showNewConfig ? "收起" : "添加新 Key"}
          </button>
        </div>
      </div>

      {showNewConfig ? (
        <div className="border-t border-slate-200 bg-slate-50 p-4">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <label>
              <span className="field-label">供应商</span>
              <select className="field-input" value={newConfig.provider} onChange={(event) => selectProvider(event.target.value)}>
                {providerOptions.map((provider) => (
                  <option key={provider} value={provider}>{providerLabel(provider, presets)}</option>
                ))}
              </select>
            </label>
            <label>
              <span className="field-label">Base URL</span>
              <input
                className="field-input"
                value={newConfig.baseUrl}
                onChange={(event) => setNewConfig((value) => ({ ...value, baseUrl: event.target.value }))}
                placeholder="https://api.example.com/v1"
              />
            </label>
            <label>
              <span className="field-label">新 API Key</span>
              <input
                className="field-input"
                type="password"
                value={newConfig.apiKey}
                onChange={(event) => setNewConfig((value) => ({ ...value, apiKey: event.target.value }))}
                placeholder={activePreset?.api_key_hint || "输入供应商 API Key"}
                autoComplete="new-password"
              />
            </label>
            <div className="flex items-end">
              <button
                className="btn-secondary min-h-10 w-full px-4 py-2"
                type="button"
                onClick={() => void discoverModels()}
                disabled={isDiscovering}
              >
                {isDiscovering ? "读取中..." : "读取模型列表"}
              </button>
            </div>
            <label className="md:col-span-2 xl:col-span-3">
              <span className="field-label">Hermes 模型</span>
              <input
                className="field-input"
                list="hermes-model-options"
                value={newConfig.modelName}
                onChange={(event) => setNewConfig((value) => ({ ...value, modelName: event.target.value }))}
                placeholder="选择模型，或直接填写模型 ID"
              />
              <datalist id="hermes-model-options">
                {modelOptions.map((model) => <option key={model.id} value={model.id}>{model.display_name || model.id}</option>)}
              </datalist>
            </label>
            <div className="flex items-end">
              <button
                className="btn-primary min-h-10 w-full px-4 py-2"
                type="button"
                onClick={() => void saveAndSwitch()}
                disabled={isSaving || !newConfig.apiKey.trim() || !newConfig.modelName.trim()}
              >
                {isSaving ? "保存中..." : "保存并切换"}
              </button>
            </div>
          </div>
          <p className="mt-3 text-xs leading-5 text-slate-500">
            API Key 只会加密保存，页面和接口仅返回掩码。无法读取模型列表时可直接填写供应商提供的模型 ID。
          </p>
        </div>
      ) : null}

      {error ? <div className="border-t border-rose-200 bg-rose-50 px-4 py-3 text-sm font-medium text-rose-700" role="alert">{error}</div> : null}
      {notice ? <div className="border-t border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-800" role="status">{notice}</div> : null}
    </section>
  );
}

function providerLabel(provider: string, presets: AIProviderPreset[]): string {
  return presets.find((preset) => preset.provider === provider)?.label || provider;
}
