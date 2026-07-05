import type { QuoteWorkbenchConfig } from "../api/client";
import type { ParsedQuoteInput } from "../utils/quoteParser";
import ChineseFieldLabel from "./ChineseFieldLabel";

export default function ParsedAddressCard({
  parsed,
  config,
  addressType,
  onAddressTypeChange,
  packagingType,
  onPackagingTypeChange,
  services,
  onServiceChange,
  detentionMinutes,
  onDetentionMinutesChange,
}: {
  parsed: ParsedQuoteInput;
  config: QuoteWorkbenchConfig;
  addressType: string;
  onAddressTypeChange: (value: string) => void;
  packagingType: string;
  onPackagingTypeChange: (value: string) => void;
  services: Record<string, boolean>;
  onServiceChange: (key: string, checked: boolean) => void;
  detentionMinutes: number;
  onDetentionMinutesChange: (value: number) => void;
}) {
  const address = parsed.address;

  return (
    <section className="ai-glass-panel p-5">
      <h2 className="text-xl font-semibold text-white">地址信息</h2>
      <div className="mt-5 grid gap-3 sm:grid-cols-2">
        <Metric label="目的地地址" value={address.address_line || "待确认"} wide />
        <Metric label="目的地城市" value={address.city || "待确认"} />
        <Metric label="目的地省份" value={address.province_name ? `${address.province_name} / ${address.province_code}` : "待确认"} />
        <Metric label="目的地邮编" value={address.postal_code || "待确认"} />
        <Metric label="国家" value={address.country || "待确认"} />
        <Metric label="偏远等级" value="待查询" />
      </div>

      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <label>
          <ChineseFieldLabel label="包装类型" hint="后台配置选项，影响计费托数规则。" />
          <select
            className="ai-select mt-2"
            value={packagingType}
            onChange={(event) => onPackagingTypeChange(event.target.value)}
          >
            {config.packaging_options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label>
          <ChineseFieldLabel label="地址类型" hint="无法自动判断时请人工确认。" />
          <select
            className="ai-select mt-2"
            value={addressType}
            onChange={(event) => onAddressTypeChange(event.target.value)}
          >
            {config.address_type_options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <fieldset className="mt-5 rounded-md border border-white/10 p-3">
        <legend className="px-1 text-sm font-semibold text-slate-100">附加服务确认</legend>
        <div className="mt-2 grid gap-3 sm:grid-cols-3">
          {config.service_options.map((option) => (
            <label
              key={option.value}
              className="flex min-h-11 items-center gap-3 rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-sm font-semibold text-slate-100"
            >
              <input
                className="h-4 w-4 rounded border-cyan-200 bg-slate-950 text-cyan-400 focus:ring-cyan-300"
                type="checkbox"
                checked={Boolean(services[option.value])}
                onChange={(event) => onServiceChange(option.value, event.target.checked)}
              />
              {option.label}
            </label>
          ))}
        </div>
        <label className="mt-3 block">
          <ChineseFieldLabel label="等待时间（分钟）" />
          <input
            className="ai-input mt-2"
            type="number"
            min={0}
            step={1}
            value={detentionMinutes}
            onChange={(event) => onDetentionMinutesChange(Math.max(0, Number(event.target.value) || 0))}
          />
        </label>
      </fieldset>
    </section>
  );
}

function Metric({
  label,
  value,
  wide = false,
}: {
  label: string;
  value: string;
  wide?: boolean;
}) {
  return (
    <div className={`rounded-md border border-white/10 bg-white/[0.04] p-3 ${wide ? "sm:col-span-2" : ""}`}>
      <dt className="text-xs font-medium text-slate-400">{label}</dt>
      <dd className="mt-1 break-words text-sm font-semibold text-white">{value}</dd>
    </div>
  );
}
