import { FormEvent, useEffect, useState } from "react";
import {
  getQuoteWorkbenchConfig,
  updateQuoteWorkbenchConfig,
  type QuoteWorkbenchConfig,
} from "../api/client";

export default function QuoteSettingsPage() {
  const [configText, setConfigText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    void loadConfig();
  }, []);

  async function loadConfig() {
    setError(null);
    setNotice(null);
    try {
      const config = await getQuoteWorkbenchConfig();
      setConfigText(JSON.stringify(config, null, 2));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "报价配置加载失败");
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    setIsSaving(true);
    try {
      const parsed = JSON.parse(configText) as QuoteWorkbenchConfig;
      const saved = await updateQuoteWorkbenchConfig(parsed);
      setConfigText(JSON.stringify(saved, null, 2));
      setNotice("报价工作台配置已保存");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "报价配置保存失败");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
      <header>
        <p className="text-sm font-medium text-blue-800">Quote Settings</p>
        <h1 className="mt-1 text-2xl font-semibold text-slate-950">
          报价工作台后台配置
        </h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
          `/quote` 页面只读取这里的配置；包装类型、地址类型、风险阈值、示例文本和销售话术模板不要写在前端代码里。
        </p>
      </header>

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

      <form className="panel p-5" onSubmit={handleSubmit}>
        <label>
          <span className="field-label">quote_workbench_config JSON</span>
          <textarea
            className="field-input min-h-[560px] font-mono text-sm leading-6"
            value={configText}
            onChange={(event) => setConfigText(event.target.value)}
            spellCheck={false}
          />
        </label>
        <div className="mt-5 flex flex-wrap gap-3">
          <button className="btn-primary" type="submit" disabled={isSaving}>
            {isSaving ? "保存中..." : "保存配置"}
          </button>
          <button className="btn-secondary" type="button" onClick={loadConfig} disabled={isSaving}>
            重新读取
          </button>
        </div>
      </form>
    </div>
  );
}
