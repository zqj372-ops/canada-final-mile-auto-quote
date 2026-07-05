import { FormEvent, useEffect, useState } from "react";
import {
  calculateZoneQuote,
  listWeComBots,
  type AddressType,
  type PackagingType,
  type WeComBotConfigPublic,
  type ZoneQuoteRequest,
  type ZoneQuoteResult,
} from "../api/client";
import ResultCard from "../components/ResultCard";

type StackableValue = "unknown" | "true" | "false";

interface QuoteFormState {
  address_line: string;
  postal_code: string;
  city: string;
  province: string;
  cbm: string;
  weight_kg: string;
  piece_count: string;
  packaging_type: PackagingType;
  longest_side_cm: string;
  explicit_pallet_count: string;
  is_stackable: StackableValue;
  address_type: AddressType;
  requires_liftgate: boolean;
  requires_pallet_jack: boolean;
  requires_appointment: boolean;
  detention_minutes: string;
}

const initialForm: QuoteFormState = {
  address_line: "",
  postal_code: "",
  city: "",
  province: "",
  cbm: "",
  weight_kg: "",
  piece_count: "1",
  packaging_type: "carton",
  longest_side_cm: "",
  explicit_pallet_count: "",
  is_stackable: "unknown",
  address_type: "commercial",
  requires_liftgate: false,
  requires_pallet_jack: false,
  requires_appointment: false,
  detention_minutes: "0",
};

const packagingOptions: Array<{ value: PackagingType; label: string }> = [
  { value: "carton", label: "纸箱 carton" },
  { value: "wooden_crate", label: "木箱 wooden_crate" },
  { value: "pallet", label: "托盘 pallet" },
  { value: "woven_bag", label: "编织袋 woven_bag" },
  { value: "flexible_packaging", label: "软包装 flexible_packaging" },
  { value: "unknown", label: "未知 unknown" },
];

const addressTypeOptions: Array<{ value: AddressType; label: string }> = [
  { value: "commercial", label: "商业 commercial" },
  { value: "residential", label: "住宅 residential" },
  { value: "private", label: "私人 private" },
  { value: "rural_residential", label: "偏远住宅 rural_residential" },
];

