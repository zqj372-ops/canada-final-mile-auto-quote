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
    <section className="ai-glass-panel flex h-full flex-col p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase text-cyan-200">
            AI 报价输入
          </p>
          <h2 className="mt-2 text-xl font-semibold text-white">{config.input_title}</h2>
        </div>
        <span className="rounded-full border border-cyan-300/40 bg-cyan-300/10 px-3 py-1 text-xs font-semibold text-cyan-100">
          {statusLabel}
        </span>
      </div>

      <label className="mt-5 flex min-h-0 flex-1 flex-col">
        <ChineseFieldLabel
          label={config.input_label}
          hint="尺寸默认 cm，重量默认 kg；原始信息只用于字段识别。"
        />
        <textarea
          className="ai-textarea mt-3 min-h-80 flex-1"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={config.sample_input}
        />
      </label>

      <div className="mt-4 rounded-md border border-white/10 bg-white/[0.04] p-3">
        <p className="text-xs font-semibold text-cyan-100">支持格式</p>
        <div className="mt-2 grid gap-1 text-xs leading-5 text-slate-300">
          {config.format_hints.map((hint) => (
            <span key={hint}>{hint}</span>
          ))}
        </div>
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-[1fr_auto_auto]">
        <button className="ai-primary-button" type="button" onClick={onSubmit} disabled={isQuoting}>
          {isQuoting ? "报价中" : config.primary_button_label}
        </button>
        <button className="ai-secondary-button" type="button" onClick={onClear} disabled={isQuoting}>
          {config.clear_button_label}
        </button>
        <label className="ai-secondary-button cursor-pointer">
          {config.import_button_label}
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
