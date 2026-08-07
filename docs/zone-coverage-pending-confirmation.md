# Zone 覆盖补全:待业务确认清单

> 2026-08-07 从 493 条历史订单共识别 216 个 FSA,当前查询表已覆盖 **189 个(88%)**。
> 其中 101 个通过"同城锚点推导"直接补录(见 `scripts/maintain_zone_reference.py` 的 `_BACKFILL_RULES`,
> 每条均带锚点证据 note)。本清单是**剩余 27 个无可靠锚点的 FSA**,需要业务/运营确认 Zone 后补录。
>
> 确认方式:直接修改 `scripts/maintain_zone_reference.py` 的 `CONFIRMED_RULES`
> (note 写确认依据),然后运行 `python3 scripts/maintain_zone_reference.py --write`。

## 待确认清单(27 个)

| FSA | 城市 | 省 | 建议 Zone | 置信度 | 依据 |
|---|---|---|---|---|---|
| V2W | MAPLE RIDGE | BC | 5 | 高 | 大温东端,邻近 COQUITLAM(V3B)=5、LANGLEY=5 |
| V3Y | PITT MEADOWS | BC | 5 | 高 | 大温东端,紧邻 COQUITLAM/Maple Ridge(历史订单曾匹配 Zone12,判断为旧表错误,不建议采用) |
| T8H | SHERWOOD PARK | AB | 8 | 中 | 埃德蒙顿东郊,邻近 ARDROSSAN(T8E)=8 |
| T9N | BONNYVILLE | AB | 9 | 中低 | 东北区,邻近 ATHABASCA(T9S)=9 |
| N2V | WATERLOO | ON | 5 | 高 | 紧邻 KITCHENER(N2H)=5、CAMBRIDGE=5(滑铁卢地区同区) |
| L8J | STONEY CREEK | ON | 5 | 中 | 汉密尔顿东郊,HAMILTON(L8N/L8R/L9C)=5 |
| L3K | PORT COLBORNE | ON | 5 | 中 | 尼亚加拉东端,邻近 ST CATHARINES(L2W)=5 |
| N5A | STRATFORD | ON | 5 | 低 | 伦敦东北 ~50km,同区参照 CAMBRIDGE=5 / LONDON=5;也可能 6 |
| K4B | NAVAN | ON | 7 | 中 | 渥太华东郊,邻近 ORLÉANS(K1W)=7 |
| K4K | ROCKLAND | ON | 7 | 中 | 渥太华东北,邻近 ORLÉANS(K1W)=7 |
| L4P | KESWICK | ON | 6 | 低 | 约克区北/SIMCOE 湖南岸,参考 BALA(P0C)=6 |
| P1L | BRACEBRIDGE | ON | 8 | 低 | 马斯科卡,参考 BONFIELD(P0H)=8 / CACHE BAY(P0H)=10,待确认 |
| L6H / L6J / L6M | OAKVILLE | ON | 1 或 3 | 低 | 表内 MISSISSAUGA=1、MILTON(L9E)=1 已按 Zone1 报价;但 Oakville 南端临湖,可能按 Zone3(Halton)。**必须确认** |
| L7L / L7T | BURLINGTON | ON | 1 或 3 | 低 | 同 Oakville,紧邻 Zone1 城市但地理靠西,待确认 |
| G1N / G1P / G2C | QUÉBEC | QC | 8 | 低 | 省会,距蒙特利尔 ~250km;同省参考 CHICOUTIMI(G7H)=8、BOISCHATEL(G0A)=8;也可能 7/9 |
| J1L | SHERBROOKE | QC | 8 | 中 | 东镇,邻近 ASBESTOS(J1T)=8 |
| J7C | BLAINVILLE | QC | 7 | 高 | 蒙特利尔北郊,紧邻 BOISBRIAND=7、TERREBONNE(J6Y)=7 |
| S6H | MOOSE JAW | SK | 6 | 中低 | REGINA(S4N)=5 以西 ~70km,参考 CRAIK(S0G)=5 / BROADVIEW(S0G)=6 |
| S6V | PRINCE ALBERT | SK | 7 | 低 | SK 中部偏北,参考 CLAVET(S0K)=7 |
| R2X / R3E / R3H | WINNIPEG | MB | 5 | 中 | 同城多数 FSA(R2P/R3T)=5;仅 R2C(东北特定区)=12 经生产审计确认。市中心区建议 5 |
| T4C | COCHRANE | AB | 2 | 已补录 | 订单同城证据 ROCKY VIEW COUNTY=2;邻近 AIRDRIE/OKOTOKS=2 |

## 补录后自检

1. 更新后运行 `python3 scripts/maintain_zone_reference.py --write`,确认
   `confirmed_rules_upserted` 与 `final_records` 增加。
2. 运行 `python3 -m pytest -q tests/api/test_zone_quotes.py tests/quote-engine/test_zone_engine_oversize.py`,
   确认 Zone 查表链路无回归。
3. 预期覆盖:27 个确认后,历史订单 FSA 覆盖率 189/216 → 216/216(100%)。

## 备注

- 本清单全部基于地理邻近与同城锚点**推断**,不是承运商确认口径;Zone 划分以佳邮国际 Zone
  票价表分区为准,确认时优先查对票价表 zone 分布。
- 补录的 `match_level` 建议用 `manual_confirmation`,note 注明确认日期与确认人。
