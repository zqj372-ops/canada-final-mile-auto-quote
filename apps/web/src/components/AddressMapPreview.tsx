import type { ParsedQuoteInput } from "../utils/quoteParser";
import { getApiBaseUrl } from "../api/client";

export default function AddressMapPreview({ parsed }: { parsed: ParsedQuoteInput }) {
  const query = buildMapQuery(parsed);
  const embedUrl = query
    ? `${getApiBaseUrl()}/maps/embed?query=${encodeURIComponent(query)}`
    : "";

  return (
    <div className="mt-3 rounded-lg border border-white/10 bg-white/[0.04] p-3 sm:p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-white">Google 地图预览</h3>
          <p className="mt-1 text-sm leading-6 text-slate-400">
            自动按解析地址搜索；仅用于核对地址情况，不影响系统报价金额。
          </p>
        </div>
        {query && (
          <a
            className="shrink-0 rounded-md border border-cyan-300/40 bg-cyan-300/10 px-3 py-2 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-300/20"
            href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`}
            target="_blank"
            rel="noreferrer"
          >
            打开地图
          </a>
        )}
      </div>

      {query ? (
        <div className="mt-4 overflow-hidden rounded-md border border-white/10 bg-slate-950/40">
          <iframe
            className="block h-[clamp(18rem,28vw,26rem)] w-full"
            title={`Google 地图：${query}`}
            src={embedUrl}
            loading="lazy"
            referrerPolicy="no-referrer-when-downgrade"
          />
        </div>
      ) : (
        <div className="mt-2 grid h-32 place-items-center rounded-md border border-dashed border-white/15 bg-white/[0.03] px-3 text-center text-sm font-semibold text-slate-400">
          地址解析完成后自动显示地图
        </div>
      )}
    </div>
  );
}

function buildMapQuery(parsed: ParsedQuoteInput): string {
  const address = parsed.address;
  return [
    address.address_line,
    address.city,
    address.province_name || address.province_code,
    address.postal_code,
    address.country || "Canada",
  ]
    .map((part) => String(part || "").trim())
    .filter(Boolean)
    .join(", ");
}
