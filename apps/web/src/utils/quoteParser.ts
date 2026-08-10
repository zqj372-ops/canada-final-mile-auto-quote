import type { ProvinceAlias, QuoteWorkbenchConfig } from "../api/client";

export interface ParsedCargoItem {
  id: number;
  quantity: number;
  length_cm: number | null;
  width_cm: number | null;
  height_cm: number | null;
  weight_kg: number | null;
  cbm: number | null;
  total_weight_kg: number | null;
  total_cbm: number | null;
  source_span: string | null;
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

interface ParsedAggregateTotals {
  piece_count: number | null;
  cbm: number | null;
  weight_kg: number | null;
}

const NUMBER_TOKEN_SOURCE = String.raw`(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?)`;
const HORIZONTAL_SPACE_SOURCE = String.raw`[^\S\r\n]*`;
const PIECE_UNIT_SOURCE = String.raw`(?:pcs?|pieces?|units?|ctns?|cartons?|boxes|pkgs?|packages?|cases?|bags?|sacks?|rolls?|drums?|crates?|skids?|skds?|bundles?|sets?|pallets?|plts?|(?:个\s*)?(?:件|箱|包|袋|卷|桶|架|捆|套|台|托盘|托))`;
const DIMENSION_UNIT_SOURCE = String.raw`(?:millimet(?:er|re)s?|mms?|centimet(?:er|re)s?|cms?|met(?:er|re)s?|mm|cm|m|毫米|厘米|米|inches|inch|in|"|feet|foot|ft|英尺|英寸)`;
const WEIGHT_UNIT_SOURCE = String.raw`(?:metric\s*(?:tons?|tonnes?)|tonnes?|kilograms?|kgs?|kg|公斤|千克|pounds?|lbs?|lb|磅|grams?|g|克|m\.?t\.?|t)`;
const VOLUME_UNIT_SOURCE = String.raw`(?:c\.?b\.?m\.?|m(?:\^?3|³)|cubic\s*met(?:er|re)s?|cu\.?\s*ft|cuft|cft|ft(?:\^?3|³)|cubic\s*(?:feet|foot)|cu\.?\s*in|cuin|cin|in(?:\^?3|³)|cubic\s*inches?|立方米?|方)`;
const PIECE_COUNT_LABEL_SOURCE = String.raw`(?:qty|quantity|(?:no\.?|number|#)\s*of\s*${PIECE_UNIT_SOURCE}|pkg\s*count|package\s*count|piece_count|数量|箱数|件数|总件数|总箱数)`;
const TOTAL_WEIGHT_LABEL_SOURCE = String.raw`(?:total\s*(?:gross\s*)?(?:weight|wt)|ttl\s*(?:weight|wt)|gross\s*(?:weight|wt)|g(?:\.|/)?\s*w(?:t)?\.?|t\.?\s*w\.?|总重量|总重|重量合计|总毛重)`;
const VOLUME_LABEL_SOURCE = String.raw`(?:total\s*(?:volume|vol\.?|cube|cbm)|ttl\s*(?:volume|vol\.?|cube|cbm)|volume|vol\.?|meas(?:urement)?\.?|cube|c\.?b\.?m\.?|cuft|cft|总体积|总方数|方数|体积)`;

export function parseQuoteInput(rawInput: string, config: QuoteWorkbenchConfig): ParsedQuoteInput {
  const lines = rawInput
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const cargoItems: ParsedCargoItem[] = [];
  const addressLines: string[] = [];
  const allowNumericTable = hasDimensionWeightTable(rawInput);
  let dimensionUnitHint: string | undefined;

  for (const line of lines) {
    const items = parseCargoLineItems(
      line,
      cargoItems.length + 1,
      config,
      allowNumericTable,
      dimensionUnitHint,
    );
    if (items.length) {
      cargoItems.push(...items);
      dimensionUnitHint = findDimensionUnitHint(line, config) ?? dimensionUnitHint;
    } else {
      addressLines.push(line);
      dimensionUnitHint = undefined;
    }
  }

  const aggregate = parseAggregateTotals(rawInput, cargoItems.length);
  if (cargoItems.length === 1 && aggregate.piece_count && aggregate.piece_count >= cargoItems[0].quantity) {
    cargoItems[0] = reconcileSingleCargoItemWithTotals(cargoItems[0], aggregate);
  }
  if (!cargoItems.length && aggregate.piece_count && (aggregate.cbm || aggregate.weight_kg)) {
    cargoItems.push(buildAggregateCargoItem(aggregate, rawInput));
  }
  const address = parseAddress(addressLines, config);
  const cargoCbm = round3(cargoItems.reduce((sum, item) => sum + (item.cbm ?? 0) * item.quantity, 0));
  const cargoWeight = round1(cargoItems.reduce((sum, item) => sum + (item.weight_kg ?? 0) * item.quantity, 0));
  const cargoPieceCount = cargoItems.reduce((sum, item) => sum + item.quantity, 0);
  const totalCbm = aggregate.cbm || cargoCbm || 0;
  const totalWeight = aggregate.weight_kg || cargoWeight || 0;
  const pieceCount =
    aggregate.piece_count && aggregate.piece_count >= cargoPieceCount
      ? aggregate.piece_count
      : cargoPieceCount || aggregate.piece_count || 0;
  const density = totalCbm > 0 ? round1(totalWeight / totalCbm) : null;
  const dimensionedItems = cargoItems.filter(hasCompleteDimensions);
  const maxItem = dimensionedItems.reduce<ParsedCargoItem | null>(
    (current, item) => (!current || cargoItemVolume(item) > cargoItemVolume(current) ? item : current),
    null,
  );
  const knownDimensions = dimensionedItems.flatMap((item) => [item.length_cm, item.width_cm, item.height_cm]) as number[];
  const longestSide = knownDimensions.length
    ? Math.max(...knownDimensions)
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
      ? [maxItem.length_cm!, maxItem.width_cm!, maxItem.height_cm!]
      : null,
    longest_side_cm: longestSide,
    heaviest_piece_kg: heaviestPiece,
    address,
    missing_fields: missingFields,
    risk_hints: riskHints,
    confidence: calculateConfidence(cargoItems, address, density),
  };
}

