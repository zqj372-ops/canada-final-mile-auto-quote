import type { ProvinceAlias, QuoteWorkbenchConfig } from "../api/client";

export interface ParsedCargoItem {
  id: number;
  quantity: number;
  length_cm: number;
  width_cm: number;
  height_cm: number;
  weight_kg: number | null;
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
  const cargoItems: ParsedCargoItem[] = [];
  const addressLines: string[] = [];
  const allowNumericTable = hasDimensionWeightTable(rawInput);

  for (const line of lines) {
    const items = parseCargoLineItems(line, cargoItems.length + 1, config, allowNumericTable);
    if (items.length) {
      cargoItems.push(...items);
    } else {
      addressLines.push(line);
    }
  }

  const aggregate = parseAggregateTotals(rawInput);
  if (cargoItems.length === 1 && aggregate.piece_count && aggregate.piece_count > cargoItems[0].quantity) {
    cargoItems[0] = { ...cargoItems[0], quantity: aggregate.piece_count };
  }
  const address = parseAddress(addressLines, config);
  const cargoCbm = round3(cargoItems.reduce((sum, item) => sum + item.cbm * item.quantity, 0));
  const cargoWeight = round1(cargoItems.reduce((sum, item) => sum + (item.weight_kg ?? 0) * item.quantity, 0));
  const cargoPieceCount = cargoItems.reduce((sum, item) => sum + item.quantity, 0);
  const totalCbm = aggregate.cbm || cargoCbm || 0;
  const totalWeight = aggregate.weight_kg || cargoWeight || 0;
  const pieceCount =
    aggregate.piece_count && aggregate.piece_count >= cargoPieceCount
      ? aggregate.piece_count
      : cargoPieceCount || aggregate.piece_count || 0;
  const density = totalCbm > 0 ? round1(totalWeight / totalCbm) : null;
  const maxItem = cargoItems.reduce<ParsedCargoItem | null>(
    (current, item) => (!current || item.cbm > current.cbm ? item : current),
    null,
  );
  const longestSide = cargoItems.length
    ? Math.max(...cargoItems.flatMap((item) => [item.length_cm, item.width_cm, item.height_cm]))
    : null;
  const knownWeights = cargoItems
    .map((item) => item.weight_kg)
    .filter((value): value is number => value !== null && Number.isFinite(value) && value > 0);
  const heaviestPiece = knownWeights.length
    ? Math.max(...knownWeights)
    : null;

  const missingFields = buildMissingFields({ totalCbm, totalWeight, pieceCount, address });
  const riskHints = buildRiskHints({
    cargoItems,
    pieceCount,
    totalCbm,
    totalWeight,
    address,
    density,
    longestSide,
    heaviestPiece,
    config,
  });

