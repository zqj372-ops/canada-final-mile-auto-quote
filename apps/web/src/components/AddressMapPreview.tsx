import { useEffect, useMemo, useState } from "react";

import { getApiBaseUrl, verifyLocalAddress, type LocalAddressValidation } from "../api/client";
import type { ParsedQuoteInput } from "../utils/quoteParser";

export default function AddressMapPreview({
  parsed,
  mapMode = "collapsible",
}: {
  parsed: ParsedQuoteInput;
  mapMode?: "collapsible" | "expanded";
}) {
  const query = useMemo(() => buildMapQuery(parsed), [parsed]);
  const embedUrl = query
    ? `${getApiBaseUrl()}/maps/embed?query=${encodeURIComponent(query)}`
    : "";
  const [validation, setValidation] = useState<LocalAddressValidation | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  useEffect(() => {
    const address = parsed.address;
    const hasAddressBasis = Boolean(address.postal_code || address.city || address.province_code || address.address_line);
    if (!hasAddressBasis) {
      setValidation(null);
      setValidationError(null);
      return;
    }

    let cancelled = false;
    setValidationError(null);
    void verifyLocalAddress({
      address_line: address.address_line,
      postal_code: address.postal_code,
      city: address.city,
      province: address.province_code || address.province_name,
    })
      .then((nextValidation) => {
        if (!cancelled) {
          setValidation(nextValidation);
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setValidation(null);
          setValidationError(error instanceof Error ? error.message : "本地地址验证失败");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [
    parsed.address.address_line,
    parsed.address.city,
    parsed.address.postal_code,
    parsed.address.province_code,
    parsed.address.province_name,
  ]);

  return (
    <div className={`address-verification mt-3 ${mapMode === "expanded" ? "address-verification-expanded" : ""}`}>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-slate-900">地址核验</h3>
          <p className="mt-1 text-xs leading-5 text-slate-500">本地邮编库为主，地图仅用于人工复核。</p>
        </div>
        {query ? (
          <a
            className="shrink-0 text-xs font-semibold text-teal-700 transition hover:text-teal-900"
            href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`}
            target="_blank"
            rel="noreferrer"
          >
            在 Google 地图打开 ↗
          </a>
        ) : null}
      </div>

      <LocalValidationSummary validation={validation} error={validationError} />

      {query && mapMode === "expanded" ? (
        <MapFrame embedUrl={embedUrl} query={query} />
      ) : query ? (
        <details className="address-map-disclosure mt-3">
          <summary>展开地图预览</summary>
          <MapFrame embedUrl={embedUrl} query={query} />
        </details>
      ) : null}
    </div>
  );
}

function MapFrame({ embedUrl, query }: { embedUrl: string; query: string }) {
  return (
    <div className="address-map-frame mt-3 overflow-hidden rounded-md border border-slate-200 bg-slate-100">
      <iframe
        className="block h-[clamp(14rem,22vw,19rem)] w-full"
        title={`Google 地图：${query}`}
        src={embedUrl}
        loading="lazy"
        referrerPolicy="no-referrer-when-downgrade"
      />
    </div>
  );
}

function LocalValidationSummary({
  validation,
  error,
}: {
  validation: LocalAddressValidation | null;
  error: string | null;
}) {
  if (error) {
    return (
      <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm leading-6 text-amber-700">
        本地邮编验证暂时失败：{error}
      </div>
    );
  }
  if (!validation) {
    return (
      <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-3 text-sm leading-6 text-slate-500">
        地址解析完成后自动读取本地邮编库验证城市、省份和邮编。
      </div>
    );
  }

  const tone = validation.matched
    ? validation.status === "corrected_by_postal_lookup"
      ? "border-amber-200 bg-amber-50 text-amber-700"
      : "border-emerald-200 bg-emerald-50 text-emerald-700"
    : "border-amber-200 bg-amber-50 text-amber-700";
  const statusLabel = formatValidationStatus(validation.status);
  const canonical = [
    validation.preferred_city || validation.input_city,
    validation.province,
    validation.postal_code,
  ].filter(Boolean).join(", ");

  return (
    <div className={`mt-3 rounded-md border p-3 ${tone}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold">本地邮编库验证：{statusLabel}</p>
        <span className="rounded-full border border-current/30 px-2 py-0.5 text-xs font-semibold">
          {validation.confidence}%
        </span>
      </div>
      <p className="mt-2 text-sm leading-6">{validation.note_zh}</p>
      {canonical && (
        <p className="mt-2 text-xs leading-5 opacity-90">
          规范地址字段：{canonical}
        </p>
      )}
      {(validation.corrected_city || validation.corrected_province) && (
        <p className="mt-1 text-xs leading-5 opacity-90">
          建议修正：{validation.corrected_city ? `城市改为 ${validation.corrected_city}` : ""}
          {validation.corrected_city && validation.corrected_province ? "，" : ""}
          {validation.corrected_province ? `省份改为 ${validation.corrected_province}` : ""}
        </p>
      )}
    </div>
  );
}

function formatValidationStatus(status: LocalAddressValidation["status"]): string {
  const labels: Record<LocalAddressValidation["status"], string> = {
    missing_postal_code: "缺少邮编",
    invalid_postal_code: "邮编格式错误",
    postal_not_found: "本地库未命中",
    postal_fsa_suggested: "FSA 城市建议",
    postal_verified: "邮编已命中",
    verified: "城市省份一致",
    corrected_by_postal_lookup: "已按邮编库建议纠正",
  };
  return labels[status] || status;
}

function buildMapQuery(parsed: ParsedQuoteInput): string {
  const address = parsed.address;
  const hasAddressBasis = Boolean(
    address.address_line || address.city || address.province_name || address.province_code || address.postal_code,
  );
  if (!hasAddressBasis) {
    return "";
  }
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