function parseAggregateTotals(rawInput: string, cargoItemCount: number): ParsedAggregateTotals {
  const normalized = normalizeCargoText(rawInput);
  const pieceCount = findExplicitPieceCount(normalized);
  const labeledCbmMatch = findLastMatch(
    normalized,
    new RegExp(
      String.raw`(?<![A-Za-z0-9.])(${VOLUME_LABEL_SOURCE})\s*[:：=]?\s*(${NUMBER_TOKEN_SOURCE})(?![\d,.])\s*(${VOLUME_UNIT_SOURCE})?(?!\s*(?:\*|x|×|by\b))`,
      "gi",
    ),
  );
  const cbmMatch = labeledCbmMatch ?? findLastMatch(
    normalized,
    new RegExp(String.raw`(${NUMBER_TOKEN_SOURCE})\s*(${VOLUME_UNIT_SOURCE})(?=$|[^A-Za-z])`, "gi"),
  );
  const cbm = cbmMatch
    ? toCbm(
        parseFlexibleNumber(cbmMatch[labeledCbmMatch ? 2 : 1]),
        cbmMatch[labeledCbmMatch ? 3 : 2] || (labeledCbmMatch ? cbmMatch[1] : "cbm"),
      )
    : null;
  let weightKg = findExplicitAggregateWeight(normalized);
  if (weightKg === null && pieceCount) {
    const perPieceWeight = findPerPieceWeight(normalized);
    if (perPieceWeight !== null && cargoItemCount <= 1) {
      weightKg = perPieceWeight * pieceCount;
    }
  }
  const weightMatches = Array.from(
    normalized.matchAll(new RegExp(String.raw`(${NUMBER_TOKEN_SOURCE})\s*(${WEIGHT_UNIT_SOURCE})(?=$|[^A-Za-z])`, "gi")),
  );
  const weightMatch = weightMatches.length ? weightMatches[weightMatches.length - 1] : undefined;
  const hasDimensionSpecs = new RegExp(
    String.raw`${NUMBER_TOKEN_SOURCE}\s*(?:${DIMENSION_UNIT_SOURCE})?\s*(?:\*|x|X|×|by)\s*${NUMBER_TOKEN_SOURCE}`,
    "i",
  ).test(normalized);
  const fallbackAggregateWeight = !hasDimensionSpecs && pieceCount && cbmMatch ? weightMatch : undefined;
  if (weightKg === null && fallbackAggregateWeight) {
    weightKg = toKg(parseFlexibleNumber(fallbackAggregateWeight[1]), fallbackAggregateWeight[2]);
  }
  return {
    piece_count: pieceCount,
    cbm: cbm === null ? null : round3(cbm),
    weight_kg: weightKg === null ? null : round1(weightKg),
  };
}