  return {
    cargo_items: cargoItems,
    piece_count: pieceCount,
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

function parseAggregateTotals(rawInput: string): {
  piece_count: number | null;
  cbm: number | null;
  weight_kg: number | null;
} {
  const pieceCount = findExplicitPieceCount(rawInput);
  const cbmMatch = rawInput.match(/(\d+(?:\.\d+)?)\s*(?:cbm|m3|m³|方|立方)/i);
  const explicitWeightMatch =
    rawInput.match(/(?:合计|总计|总重量|总重|重量合计|一共|共)[^\n\r]{0,32}?(\d+(?:\.\d+)?)\s*(kg|kgs|公斤|千克|lb|lbs|pounds?|磅)/i) ??
    rawInput.match(/(\d+(?:\.\d+)?)\s*(kg|kgs|公斤|千克|lb|lbs|pounds?|磅)\s*(?:total|合计|总重)/i);
  const weightMatches = Array.from(
    rawInput.matchAll(/(\d+(?:\.\d+)?)\s*(kg|kgs|公斤|千克|lb|lbs|pounds?|磅)/gi),
  );
  const weightMatch = weightMatches.length ? weightMatches[weightMatches.length - 1] : undefined;
  const hasDimensionSpecs = /\d+(?:\.\d+)?\s*(?:mm|cm|厘米|m|米|inches|inch|in|"|ft|feet|英尺|英寸)?\s*(?:\*|x|X|×|by)\s*\d+(?:\.\d+)?/i.test(rawInput);
  const fallbackAggregateWeight = !hasDimensionSpecs && pieceCount && cbmMatch ? weightMatch : undefined;
  const selectedWeight = explicitWeightMatch ?? fallbackAggregateWeight;
  return {
    piece_count: pieceCount,
    cbm: cbmMatch ? round3(Number(cbmMatch[1])) : null,
    weight_kg: selectedWeight ? round1(toKg(Number(selectedWeight[1]), selectedWeight[2])) : null,
  };
}

function findExplicitPieceCount(rawInput: string): number | null {
  const patterns = [
    /(?:数量|箱数|件数|总件数|总箱数)\s*[:：]?\s*(?:共|合计|总计)?\s*(\d{1,5})\s*(?:箱|件|pcs?|pieces?|ctns?|cartons?|boxes)/i,
    /(?:一共|共|合计|总计|总件数|件数)[^\d\n\r]{0,8}(\d{1,5})\s*(?:箱|件|pcs?|pieces?|ctns?|cartons?|boxes)/i,
    /(\d{1,5})\s*(?:箱|件|pcs?|pieces?|ctns?|cartons?|boxes)/i,
  ];
  for (const pattern of patterns) {
    const match = rawInput.match(pattern);
    if (match) {
      return Number(match[1]);
    }
  }
  return null;
}

function toKg(value: number, unit: string): number {
  const normalized = unit.toLowerCase();
  if (["lb", "lbs", "pound", "pounds", "磅"].includes(normalized)) {
    return value * 0.45359237;
  }
  return value;
}

function toCargoItem(
  id: number,
  lengthCm: number,
  widthCm: number,
  heightCm: number,
  weightKg: number | null,
  quantity: number,
): ParsedCargoItem {
  return {
    id,
    quantity,
    length_cm: lengthCm,
    width_cm: widthCm,
    height_cm: heightCm,
    weight_kg: weightKg,
    cbm: (lengthCm * widthCm * heightCm) / 1_000_000,
  };
}

function parseCargoLineItems(
  line: string,
  startId: number,
  config: QuoteWorkbenchConfig,
  allowNumericTable = false,
): ParsedCargoItem[] {
  const normalized = normalizeCargoText(line);
  const decimal = "(\\d+(?:\\.\\d+)?)";
  const separators = config.parser.dimension_separators.map(escapeRegex).join("|");
  const dimensionUnits = "mm|cm|厘米|m|米|inches|inch|in|\"|ft|feet|英尺|英寸";
  const dimensionRegex = new RegExp(
    `${decimal}\\s*(${dimensionUnits})?\\s*(?:${separators})\\s*${decimal}\\s*(${dimensionUnits})?\\s*(?:${separators})\\s*${decimal}\\s*(${dimensionUnits})?`,
    "gi",
  );
  const matches = Array.from(normalized.matchAll(dimensionRegex));
  if (matches.length) {
    const items = matches
      .map((match, index) => parseDimensionMatch(
        normalized,
        match,
        matches[index + 1]?.index ?? null,
        startId + index,
        config,
      ))
      .filter((item): item is ParsedCargoItem => item !== null);
    if (items.length) {
      return items;
    }
  }

  const single = parseSpaceSeparatedCargoLine(normalized, startId, config) ??
    (allowNumericTable ? parseNumericTableCargoLine(normalized, startId) : null);
  return single ? [single] : [];
}

function parseDimensionMatch(
  line: string,
  dimensionMatch: RegExpMatchArray,
  nextDimensionStart: number | null,
  id: number,
  config: QuoteWorkbenchConfig,
): ParsedCargoItem | null {
  if (dimensionMatch.index === undefined) {
    return null;
  }
  const decimal = "(\\d+(?:\\.\\d+)?)";
  const units = config.parser.weight_units.map(escapeRegex).join("|");
  const weightRegex = new RegExp(`${decimal}\\s*(${units})`, "i");
  const dimensionStart = dimensionMatch.index;
  const dimensionEnd = dimensionStart + dimensionMatch[0].length;
  const localEnd = nextDimensionStart ?? line.length;
  const localWeight = findItemWeight(line.slice(dimensionEnd, localEnd), dimensionEnd, weightRegex);
  const prefixWeight = localWeight ?? findItemWeight(line.slice(Math.max(0, dimensionStart - 48), dimensionStart), Math.max(0, dimensionStart - 48), weightRegex);
  const weightEnd = prefixWeight?.end ?? dimensionEnd;
  const quantity = findQuantity(line, dimensionStart, weightEnd);
  const dimensionFallbackUnit = dimensionMatch[6] || dimensionMatch[4] || dimensionMatch[2] ||
    inferDimensionUnit([Number(dimensionMatch[1]), Number(dimensionMatch[3]), Number(dimensionMatch[5])]) ||
    "cm";
  return toCargoItem(
    id,
    toCm(Number(dimensionMatch[1]), dimensionMatch[2] || dimensionFallbackUnit),
    toCm(Number(dimensionMatch[3]), dimensionMatch[4] || dimensionFallbackUnit),
    toCm(Number(dimensionMatch[5]), dimensionMatch[6] || dimensionFallbackUnit),
    prefixWeight ? toKg(Number(prefixWeight.match[1]), prefixWeight.match[2]) : null,
    quantity,
  );
}

function findItemWeight(
  segment: string,
  offset: number,
  weightRegex: RegExp,
): { match: RegExpMatchArray; end: number } | null {
  const match = segment.match(weightRegex);
  if (!match || match.index === undefined) {
    return null;
  }
  const beforeWeight = segment.slice(0, match.index);
  if (/(?:总重|总重量|重量合计|合计|总计)\s*[:：]?\s*$/i.test(beforeWeight)) {
    return null;
  }
  return { match, end: offset + match.index + match[0].length };
}

function hasDimensionWeightTable(rawInput: string): boolean {
  const normalized = normalizeCargoText(rawInput).toLowerCase();
  return /(?:长|length)\s*(?:宽|width)\s*(?:高|height)[\s\S]*?(?:重量|weight|kg)/i.test(normalized) ||
    /\bl\b\s*\bw\b\s*\bh\b[\s\S]*?(?:weight|kg)/i.test(normalized) ||
    /长[\s\S]{0,20}宽[\s\S]{0,20}高[\s\S]{0,40}(?:围长|重量)/i.test(normalized);
}

function parseNumericTableCargoLine(line: string, id: number): ParsedCargoItem | null {
  if (/(?:电话|phone|tel|邮编|postal|zip|地址|address|国家|country|城市|city|州省|province)/i.test(line)) {
    return null;
  }
  const numbers = Array.from(line.matchAll(/(?<![A-Za-z])\d+(?:\.\d+)?(?![A-Za-z])/g)).map((match) => Number(match[0]));
  if (numbers.length < 4) {
    return null;
  }
  const unit = inferDimensionUnit(numbers.slice(0, 3));
  const lengthCm = toCm(numbers[0], unit);
  const widthCm = toCm(numbers[1], unit);
  const heightCm = toCm(numbers[2], unit);
  const weightKg = numbers.length >= 5 ? numbers[numbers.length - 1] : numbers[3];
  if ([lengthCm, widthCm, heightCm, weightKg].some((value) => !Number.isFinite(value) || value <= 0)) {
    return null;
  }
  return toCargoItem(id, lengthCm, widthCm, heightCm, weightKg, 1);
}

function parseSpaceSeparatedCargoLine(line: string, id: number, config: QuoteWorkbenchConfig): ParsedCargoItem | null {
  if (!config.parser.allow_space_dimension_separator) {
    return null;
  }
  const decimal = "(\\d+(?:\\.\\d+)?)";
  const units = config.parser.weight_units.map(escapeRegex).join("|");
  const dimensionUnits = "mm|cm|厘米|m|米|inches|inch|in|\"|ft|feet|英尺|英寸";
  const pattern = new RegExp(
    `(?:^|[^\\d.])${decimal}\\s+${decimal}\\s+${decimal}(?:\\s*(${dimensionUnits}))?\\s+${decimal}\\s*(${units})`,
    "i",
  );
  const match = line.match(pattern);
  if (!match || match.index === undefined) {
    return null;
  }
  const start = match.index;
  const end = start + match[0].length;
  return toCargoItem(
    id,
    toCm(Number(match[1]), match[4] || inferDimensionUnit([Number(match[1]), Number(match[2]), Number(match[3])]) || "cm"),
    toCm(Number(match[2]), match[4] || inferDimensionUnit([Number(match[1]), Number(match[2]), Number(match[3])]) || "cm"),
    toCm(Number(match[3]), match[4] || inferDimensionUnit([Number(match[1]), Number(match[2]), Number(match[3])]) || "cm"),
    toKg(Number(match[5]), match[6]),
    findQuantity(line, start, end),
  );
}

function findQuantity(line: string, dimensionStart: number, itemEnd: number): number {
  const prefix = line.slice(Math.max(0, dimensionStart - 32), dimensionStart);
  const suffix = line.slice(itemEnd, itemEnd + 48);
  const quantityUnit = "(?:pcs?|pieces?|ctns?|cartons?|boxes|箱|件|托|pallets?)";
  const suffixNumberFirst = suffix.match(new RegExp(`(\\d{1,5})\\s*${quantityUnit}`, "i"));
  if (suffixNumberFirst) {
    return Math.max(1, Number(suffixNumberFirst[1]));
  }
  const prefixMatch = prefix.match(new RegExp(`(\\d{1,5})\\s*${quantityUnit}\\s*$`, "i"));
  if (prefixMatch) {
    return Math.max(1, Number(prefixMatch[1]));
  }
  const suffixTokenFirst = suffix.match(/(?:x|×|qty|quantity|数量|件数)\s*(\d{1,5})\b/i);
  if (suffixTokenFirst) {
    return Math.max(1, Number(suffixTokenFirst[1]));
  }
  return 1;
}

function toCm(value: number, unit: string | undefined): number {
  const normalized = (unit || "cm").toLowerCase();
  if (normalized === "mm") {
    return value / 10;
  }
  if (["m", "米"].includes(normalized)) {
    return value * 100;
  }
  if (["in", "inch", "inches", "\"", "英寸"].includes(normalized)) {
    return value * 2.54;
  }
  if (["ft", "feet", "英尺"].includes(normalized)) {
    return value * 30.48;
  }
  return value;
}

function inferDimensionUnit(values: number[]): string | undefined {
  return values.some((value) => Number.isFinite(value) && value > 500) ? "mm" : undefined;
}

function normalizeCargoText(value: string): string {
  return value
    .replace(/＊/g, "*")
    .replace(/Ｘ/g, "x")
    .replace(/公斤/g, "kg")
    .replace(/千克/g, "kg")
    .replace(/厘米/g, "cm");
}

function parseAddress(lines: string[], config: QuoteWorkbenchConfig): ParsedAddress {
  const postalRegex = safeRegex(config.parser.postal_code_pattern, "i");
  let postalCode: string | null = null;
  let addressLine: string | null = null;
  let city: string | null = null;
  let province: ProvinceAlias | null = null;
  const cleanedLines: string[] = [];

  for (const rawLine of lines) {
    const labeled = parseLabeledAddressLine(rawLine, config);
    if (labeled.skip) {
      postalCode = postalCode ?? labeled.postal_code;
      addressLine = addressLine ?? labeled.address_line;
      city = city ?? labeled.city;
      province = province ?? labeled.province;
      continue;
    }

    const line = cleanAddressLine(rawLine);
    if (!line || isNonAddressLine(line)) {
      continue;
    }
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
      const parsedLine = parseAddressLineWithProvince(line, foundProvince.alias, config.parser.country_aliases);
      if (parsedLine.address_line && !addressLine) {
        addressLine = parsedLine.address_line;
      }
      if (parsedLine.city && !city) {
        city = parsedLine.city;
      }
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

  const inferredProvince = province ?? inferProvinceFromPostalCode(postalCode, config.provinces);

  return {
    address_line: addressLine,
    city,
    province_code: inferredProvince?.code ?? null,
    province_name: inferredProvince?.name ?? null,
    postal_code: postalCode,
    country: config.parser.default_country,
  };
}

function parseLabeledAddressLine(
  rawLine: string,
  config: QuoteWorkbenchConfig,
): {
  skip: boolean;
  address_line: string | null;
  city: string | null;
  province: ProvinceAlias | null;
  postal_code: string | null;
} {
  const empty = {
    skip: false,
    address_line: null,
    city: null,
    province: null,
    postal_code: null,
  };
  const match = rawLine.match(/^\s*([^:：]{1,24})\s*[:：]\s*(.+?)\s*$/);
  if (!match) {
    return empty;
  }
  const label = match[1].trim().toLowerCase();
  const value = match[2].trim();
  if (!value) {
    return { ...empty, skip: true };
  }
  if (/(?:收货人|联系人|电话|手机|国家|country|consignee|contact|phone|tel)$/.test(label)) {
    return { ...empty, skip: true };
  }
  if (/(?:地址\s*\d*|address\s*(?:line)?\s*\d*)$/.test(label)) {
    const postalMatch = value.match(safeRegex(config.parser.postal_code_pattern, "i") ?? /a^/);
    const foundProvince = findProvince(value, config.provinces);
    const parsedLine = foundProvince
      ? parseAddressLineWithProvince(value, foundProvince.alias, config.parser.country_aliases)
      : { address_line: null, city: null };
    return {
      ...empty,
      skip: true,
      address_line: parsedLine.address_line ?? stripAddressQualifiers(value, config) ?? value,
      city: parsedLine.city,
      province: foundProvince?.province ?? null,
      postal_code: postalMatch?.[0] ? normalizeCanadianPostalCode(postalMatch[0]) : null,
    };
  }
  if (/(?:城市|city)$/.test(label)) {
    return { ...empty, skip: true, city: value };
  }
  if (/(?:州省|省份|province|state)$/.test(label)) {
    return { ...empty, skip: true, province: findProvince(value, config.provinces)?.province ?? null };
  }
  if (/(?:邮编|postal|zip)/.test(label)) {
    const postalMatch = value.match(safeRegex(config.parser.postal_code_pattern, "i") ?? /a^/);
    return { ...empty, skip: true, postal_code: postalMatch?.[0] ? normalizeCanadianPostalCode(postalMatch[0]) : null };
  }
  return empty;
}

function inferProvinceFromPostalCode(
  postalCode: string | null,
  provinces: ProvinceAlias[],
): ProvinceAlias | null {
  if (!postalCode) {
    return null;
  }
  const map: Record<string, string> = {
    A: "NL",
    B: "NS",
    C: "PE",
    E: "NB",
    G: "QC",
    H: "QC",
    J: "QC",
    K: "ON",
    L: "ON",
    M: "ON",
    N: "ON",
    P: "ON",
    R: "MB",
    S: "SK",
    T: "AB",
    V: "BC",
    X: "NT",
    Y: "YT",
  };
  const provinceCode = map[postalCode.trim().toUpperCase()[0]];
  return provinces.find((province) => province.code === provinceCode) ?? null;
}

function cleanAddressLine(line: string): string {
  return line
    .trim()
    .replace(/^加拿大地址\s*[:：]\s*/i, "")
    .replace(/^(?:地址\s*\d*|收件地址|目的地|派送地址|delivery\s*address|address\s*(?:line)?\s*\d*)\s*[:：]\s*/i, "")
    .replace(/^\d{1,5}\s*(?:件|箱|pcs?|pieces?|ctns?|cartons?|boxes)\s*(?:货|货物|cargo|goods)?[.。,\s，]*/i, "")
    .trim();
}

function stripAddressQualifiers(value: string, config: QuoteWorkbenchConfig): string | null {
  let output = value;
  const postalRegex = safeRegex(config.parser.postal_code_pattern, "ig");
  if (postalRegex) {
    output = output.replace(postalRegex, " ");
  }
  for (const province of config.provinces) {
    for (const alias of province.aliases) {
      if (containsToken(output, alias)) {
        output = output.replace(new RegExp(`(^|[^a-z0-9])${escapeRegex(alias)}([^a-z0-9]|$)`, "ig"), " ");
      }
    }
  }
  output = removeCountryAliases(output, config.parser.country_aliases);
  const parts = output
    .split(/[,，]/)
    .map((part) => part.replace(/\s+/g, " ").trim())
    .filter(Boolean);
  output = (parts.length > 1 ? joinUniqueParts(parts) : output)
    .replace(/[,，]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return output || null;
}

function isNonAddressLine(line: string): boolean {
  if (/[A-Za-z]\d[A-Za-z][ -]?\d[A-Za-z]\d/.test(line) || looksLikeStreetAddress(line)) {
    return false;
  }
  if (/^[a-zA-Z_][a-zA-Z0-9_]*\s*=/.test(line)) {
    return true;
  }
  if (/(?:hscode|hs\s*code|品名|产品|商品|cbm|m3|m³|kg|kgs|公斤|千克|箱|件|报价|谢谢|麻烦)/i.test(line)) {
    return true;
  }
  return !/[A-Za-z]/.test(line);
}

function looksLikeStreetAddress(line: string): boolean {
  if (/(?:cbm|m3|m³|kg|kgs|公斤|千克|箱|件)/i.test(line)) {
    return false;
  }
  if (/\d+(?:\.\d+)?\s*(?:mm|cm|厘米|m|米|inches|inch|in|"|ft|feet|英尺|英寸)?\s*(?:\*|x|X|×|by)\s*\d+(?:\.\d+)?/i.test(line)) {
    return false;
  }
  return /\b\d{1,6}\b/.test(line) && /[A-Za-z]/.test(line);
}

function parseAddressLineWithProvince(
  line: string,
  provinceAlias: string,
  countryAliases: string[],
): { address_line: string | null; city: string | null } {
  const beforeProvince = line.split(new RegExp(escapeRegex(provinceAlias), "i"))[0] ?? line;
  const withoutCountry = removeCountryAliases(beforeProvince, countryAliases).replace(/\s+/g, " ").trim();
  const parts = withoutCountry
    .split(/[,，]/)
    .map((part) => part.trim())
    .filter(Boolean);
  if (parts.length >= 2) {
    if (looksLikeStreetAddress(parts[parts.length - 1])) {
      return {
        address_line: joinUniqueParts(parts),
        city: null,
      };
    }
    return {
      address_line: parts.slice(0, -1).join(", "),
      city: parts[parts.length - 1],
    };
  }
  if (parts.length === 1 && !/^\d+/.test(parts[0])) {
    return { address_line: null, city: parts[0] };
  }
  return { address_line: parts[0] ?? null, city: null };
}

function joinUniqueParts(parts: string[]): string {
  const seen = new Set<string>();
  const unique: string[] = [];
  for (const part of parts) {
    const key = part.trim().toLowerCase();
    if (!seen.has(key)) {
      seen.add(key);
      unique.push(part);
    }
  }
  return unique.join(", ");
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
  output = removeCountryAliases(output, countryAliases);
  output = output.replace(/[,，]+/g, " ").replace(/\s+/g, " ").trim();
  return output || null;
}

function removeCountryAliases(line: string, countryAliases: string[]): string {
  let output = line;
  for (const countryAlias of countryAliases) {
    output = output.replace(new RegExp(escapeRegex(countryAlias), "ig"), " ");
  }
  return output;
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

function buildMissingFields({
  totalCbm,
  totalWeight,
  pieceCount,
  address,
}: {
  totalCbm: number;
  totalWeight: number;
  pieceCount: number;
  address: ParsedAddress;
}): string[] {
  const missing: string[] = [];
  if (!pieceCount) {
    missing.push("件数");
  }
  if (!totalCbm) {
    missing.push("总体积 CBM");
  }
  if (!totalWeight) {
    missing.push("总重量 KG");
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
  pieceCount,
  totalCbm,
  totalWeight,
  address,
  density,
  longestSide,
  heaviestPiece,
  config,
}: {
  cargoItems: ParsedCargoItem[];
  pieceCount: number;
  totalCbm: number;
  totalWeight: number;
  address: ParsedAddress;
  density: number | null;
  longestSide: number | null;
  heaviestPiece: number | null;
  config: QuoteWorkbenchConfig;
}): string[] {
  const risks: string[] = [];
  if (!cargoItems.length && (!pieceCount || !totalCbm || !totalWeight)) {
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
  if (!cargoItems.length) {
    risks.push("客户提供的是汇总体积/重量，最大单件尺寸待确认。");
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
