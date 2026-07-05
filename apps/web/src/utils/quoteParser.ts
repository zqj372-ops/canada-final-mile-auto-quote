import type { ProvinceAlias, QuoteWorkbenchConfig } from "../api/client";

export interface ParsedCargoItem {
  id: number;
  length_cm: number;
  width_cm: number;
  height_cm: number;
  weight_kg: number;
  cbm: number;
}

export interface ParsedAddress {
  address_line: string | null;
  city: string | null;
  province_code: string | null;
  province_name: string | null;
  postal_code: string | null;
  country: string;
}

export interface ParsedQuoteInput {
  cargo_items: ParsedCargoItem[];
  piece_count: number;
  total_cbm: number;
  total_weight_kg: number;
  density_kg_per_cbm: number | null;
  max_dimensions_cm: [number, number, number] | null;
  longest_side_cm: number | null;
  heaviest_piece_kg: number | null;
  address: ParsedAddress;
  missing_fields: string[];
  risk_hints: string[];
  confidence: number;
}

export function parseQuoteInput(rawInput: string, config: QuoteWorkbenchConfig): ParsedQuoteInput {
  const lines = rawInput
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const cargoRegex = buildCargoRegex(config);
  const spaceCargoRegex = buildSpaceCargoRegex(config);
  const cargoItems: ParsedCargoItem[] = [];
  const addressLines: string[] = [];

  for (const line of lines) {
    const match = line.match(cargoRegex) ?? line.match(spaceCargoRegex);
    if (match) {
      const [, length, width, height, weight] = match;
      const item = toCargoItem(cargoItems.length + 1, length, width, height, weight);
      cargoItems.push(item);
    } else {
      addressLines.push(line);
    }
  }

  const address = parseAddress(addressLines, config);
  const totalCbm = round3(cargoItems.reduce((sum, item) => sum + item.cbm, 0));
  const totalWeight = round1(cargoItems.reduce((sum, item) => sum + item.weight_kg, 0));
  const density = totalCbm > 0 ? round1(totalWeight / totalCbm) : null;
  const maxItem = cargoItems.reduce<ParsedCargoItem | null>(
    (current, item) => (!current || item.cbm > current.cbm ? item : current),
    null,
  );
  const longestSide = cargoItems.length
    ? Math.max(...cargoItems.flatMap((item) => [item.length_cm, item.width_cm, item.height_cm]))
    : null;
  const heaviestPiece = cargoItems.length
    ? Math.max(...cargoItems.map((item) => item.weight_kg))
    : null;

  const missingFields = buildMissingFields(cargoItems, address);
  const riskHints = buildRiskHints({
    cargoItems,
    address,
    density,
    longestSide,
    heaviestPiece,
    config,
  });

  return {
    cargo_items: cargoItems,
    piece_count: cargoItems.length,
    total_cbm: totalCbm,
    total_weight_kg: totalWeight,
    density_kg_per_cbm: density,
    max_dimensions_cm: maxItem
      ? [maxItem.length_cm, maxItem.width_cm, maxItem.height_cm]
      : null,
    longest_side_cm: longestSide,
    heaviest_piece_kg: heaviestPiece,
    address,
    missing_fields: missingFields,
    risk_hints: riskHints,
    confidence: calculateConfidence(cargoItems, address, density),
  };
}

function toCargoItem(
  id: number,
  length: string,
  width: string,
  height: string,
  weight: string,
): ParsedCargoItem {
  const lengthCm = Number(length);
  const widthCm = Number(width);
  const heightCm = Number(height);
  const weightKg = Number(weight);
  return {
    id,
    length_cm: lengthCm,
    width_cm: widthCm,
    height_cm: heightCm,
    weight_kg: weightKg,
    cbm: (lengthCm * widthCm * heightCm) / 1_000_000,
  };
}

function buildCargoRegex(config: QuoteWorkbenchConfig): RegExp {
  const decimal = "(\\d+(?:\\.\\d+)?)";
  const separators = config.parser.dimension_separators.map(escapeRegex).join("|");
  const units = config.parser.weight_units.map(escapeRegex).join("|");
  return new RegExp(
    `^\\s*${decimal}\\s*(?:${separators})\\s*${decimal}\\s*(?:${separators})\\s*${decimal}(?:\\s*(?:cm|厘米))?\\s+${decimal}\\s*(?:${units})\\b`,
    "i",
  );
}

function buildSpaceCargoRegex(config: QuoteWorkbenchConfig): RegExp {
  if (!config.parser.allow_space_dimension_separator) {
    return /a^/;
  }
  const decimal = "(\\d+(?:\\.\\d+)?)";
  const units = config.parser.weight_units.map(escapeRegex).join("|");
  return new RegExp(`^\\s*${decimal}\\s+${decimal}\\s+${decimal}\\s+${decimal}\\s*(?:${units})\\b`, "i");
}