function findExplicitPieceCount(rawInput: string): number | null {
  const normalized = normalizeCargoText(rawInput);
  const patterns = [
    new RegExp(String.raw`${PIECE_COUNT_LABEL_SOURCE}${HORIZONTAL_SPACE_SOURCE}[:：=#-]?${HORIZONTAL_SPACE_SOURCE}(?:共|合计|总计)?${HORIZONTAL_SPACE_SOURCE}(${NUMBER_TOKEN_SOURCE})${HORIZONTAL_SPACE_SOURCE}${PIECE_UNIT_SOURCE}?`, "i"),
    new RegExp(String.raw`(?:一共|共|合计|总计|总件数|件数)[^\d\n\r]{0,8}(${NUMBER_TOKEN_SOURCE})${HORIZONTAL_SPACE_SOURCE}${PIECE_UNIT_SOURCE}`, "i"),
    new RegExp(String.raw`(${NUMBER_TOKEN_SOURCE})${HORIZONTAL_SPACE_SOURCE}${PIECE_UNIT_SOURCE}`, "i"),
    new RegExp(String.raw`(?:ctns?|cartons?|pkgs?|packages?|pcs?|pieces?|skids?|skds?|pallets?|plts?)${HORIZONTAL_SPACE_SOURCE}[:：=#-]?${HORIZONTAL_SPACE_SOURCE}(${NUMBER_TOKEN_SOURCE})\b`, "i"),
  ];
  for (const pattern of patterns) {
    const match = normalized.match(pattern);
    if (match) {
      return parseFlexibleNumber(match[1]);
    }
  }
  return null;
}

function findExplicitAggregateWeight(value: string): number | null {
  const patterns = [
    new RegExp(String.raw`${TOTAL_WEIGHT_LABEL_SOURCE}\s*[:：=#-]?\s*(${NUMBER_TOKEN_SOURCE})\s*(${WEIGHT_UNIT_SOURCE})(?=$|[^A-Za-z])`, "gi"),
    new RegExp(String.raw`${TOTAL_WEIGHT_LABEL_SOURCE}[^\n\r]{0,32}?(${NUMBER_TOKEN_SOURCE})\s*(${WEIGHT_UNIT_SOURCE})(?=$|[^A-Za-z])`, "gi"),
    new RegExp(String.raw`(?:weight|wt|重量|毛重)\s*[:：=]\s*(?:total|gross|共|合计|总计)?\s*(${NUMBER_TOKEN_SOURCE})\s*(${WEIGHT_UNIT_SOURCE})(?=$|[^A-Za-z])`, "gi"),
    new RegExp(String.raw`(?:总|合计|总计|一共|共)\s*[:：]?\s*(?:总?重(?:重量)?|毛重)?\s*(${NUMBER_TOKEN_SOURCE})\s*(${WEIGHT_UNIT_SOURCE})(?=$|[^A-Za-z])`, "gi"),
    new RegExp(String.raw`(${NUMBER_TOKEN_SOURCE})\s*(${WEIGHT_UNIT_SOURCE})\s*(?:total|gross|合计|总重)`, "gi"),
  ];
  for (const pattern of patterns) {
    for (const match of value.matchAll(pattern)) {
      const start = match.index ?? 0;
      if (!isPerPieceWeightContext(value, start, start + match[0].length)) {
        return toKg(parseFlexibleNumber(match[1]), match[2]);
      }
    }
  }
  return null;
}