export default function QuotePage() {
  const [form, setForm] = useState<QuoteFormState>(initialForm);
  const [result, setResult] = useState<ZoneQuoteResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [wecomBots, setWecomBots] = useState<WeComBotConfigPublic[]>([]);
  const [notifyWecom, setNotifyWecom] = useState(false);
  const [selectedWecomBotId, setSelectedWecomBotId] = useState("");

  useEffect(() => {
    void loadWecomBots();
  }, []);

  async function loadWecomBots() {
    try {
      setWecomBots(await listWeComBots());
    } catch {
      setWecomBots([]);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    try {
      const payload = buildPayload(form);
      setIsSubmitting(true);
      const quoteResult = await calculateZoneQuote(
        notifyWecom
          ? {
              quote: payload,
              notify_wecom: true,
              wecom_bot_id: selectedWecomBotId ? Number(selectedWecomBotId) : null,
            }
          : payload,
      );
      setResult(quoteResult);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "报价请求失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  function update<K extends keyof QuoteFormState>(
    key: K,
    value: QuoteFormState[K],
  ) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
      <header>
        <p className="text-sm font-medium text-blue-800">Zone Quote</p>
        <h1 className="mt-1 text-2xl font-semibold text-slate-950">
          加拿大尾程派送报价
        </h1>
      </header>

      <form className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]" onSubmit={handleSubmit}>
        <section className="panel p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="section-title">报价输入</h2>
              <p className="mt-1 text-sm text-slate-600">
                前端只提交货物与地址信息，金额全部由后端 Quote Engine 返回。
              </p>
            </div>
            <button
              className="btn-secondary shrink-0"
              type="button"
              onClick={() => {
                setForm(initialForm);
                setResult(null);
                setError(null);
              }}
            >
              清空
            </button>
          </div>

          {error && (
            <div
              className="mt-4 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900"
              role="alert"
            >
              {error}
            </div>
          )}

          <fieldset className="mt-5 border-t border-slate-200 pt-5">
            <legend className="text-sm font-semibold text-slate-950">地址信息</legend>
            <div className="mt-3 grid gap-4 md:grid-cols-2">
              <TextField
                label="address_line"
                value={form.address_line}
                onChange={(value) => update("address_line", value)}
                placeholder="收货地址"
              />
              <TextField
                label="postal_code *"
                value={form.postal_code}
                onChange={(value) => update("postal_code", value)}
                placeholder="A1A 1A1"
                required
              />
              <TextField
                label="city"
                value={form.city}
                onChange={(value) => update("city", value)}
                placeholder="Richmond"
              />
              <TextField
                label="province"
                value={form.province}
                onChange={(value) => update("province", value)}
                placeholder="BC / ON"
              />
            </div>
          </fieldset>

          <fieldset className="mt-6 border-t border-slate-200 pt-5">
            <legend className="text-sm font-semibold text-slate-950">货物信息</legend>
            <div className="mt-3 grid gap-4 md:grid-cols-2">
              <NumberField
                label="cbm *"
                value={form.cbm}
                onChange={(value) => update("cbm", value)}
                min="0"
                step="0.01"
                required
              />
              <NumberField
                label="weight_kg *"
                value={form.weight_kg}
                onChange={(value) => update("weight_kg", value)}
                min="0"
                step="0.01"
                required
              />
              <NumberField
                label="piece_count *"
                value={form.piece_count}
                onChange={(value) => update("piece_count", value)}
                min="1"
                step="1"
                required
              />
              <label>
                <span className="field-label">packaging_type</span>
                <select
                  className="field-input"
                  value={form.packaging_type}
                  onChange={(event) =>
                    update("packaging_type", event.target.value as PackagingType)
                  }
                >
                  {packagingOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <NumberField
                label="longest_side_cm"
                value={form.longest_side_cm}
                onChange={(value) => update("longest_side_cm", value)}
                min="0"
                step="0.1"
              />
              <NumberField
                label="explicit_pallet_count"
                value={form.explicit_pallet_count}
                onChange={(value) => update("explicit_pallet_count", value)}
                min="1"
                step="1"
              />
              <label>
                <span className="field-label">is_stackable</span>
                <select
                  className="field-input"
                  value={form.is_stackable}
                  onChange={(event) =>
                    update("is_stackable", event.target.value as StackableValue)
                  }
                >
                  <option value="unknown">未知</option>
                  <option value="true">是</option>
                  <option value="false">否</option>
                </select>
              </label>
              <label>
                <span className="field-label">address_type</span>
                <select
                  className="field-input"
                  value={form.address_type}
                  onChange={(event) =>
                    update("address_type", event.target.value as AddressType)
                  }
                >
                  {addressTypeOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </fieldset>

          <fieldset className="mt-6 border-t border-slate-200 pt-5">
            <legend className="text-sm font-semibold text-slate-950">服务要求</legend>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <CheckboxField
                label="requires_liftgate"
                checked={form.requires_liftgate}
                onChange={(checked) => update("requires_liftgate", checked)}
              />
              <CheckboxField
                label="requires_pallet_jack"
                checked={form.requires_pallet_jack}
                onChange={(checked) => update("requires_pallet_jack", checked)}
              />
              <CheckboxField
                label="requires_appointment"
                checked={form.requires_appointment}
                onChange={(checked) => update("requires_appointment", checked)}
              />
              <NumberField
                label="detention_minutes"
                value={form.detention_minutes}
                onChange={(value) => update("detention_minutes", value)}
                min="0"
                step="1"
              />
            </div>
          </fieldset>

          <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-center">
            <button className="btn-primary" type="submit" disabled={isSubmitting}>
              {isSubmitting ? "报价中..." : "提交报价"}
            </button>
            <p className="text-sm text-slate-600">
              命中失败会进入 manual_required，不会在前端估价。
            </p>
          </div>

          <fieldset className="mt-6 border-t border-slate-200 pt-5">
            <legend className="text-sm font-semibold text-slate-950">企业微信推送</legend>
            <div className="mt-3 grid gap-3">
              <CheckboxField
                label="成功报价后推送企业微信"
                checked={notifyWecom}
                onChange={setNotifyWecom}
              />
              <label>
                <span className="field-label">wecom_bot_id</span>
                <select
                  className="field-input"
                  value={selectedWecomBotId}
                  onChange={(event) => setSelectedWecomBotId(event.target.value)}
                  disabled={!notifyWecom}
                >
                  <option value="">使用 quote_success/default 机器人</option>
                  {wecomBots.map((bot) => (
                    <option key={bot.id} value={bot.id}>
                      {bot.name} / {bot.purpose}
                      {bot.is_default ? " / 默认" : ""}
                    </option>
                  ))}
                </select>
                <p className="field-hint">
                  manual_required 会自动进入人工确认池，并尝试推送人工确认通知。
                </p>
              </label>
            </div>
          </fieldset>
        </section>

        <div>
          {result ? (
            <ResultCard result={result} />
          ) : (
            <section className="panel flex min-h-72 items-center justify-center p-6 text-center">
              <div>
                <h2 className="text-lg font-semibold text-slate-950">等待报价结果</h2>
                <p className="mt-2 max-w-md text-sm leading-6 text-slate-600">
                  提交后会展示 Zone、计费托数、基础价、燃油、附加费、风险标签和销售备注。
                </p>
              </div>
            </section>
          )}
        </div>
      </form>
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
  required = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  min?: string;
  step?: string;
  required?: boolean;
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

function buildPayload(form: QuoteFormState): ZoneQuoteRequest {
  return {
    address_line: optionalText(form.address_line),
    postal_code: form.postal_code.trim(),
    city: optionalText(form.city),
    province: optionalText(form.province),
    cbm: requiredNumber(form.cbm, "cbm"),
    weight_kg: requiredNumber(form.weight_kg, "weight_kg"),
    piece_count: requiredInteger(form.piece_count, "piece_count", 1),
    packaging_type: form.packaging_type,
    longest_side_cm: optionalNumber(form.longest_side_cm),
    explicit_pallet_count: optionalInteger(form.explicit_pallet_count, 1),
    is_stackable:
      form.is_stackable === "unknown" ? null : form.is_stackable === "true",
    address_type: form.address_type,
    requires_liftgate: form.requires_liftgate,
    requires_pallet_jack: form.requires_pallet_jack,
    requires_appointment: form.requires_appointment,
    detention_minutes: optionalInteger(form.detention_minutes) ?? 0,
  };
}

function optionalText(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function optionalNumber(value: string): number | null {
  if (!value.trim()) {
    return null;
  }
  return requiredNumber(value, "number");
}

function optionalInteger(value: string, min = 0): number | null {
  if (!value.trim()) {
    return null;
  }
  return requiredInteger(value, "integer", min);
}

function requiredNumber(value: string, fieldName: string): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) {
    throw new Error(`${fieldName} 必须是大于等于 0 的数字`);
  }
  return parsed;
}

function requiredInteger(value: string, fieldName: string, min = 0): number {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < min) {
    throw new Error(`${fieldName} 必须是大于等于 ${min} 的整数`);
  }
  return parsed;
}