function parseAddress(lines: string[], config: QuoteWorkbenchConfig): ParsedAddress {
  const postalRegex = safeRegex(config.parser.postal_code_pattern, "i");
  let postalCode: string | null = null;
  let addressLine: string | null = null;
  let city: string | null = null;
  let province: ProvinceAlias | null = null;
  const cleanedLines: string[] = [];

  for (const line of lines) {
    const postalMatch = postalRegex ? line.match(postalRegex) : null;
    if (!postalCode && postalMatch?.[0]) {
      postalCode = normalizeCanadianPostalCode(postalMatch[0]);
    }
    const withoutPostal = postalMatch?.[0]
      ? line.replace(postalMatch[0], "").replace(/[,\s]+$/g, "").trim()
      : line;
    if (withoutPostal) {
      cleanedLines.push(withoutPostal);
    }
  }

  for (const line of cleanedLines) {
    const foundProvince = findProvince(line, config.provinces);
    if (foundProvince) {
      province = province ?? foundProvince.province;
      const cityCandidate = removeKnownAddressTokens(
        line,
        foundProvince.alias,
        config.parser.country_aliases,
      );
      if (cityCandidate && !city) {
        city = cityCandidate;
      }
      continue;
    }

    if (!addressLine && /^\d+[\w\s#.-]+/.test(line)) {
      addressLine = line;
      continue;
    }

    if (!city && !containsCountryAlias(line, config.parser.country_aliases)) {
      city = line.replace(/,+$/g, "").trim() || null;
    }
  }

  if (!addressLine) {
    addressLine = cleanedLines.find((line) => /^\d+/.test(line)) ?? null;
  }

  return {
    address_line: addressLine,
    city,
    province_code: province?.code ?? null,
    province_name: province?.name ?? null,
    postal_code: postalCode,
    country: config.parser.default_country,
  };
}

function findProvince(
  line: string,
  provinces: ProvinceAlias[],
): { province: ProvinceAlias; alias: string } | null {
  for (const province of provinces) {
    const aliases = [...province.aliases].sort((a, b) => b.length - a.length);
    for (const alias of aliases) {
      if (containsToken(line, alias)) {
        return { province, alias };
      }
    }
  }
  return null;
}

function removeKnownAddressTokens(
  line: string,
  provinceAlias: string,
  countryAliases: string[],
): string | null {
  let output = line;
  output = output.replace(new RegExp(escapeRegex(provinceAlias), "i"), " ");
  for (const countryAlias of countryAliases) {
    output = output.replace(new RegExp(escapeRegex(countryAlias), "ig"), " ");
  }
  output = output.replace(/[,，]+/g, " ").replace(/\s+/g, " ").trim();
  return output || null;
}

function containsCountryAlias(line: string, aliases: string[]): boolean {
  return aliases.some((alias) => containsToken(line, alias));
}

function containsToken(source: string, token: string): boolean {
  const escaped = escapeRegex(token.trim());
  if (!escaped) {
    return false;
  }
  if (/^[a-z0-9.\s]+$/i.test(token)) {
    return new RegExp(`(^|[^a-z0-9])${escaped}([^a-z0-9]|$)`, "i").test(source);
  }
  return source.toLowerCase().includes(token.toLowerCase());
}

function normalizeCanadianPostalCode(value: string): string {
  const compact = value.toUpperCase().replace(/[^A-Z0-9]/g, "");
  return compact.length === 6 ? `${compact.slice(0, 3)} ${compact.slice(3)}` : value.toUpperCase();
}

function buildMissingFields(cargoItems: ParsedCargoItem[], address: ParsedAddress): string[] {
  const missing: string[] = [];
  if (!cargoItems.length) {
    missing.push("货物尺寸重量");
  }
  if (!address.postal_code) {
    missing.push("目的地邮编");
  }
  if (!address.city) {
    missing.push("目的地城市");
  }
  if (!address.province_code) {
    missing.push("目的地省份");
  }
  if (!address.address_line) {
    missing.push("目的地地址");
  }
  return missing;
}

function buildRiskHints({
  cargoItems,
  address,
  density,
  longestSide,
  heaviestPiece,
  config,
}: {
  cargoItems: ParsedCargoItem[];
  address: ParsedAddress;
  density: number | null;
  longestSide: number | null;
  heaviestPiece: number | null;
  config: QuoteWorkbenchConfig;
}): string[] {
  const risks: string[] = [];
  if (!cargoItems.length) {
    return risks;
  }
  if (density !== null && density >= config.risks.dense_density_kg_per_cbm) {
    risks.push("重货偏高密度，不是泡货。");
  }
  if (density !== null && density < config.risks.light_density_kg_per_cbm) {
    risks.push("低密度泡货，计费托数可能由体积拉高。");
  }
  if (longestSide !== null && longestSide >= config.risks.oversized_longest_side_cm) {
    risks.push("最大单件可能超尺寸，请确认供应商是否加收超长超重费。");
  }
  if (heaviestPiece !== null && heaviestPiece >= config.risks.heavy_single_piece_kg) {
    risks.push("存在较重单件，请确认卸货设备、dock 或尾板需求。");
  }
  risks.push("请确认是否有叉车 / dock / 尾板需求。");
  risks.push("请确认派送地址是否商业地址；如为住宅，可能产生住宅、尾板、预约等附加费。");

  if (address.city && !isCoreCity(address.city, config.risks.core_city_names)) {
    risks.push("目的地可能属于偏远地区 / 非核心城市派送，需要匹配邮编分区或人工复核。");
  }
  return Array.from(new Set(risks));
}

function isCoreCity(city: string, coreCities: string[]): boolean {
  return coreCities.some((coreCity) => coreCity.trim().toLowerCase() === city.trim().toLowerCase());
}

function calculateConfidence(
  cargoItems: ParsedCargoItem[],
  address: ParsedAddress,
  density: number | null,
): number {
  let score = 0;
  if (cargoItems.length) {
    score += 35;
  }
  if (density !== null) {
    score += 10;
  }
  if (address.postal_code) {
    score += 20;
  }
  if (address.province_code) {
    score += 15;
  }
  if (address.city) {
    score += 10;
  }
  if (address.address_line) {
    score += 10;
  }
  return Math.min(100, score);
}

function safeRegex(pattern: string, flags: string): RegExp | null {
  try {
    return new RegExp(pattern, flags);
  } catch {
    return null;
  }
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function round1(value: number): number {
  return Math.round(value * 10) / 10;
}

function round3(value: number): number {
  return Math.round(value * 1000) / 1000;
}