function findPerPieceWeight(value: string): number | null {
  const itemName = String.raw`(?:${PIECE_UNIT_SOURCE}|pc|ctn|pkg|plt)`;
  const patterns = [
    new RegExp(String.raw`(?:单|每)(?:件|箱|包|袋|卷|桶|托|托盘)(?:毛重|重量|重)?\s*[:：=]?\s*(${NUMBER_TOKEN_SOURCE})\s*(${WEIGHT_UNIT_SOURCE})(?=$|[^A-Za-z])`, "i"),
    new RegExp(String.raw`(?:weight\s*)?(?:each|per\s*${itemName})\s*[:：=]?\s*(${NUMBER_TOKEN_SOURCE})\s*(${WEIGHT_UNIT_SOURCE})(?=$|[^A-Za-z])`, "i"),
    new RegExp(String.raw`(${NUMBER_TOKEN_SOURCE})\s*(${WEIGHT_UNIT_SOURCE})\s*(?:each|ea\.?|per\s*${itemName}|/\s*(?:ea\.?|${itemName})|每(?:件|箱|包|袋|卷|桶|托|托盘))`, "i"),
  ];
  for (const pattern of patterns) {
    const match = value.match(pattern);
    if (match) {
      return toKg(parseFlexibleNumber(match[1]), match[2]);
    }
  }
  return null;
}

function isPerPieceWeightContext(value: string, start: number, end: number): boolean {
  const context = value.slice(Math.max(0, start - 24), Math.min(value.length, end + 24));
  return /(?:\beach\b|\bea\.?\b|\bper\s*(?:piece|carton|box|package|case|bag|skid|pallet)\b|\/\s*(?:ea\.?|pc|ctn|pkg|plt)\b|单(?:件|箱|包|袋|卷|桶|托)|每(?:件|箱|包|袋|卷|桶|托))/i.test(context);
}

function reconcileSingleCargoItemWithTotals(
  item: ParsedCargoItem,
  aggregate: ParsedAggregateTotals,
): ParsedCargoItem {
  const quantity = aggregate.piece_count ?? item.quantity;
  let weightKg = item.weight_kg;
  if (aggregate.weight_kg && quantity > 0) {
    const expectedTotal = weightKg === null ? null : weightKg * quantity;
    const tolerance = Math.max(1, aggregate.weight_kg * 0.05);
    if (expectedTotal === null || Math.abs(expectedTotal - aggregate.weight_kg) > tolerance) {
      weightKg = aggregate.weight_kg / quantity;
    }
  }
  return {
    ...item,
    quantity,
    weight_kg: weightKg,
    total_weight_kg: aggregate.weight_kg ?? (weightKg === null ? null : weightKg * quantity),
    total_cbm: aggregate.cbm ?? (item.cbm === null ? null : item.cbm * quantity),
  };
}

function buildAggregateCargoItem(aggregate: ParsedAggregateTotals, rawInput: string): ParsedCargoItem {
  const quantity = aggregate.piece_count ?? 1;
  return {
    id: 1,
    quantity,
    length_cm: null,
    width_cm: null,
    height_cm: null,
    weight_kg: aggregate.weight_kg ? aggregate.weight_kg / quantity : null,
    cbm: aggregate.cbm ? aggregate.cbm / quantity : null,
    total_weight_kg: aggregate.weight_kg,
    total_cbm: aggregate.cbm,
    source_span: findAggregateSourceLine(rawInput),
  };
}

function toKg(value: number, unit: string): number {
  const normalized = unit.toLowerCase().replace(/[.\s]/g, "");
  if (["lb", "lbs", "pound", "pounds", "磅"].includes(normalized)) {
    return value * 0.45359237;
  }
  if (["g", "gram", "grams", "克"].includes(normalized)) {
    return value / 1000;
  }
  if (["mt", "t", "tonne", "tonnes", "metricton", "metrictons", "metrictonne", "metrictonnes"].includes(normalized)) {
    return value * 1000;
  }
  return value;
}

function toCbm(value: number, unit: string): number {
  const normalized = unit.toLowerCase().replace(/[.\s^]/g, "");
  if (["cuft", "cft", "ft3", "cubicfoot", "cubicfeet"].includes(normalized)) {
    return value * 0.028316846592;
  }
  if (["cuin", "cin", "in3", "cubicinch", "cubicinches"].includes(normalized)) {
    return value * 0.000016387064;
  }
  return value;
}

