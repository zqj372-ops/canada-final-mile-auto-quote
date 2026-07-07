import type { ChangeEvent } from "react";
import type { QuoteWorkbenchConfig } from "../api/client";
import ChineseFieldLabel from "./ChineseFieldLabel";

export default function AiQuoteInputPanel({
  config,
  value,
  statusLabel,
  isQuoting,
  onChange,
  onSubmit,
  onClear,
  onImportText,
}: {
  config: QuoteWorkbenchConfig;
  value: string;
  statusLabel: string;
  isQuoting: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onClear: () => void;
  onImportText: (value: string) => void;
}) {
  const formatHints = config.format_hints ?? [];
  const inputTitle = config.input_title || "AI 智能报价输入";
  const inputLabel = config.input_label || "请直接粘贴报价信息";
  const primaryButtonLabel = config.primary_button_label || "生成 AI 报价";
  const clearButtonLabel = config.clear_button_label || "清空内容";
  const importButtonLabel = config.import_button_label || "导入 Excel";
  const sampleInput =
    config.sample_input ||
    "170*140*87 409.8kg\n205 Main Street\nNew Norway Alberta Canada\nT0B 3L0";

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    const lowerName = file.name.toLowerCase();
    if (!lowerName.endsWith(".txt") && !lowerName.endsWith(".csv")) {
      onImportText("");
      return;
    }
    onImportText(await file.text());
  }

  return (
    <section className="ai-glass-panel min-w-0 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase text-cyan-200">
            AI 报价输入
          </p>
          <h2 className="mt-1 text-lg font-semibold text-white">{inputTitle}</h2>
        </div>
        <span className="rounded-full border border-cyan-300/40 bg-cyan-300/10 px-2.5 py-1 text-xs font-semibold text-cyan-100">
          {statusLabel}
        </span>
      </div>

      <label className="mt-3 block">
        <ChineseFieldLabel
          label={inputLabel}
          hint="尺寸默认 cm，重量默认 kg；原始信息只用于字段识别。"
        />
        <textarea
          className="ai-textarea mt-2 min-h-64"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={sampleInput}
        />
      </label>

      <details className="ai-format-details mt-2 rounded-md border border-white/10 bg-white/[0.04] p-2">
        <summary className="cursor-pointer text-xs font-semibold text-cyan-100">
          支持格式
        </summary>
        <div className="mt-2 grid gap-1 text-xs leading-5 text-slate-300">
          {formatHints.map((hint) => (
            <span key={hint}>{hint}</span>
          ))}
        </div>
      </details>

      <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_auto_auto]">
        <button className="ai-primary-button" type="button" onClick={onSubmit} disabled={isQuoting}>
          {isQuoting ? "报价中" : primaryButtonLabel}
        </button>
        <button className="ai-secondary-button" type="button" onClick={onClear} disabled={isQuoting}>
          {clearButtonLabel}
        </button>
        <label className="ai-secondary-button cursor-pointer">
          {importButtonLabel}
          <input
            className="sr-only"
            type="file"
            accept=".txt,.csv,.xlsx,.xls"
            onChange={handleFileChange}
          />
        </label>
      </div>
    </section>
  );
}
