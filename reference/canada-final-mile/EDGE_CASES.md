# 加拿大尾程派送特殊规则与异常案例

本文件只在 `SOP_QUICK.md` 命中特殊场景时读取。正常报价不要把本文件整段塞入上下文。

## 1. BC 旧 origin 覆盖

BC 全境按 Calgary 派送。若旧 Zone 表显示 Toronto，视为 stale origin，按省份规则覆盖。

已知修正：

| FSA | 城市 | 旧错误 | 当前规则 |
| --- | --- | --- | --- |
| V3E | Coquitlam | Zone12 Toronto | Zone5 Calgary |
| V5N | Vancouver | Zone10 Toronto | Zone5 Calgary |
| V2S | Abbotsford | Zone12 Toronto | Zone5 Calgary |
| V3B | Coquitlam | Zone12 Toronto | Zone5 Calgary |
| V4B | White Rock | B4P/BC + Zone12 Toronto（跨省无效锚点） | Zone5 Calgary |
| V4C | Delta | K0E/BC + Zone10 Toronto（无关跨省脏记录） | Zone5 Calgary |

`B4P` 属于 Nova Scotia，不能作为 White Rock, BC 的城市回退锚点。White Rock
必须使用 `V4B + WHITE ROCK + BC -> Calgary Zone5` 的人工修正规则。

`K0E` 属于 Ontario，不是 “Delta, BC 的旧锚点”，而是一条与目的地无关的跨省脏记录。
该记录必须在原始 JSON 质量门禁中报错，并在运行库中保持停用；Delta 使用
`V4C + DELTA + BC -> Calgary Zone5` 精确规则。

## 2. FSA 缺失回退

当邮编前三位不在 Zone 表中：

1. 用完整邮编在 `canadapostalcodeslist(1).json` 确认 preferred city。
2. 查同城市+同省份已知锚点。
3. 优先选择符合省份始发仓规则的锚点。
4. 没有可靠锚点时，转供应商确认。

示例：`V3W4Y8` 完整邮编确认 `SURREY`；`V3W` 缺失；可用同城市锚点 `V4N SURREY BC -> Zone5 Calgary`。

## 3. split-record 邮编

同一 FSA 对应多个城市或多个 Zone 时，必须按实际城市和地址证据精确匹配；不能默认取第一条。

| FSA | 已知记录 | 处理 |
| --- | --- | --- |
| T0E | GRANDE CACHE / WEST COVE / DUFFIELD 等 | 强制按实际城市确认，冲突时转人工 |
| L0P | Norval / Campbellville / Moffat 等 | 按实际城市确认 |
| T1X | Calgary / Chestermere / Rocky View County 等 | 注意 Calgary 201环线内外 |

双索引冲突处理：

- by_postal_prefix 与 by_city 偏差小于 1 个 Zone：优先 by_postal_prefix。
- 偏差大于等于 2 个 Zone：转人工确认。
- split-record：实际城市优先，仍冲突则转人工确认。

## 4. Calgary 201 环线

AB Calgary 区域需区分 201 号公路/Stoney Trail 环线内外。

- Calgary 市区且位于环线内：Zone 1。
- 环线外东：Chestermere、Strathmore、Janet 等，通常 Zone 3。
- 环线外北：Airdrie、Crossfield，通常 Zone 2-3。
- 环线外西：Cochrane、Bragg Creek，通常 Zone 3。
- 环线外南：Okotoks、High River，通常 Zone 2。
- 位于环线边界时，保守按环线外处理。

## 5. 农村/农场/湖边住宅关键词

以下关键词命中时，默认按住宅/私人地址处理，并加 `50USD/票`：

- 农村道路：`8th Line`、`9th Line`、`10th Line`、`Concession Road`、`Concession Line`
- 草原道路：`Range Road`、`Township Road`
- 邮政线路：`Rural Route`、`RR`
- 乡村物业：`Farm`、`Ranch`、`Estate`、`Manor`
- 度假物业：`Cottage`、`Cabin`、`Chalet`
- 湖边/海边/度假区：`Marine`、`Lake`、`Bay`、`Beach`、`Crescent`、`Cove`、`Harbour`、`Pier`、`Island`、`River`、`Creek`

强商业证据可以推翻关键词，但必须有明确地点证据。

## 6. 包装特殊案例

### 编织袋/柔性包装

同时满足：

- 件数 >= 50
- 编织袋/柔性包装
- 可堆叠

走包干价模式，约 `$580 USD/柜`，不按托数报价。

历史反例：76 件编织袋按 152 托报价是错误，应走包干价。

### 木箱

- 木箱每件至少 1 托。
- 任一单件长度 > 120cm 时，每件 2 托。
- 不允许用纸箱体积/重量规则低估木箱托数。

历史反例：V2C Kamloops 7 件木箱应按 7 托查表。

## 7. 禁用旧规则

以下规则已废弃，实时报价不得使用：

- 默认商业地址。
- `Zone4+` 才加住宅费的口径。
- 标注“待验证”后继续报价。
- `$643 CAD` 当作 `$643 USD`。
- CAD/USD 1:1 简化。
- 按每托单价或里程估基础价。
- Zone 线性 `+1/+2/+3` 外推。

## 8. 大托数和外推

表内价格优先。表外或超过已确认范围时，不要擅自套用未确认外推。

已知但需谨慎的历史口径：

- Toronto Zone 1：26 托封顶基础价 `$345`，超出部分 `$30/托`。
- Toronto Zone 2：超 26 托按 `$30/托` 叠加。
- 其他 Zone 的外推曾在旧文档出现“待确认”，不能当作强规则。

遇到大托数、表外托数、外推口径不明确：转供应商确认。