function parseFlexibleNumber(value: string): number {
  let normalized = value.trim().replace(/\s/g, "");
  if (normalized.includes(",")) {
    const decimalDigits = normalized.slice(normalized.lastIndexOf(",") + 1).length;
    normalized = normalized.includes(".") || decimalDigits === 3
      ? normalized.replace(/,/g, "")
      : normalized.replace(/,/g, ".");
  }
  return Number(normalized);
}

function findLastMatch(value: string, pattern: RegExp): RegExpMatchArray | null {
  const matches = Array.from(value.matchAll(pattern));
  return matches.length ? matches[matches.length - 1] : null;
}

function findAggregateSourceLine(rawInput: string): string | null {
  const candidates = rawInput
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !/^[a-z_][a-z0-9_]*\s*=/i.test(line))
    .map((line) => ({
      line,
      score: [
        /(?:qty|quantity|pcs?|pieces?|ctns?|cartons?|pkgs?|packages?|件|箱|包|托)/i,
        /(?:cbm|m3|m³|volume|vol\.?|meas(?:urement)?|总体积|体积|方|立方)/i,
        /(?:kgs?|kg|lbs?|pounds?|gross\s*(?:weight|wt)|g\.?\s*w\.?|总重|重量|毛重)/i,
      ].filter((pattern) => pattern.test(line)).length,
    }))
    .filter((candidate) => candidate.score > 0);
  candidates.sort((left, right) => right.score - left.score);
  return candidates[0]?.line.slice(0, 240) ?? null;
}

function hasCompleteDimensions(
  item: ParsedCargoItem,
): item is ParsedCargoItem & { length_cm: number; width_cm: number; height_cm: number } {
  return [item.length_cm, item.width_cm, item.height_cm].every(
    (value) => value !== null && Number.isFinite(value) && value > 0,
  );
}

function cargoItemVolume(item: ParsedCargoItem): number {
  if (item.cbm !== null) {
    return item.cbm;
  }
  return hasCompleteDimensions(item)
    ? (item.length_cm * item.width_cm * item.height_cm) / 1_000_000
    : 0;
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
    total_weight_kg: weightKg === null ? null : weightKg * quantity,
    total_cbm: ((lengthCm * widthCm * heightCm) / 1_000_000) * quantity,
    source_span: null,
  };
}

function parseCargoLineItems(
  line: string,
  startId: number,
  config: QuoteWorkbenchConfig,
  allowNumericTable = false,
  dimensionUnitHint?: string,
): ParsedCargoItem[] {
  const normalized = normalizeLabeledDimensions(normalizeCargoText(line));
  const decimal = `(${NUMBER_TOKEN_SOURCE})`;
  const separators = config.parser.dimension_separators.map(escapeRegex).join("|");
  const dimensionUnits = DIMENSION_UNIT_SOURCE;
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
        dimensionUnitHint,
      ))
      .filter((item): item is ParsedCargoItem => item !== null);
    if (items.length) {
      return items;
    }
  }

  const single = parseSpaceSeparatedCargoLine(normalized, startId, config, dimensionUnitHint) ??
    (allowNumericTable ? parseNumericTableCargoLine(normalized, startId, dimensionUnitHint) : null);
  return single ? [single] : [];
}

function findDimensionUnitHint(line: string, config: QuoteWorkbenchConfig): string | undefined {
  const normalized = normalizeLabeledDimensions(normalizeCargoText(line));
  const decimal = `(${NUMBER_TOKEN_SOURCE})`;
  const separators = config.parser.dimension_separators.map(escapeRegex).join("|");
  const pattern = new RegExp(
    `${decimal}\\s*(${DIMENSION_UNIT_SOURCE})?\\s*(?:${separators})\\s*` +
      `${decimal}\\s*(${DIMENSION_UNIT_SOURCE})?\\s*(?:${separators})\\s*` +
      `${decimal}\\s*(${DIMENSION_UNIT_SOURCE})?`,
    "i",
  );
  const match = normalized.match(pattern);
  if (!match) {
    return undefined;
  }
  return match[6] || match[4] || match[2] || inferDimensionUnit([
    parseFlexibleNumber(match[1]),
    parseFlexibleNumber(match[3]),
    parseFlexibleNumber(match[5]),
  ]);
}

function parseDimensionMatch(
  line: string,
  dimensionMatch: RegExpMatchArray,
  nextDimensionStart: number | null,
  id: number,
  config: QuoteWorkbenchConfig,
  dimensionUnitHint?: string,
): ParsedCargoItem | null {
  if (dimensionMatch.index === undefined) {
    return null;
  }
  const decimal = `(${NUMBER_TOKEN_SOURCE})`;
  const units = buildWeightUnitPattern(config);
  const weightRegex = new RegExp(`${decimal}\\s*(${units})`, "i");
  const dimensionStart = dimensionMatch.index;
  const dimensionEnd = dimensionStart + dimensionMatch[0].length;
  const localEnd = nextDimensionStart ?? line.length;
  const localWeight = findItemWeight(line.slice(dimensionEnd, localEnd), dimensionEnd, weightRegex);
  const prefixWeight = localWeight ?? findItemWeight(line.slice(Math.max(0, dimensionStart - 48), dimensionStart), Math.max(0, dimensionStart - 48), weightRegex);
  const weightEnd = Math.max(dimensionEnd, prefixWeight?.end ?? dimensionEnd);
  const quantity = findQuantity(line, dimensionStart, weightEnd);
  const dimensionFallbackUnit = dimensionMatch[6] || dimensionMatch[4] || dimensionMatch[2] || dimensionUnitHint ||
    inferDimensionUnit([parseFlexibleNumber(dimensionMatch[1]), parseFlexibleNumber(dimensionMatch[3]), parseFlexibleNumber(dimensionMatch[5])]) ||
    "cm";
  return toCargoItem(
    id,
    toCm(parseFlexibleNumber(dimensionMatch[1]), dimensionMatch[2] || dimensionFallbackUnit),
    toCm(parseFlexibleNumber(dimensionMatch[3]), dimensionMatch[4] || dimensionFallbackUnit),
    toCm(parseFlexibleNumber(dimensionMatch[5]), dimensionMatch[6] || dimensionFallbackUnit),
    prefixWeight ? toKg(parseFlexibleNumber(prefixWeight.match[1]), prefixWeight.match[2]) : null,
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

function parseNumericTableCargoLine(
  line: string,
  id: number,
  dimensionUnitHint?: string,
): ParsedCargoItem | null {
  if (/(?:电话|phone|tel|邮编|postal|zip|地址|address|国家|country|城市|city|州省|province)/i.test(line)) {
    return null;
  }
  const numbers = Array.from(line.matchAll(/(?<![A-Za-z])\d+(?:\.\d+)?(?![A-Za-z])/g)).map((match) => Number(match[0]));
  if (numbers.length < 4) {
    return null;
  }
  const unit = dimensionUnitHint || inferDimensionUnit(numbers.slice(0, 3));
  const lengthCm = toCm(numbers[0], unit);
  const widthCm = toCm(numbers[1], unit);
  const heightCm = toCm(numbers[2], unit);
  const weightKg = numbers.length >= 5 ? numbers[numbers.length - 1] : numbers[3];
  if ([lengthCm, widthCm, heightCm, weightKg].some((value) => !Number.isFinite(value) || value <= 0)) {
    return null;
  }
  return toCargoItem(id, lengthCm, widthCm, heightCm, weightKg, 1);
}

function parseSpaceSeparatedCargoLine(
  line: string,
  id: number,
  config: QuoteWorkbenchConfig,
  dimensionUnitHint?: string,
): ParsedCargoItem | null {
  if (!config.parser.allow_space_dimension_separator) {
    return null;
  }
  const decimal = `(${NUMBER_TOKEN_SOURCE})`;
  const units = buildWeightUnitPattern(config);
  const dimensionUnits = DIMENSION_UNIT_SOURCE;
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
    toCm(parseFlexibleNumber(match[1]), match[4] || dimensionUnitHint || inferDimensionUnit([parseFlexibleNumber(match[1]), parseFlexibleNumber(match[2]), parseFlexibleNumber(match[3])]) || "cm"),
    toCm(parseFlexibleNumber(match[2]), match[4] || dimensionUnitHint || inferDimensionUnit([parseFlexibleNumber(match[1]), parseFlexibleNumber(match[2]), parseFlexibleNumber(match[3])]) || "cm"),
    toCm(parseFlexibleNumber(match[3]), match[4] || dimensionUnitHint || inferDimensionUnit([parseFlexibleNumber(match[1]), parseFlexibleNumber(match[2]), parseFlexibleNumber(match[3])]) || "cm"),
    toKg(parseFlexibleNumber(match[5]), match[6]),
    findQuantity(line, start, end),
  );
}

function findQuantity(line: string, dimensionStart: number, itemEnd: number): number {
  const prefix = line.slice(Math.max(0, dimensionStart - 48), dimensionStart);
  const suffix = line.slice(itemEnd, itemEnd + 48);
  const number = `(${NUMBER_TOKEN_SOURCE})`;
  const quantityUnit = PIECE_UNIT_SOURCE;
  const prefixLabeled = prefix.match(new RegExp(`(?:qty|quantity|数量|件数)\\s*[:：=#-]?\\s*${number}\\s*${quantityUnit}?[^\\d]*$`, "i"));
  if (prefixLabeled) {
    return Math.max(1, parseFlexibleNumber(prefixLabeled[1]));
  }
  const prefixBare = prefix.match(new RegExp(`${number}\\s*(?:@|x|×)\\s*$`, "i"));
  if (prefixBare) {
    return Math.max(1, parseFlexibleNumber(prefixBare[1]));
  }
  const localNumberFirst = line.slice(dimensionStart, itemEnd).match(new RegExp(`${number}\\s*${quantityUnit}`, "i"));
  if (localNumberFirst) {
    return Math.max(1, parseFlexibleNumber(localNumberFirst[1]));
  }
  const suffixNumberFirst = suffix.match(new RegExp(`${number}\\s*${quantityUnit}`, "i"));
  if (suffixNumberFirst) {
    return Math.max(1, parseFlexibleNumber(suffixNumberFirst[1]));
  }
  const prefixMatch = prefix.match(new RegExp(`${number}\\s*${quantityUnit}[^\\dA-Za-z]*$`, "i"));
  if (prefixMatch) {
    return Math.max(1, parseFlexibleNumber(prefixMatch[1]));
  }
  const suffixTokenFirst = suffix.match(new RegExp(`(?:\\*|x|×|qty|quantity|数量|件数)\\s*[:：=#-]?\\s*${number}\\b`, "i"));
  if (suffixTokenFirst) {
    return Math.max(1, parseFlexibleNumber(suffixTokenFirst[1]));
  }
  return 1;
}

function buildWeightUnitPattern(config: QuoteWorkbenchConfig): string {
  const units = new Set([
    ...config.parser.weight_units,
    "kg",
    "kgs",
    "kilogram",
    "kilograms",
    "公斤",
    "千克",
    "lb",
    "lbs",
    "pound",
    "pounds",
    "磅",
    "g",
    "gram",
    "grams",
    "克",
    "mt",
    "m.t.",
    "t",
    "tonne",
    "tonnes",
    "metric ton",
    "metric tons",
  ]);
  return Array.from(units)
    .sort((left, right) => right.length - left.length)
    .map(escapeRegex)
    .join("|");
}

function normalizeLabeledDimensions(value: string): string {
  const number = `(${NUMBER_TOKEN_SOURCE})`;
  const unit = `(${DIMENSION_UNIT_SOURCE})?`;
  const gap = String.raw`[\s,，;；/|*x×-]*`;
  const lwhPattern = new RegExp(
    String.raw`\bL\s*/\s*W\s*/\s*H\s*[:：=]?\s*${number}\s*(?:/|\*|x|×)\s*` +
      String.raw`${number}\s*(?:/|\*|x|×)\s*${number}\s*${unit}`,
    "gi",
  );
  const prefixPattern = new RegExp(
    String.raw`(?:\bL(?:ength)?|长)\s*[:：=]?\s*${number}\s*${unit}${gap}` +
      String.raw`(?:\bW(?:idth)?|宽)\s*[:：=]?\s*${number}\s*${unit}${gap}` +
      String.raw`(?:\bH(?:eight)?|高)\s*[:：=]?\s*${number}\s*${unit}\s*${unit}`,
    "gi",
  );
  const suffixPattern = new RegExp(
    String.raw`${number}\s*${unit}\s*[（(]?\s*(?:L|长)\s*[）)]?\s*(?:\*|x|×)\s*` +
      String.raw`${number}\s*${unit}\s*[（(]?\s*(?:W|宽)\s*[）)]?\s*(?:\*|x|×)\s*` +
      String.raw`${number}\s*${unit}\s*[（(]?\s*(?:H|高)\s*[）)]?\s*${unit}`,
    "gi",
  );
  const replace = (
    _match: string,
    length: string,
    lengthUnit: string | undefined,
    width: string,
    widthUnit: string | undefined,
    height: string,
    heightUnit: string | undefined,
    overallUnit: string | undefined,
  ) => {
    const fallbackUnit = overallUnit ?? "";
    return [
      `${parseFlexibleNumber(length)}${lengthUnit ?? fallbackUnit}`,
      `${parseFlexibleNumber(width)}${widthUnit ?? fallbackUnit}`,
      `${parseFlexibleNumber(height)}${heightUnit ?? fallbackUnit}`,
    ].join("x");
  };
  const replaceLwh = (
    _match: string,
    length: string,
    width: string,
    height: string,
    overallUnit: string | undefined,
  ) => [length, width, height]
    .map((item) => `${parseFlexibleNumber(item)}${overallUnit ?? ""}`)
    .join("x");

  let normalized = value
    .replace(lwhPattern, replaceLwh)
    .replace(prefixPattern, replace)
    .replace(suffixPattern, replace);
  const labeledValuePattern = new RegExp(
    String.raw`(\b(?:L(?:ength)?|W(?:idth)?|H(?:eight)?)\b|长|宽|高)\s*[:：=]?\s*${number}\s*${unit}`,
    "gi",
  );
  const matches = Array.from(normalized.matchAll(labeledValuePattern));
  const dimensions = new Map<"length" | "width" | "height", RegExpMatchArray>();
  for (const match of matches) {
    const label = match[1].toLowerCase();
    const name = label.startsWith("l") || label === "长"
      ? "length"
      : label.startsWith("w") || label === "宽"
        ? "width"
        : "height";
    if (!dimensions.has(name)) {
      dimensions.set(name, match);
    }
  }
  if (dimensions.size !== 3) {
    return normalized;
  }
  const fallbackUnit = [...matches].reverse().find((match) => match[3])?.[3] ?? "";
  const replacement = (["length", "width", "height"] as const)
    .map((name) => {
      const match = dimensions.get(name)!;
      return `${parseFlexibleNumber(match[2])}${match[3] ?? fallbackUnit}`;
    })
    .join("x");
  const selectedMatches = Array.from(dimensions.values());
  const start = Math.min(...selectedMatches.map((match) => match.index ?? 0));
  const end = Math.max(...selectedMatches.map((match) => (match.index ?? 0) + match[0].length));
  normalized = `${normalized.slice(0, start)}${replacement}${normalized.slice(end)}`;
  return normalized;
}

function toCm(value: number, unit: string | undefined): number {
  const normalized = (unit || "cm").toLowerCase().replace(/[.\s]/g, "");
  let converted = value;
  if (["mm", "mms", "millimeter", "millimeters", "millimetre", "millimetres", "毫米"].includes(normalized)) {
    converted = value / 10;
  } else if (["m", "meter", "meters", "metre", "metres", "米"].includes(normalized)) {
    converted = value * 100;
  } else if (["in", "inch", "inches", "\"", "英寸"].includes(normalized)) {
    converted = value * 2.54;
  } else if (["ft", "foot", "feet", "英尺"].includes(normalized)) {
    converted = value * 30.48;
  }
  return Math.round((converted + Number.EPSILON) * 10_000) / 10_000;
}

function inferDimensionUnit(values: number[]): string | undefined {
  const dimensions = values.filter((value) => Number.isFinite(value) && value > 0);
  if (dimensions.some((value) => value > 500)) {
    return "mm";
  }
  if (
    dimensions.length === 3 &&
    Math.max(...dimensions) <= 10 &&
    dimensions.filter((value) => value < 1).length >= 2
  ) {
    return "m";
  }
  return undefined;
}

function normalizeCargoText(value: string): string {
  return value
    .normalize("NFKC")
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
  if (!cargoItems.some(hasCompleteDimensions)) {
    risks.push("已识别汇总件数、体积和重量，但原文未提供单件尺寸。");
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
