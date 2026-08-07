# North America Oversize Pallet Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有加拿大尾程 Zone 报价链路中落地 NA_OVERSIZE_TEMP_V1 超大件算托规则：以实际搬运单元计算尺寸托数，以整票重量计算重量托数，以客户明确托数作为下限；内部使用真实尺寸、体积、重量和叠放状态校验 26 尺/53 尺车辆；普通销售/客户输出只呈现最终计费托数或人工状态，内部审计保留可复算的完整依据。本计划只覆盖开发、测试、本地/测试数据库验证，不执行生产环境发布。

**Architecture:** 扩展现有 ZoneQuoteRequest -> ZoneQuoteEngine -> quote_service -> API/UI 路径，不建立第二套报价流程。新增独立的超大件领域模型、可发布规则快照和确定性车辆排布模块；ZoneQuoteResult 作为内部结果保留托数分解、车辆和附加费，API 通过 allowlist DTO 只返回普通报价所需字段。AI 提取器只负责把已有货物明细映射为实际搬运单元，缺少尺寸/单重时 fail closed；客户总箱数只进入容差核对，不进入托位乘法。

**Tech Stack:** Python 3.11、Pydantic 2、Decimal、FastAPI、SQLAlchemy/Alembic、Pytest、React 18、TypeScript、Vite、Vitest。

---

## Task 1: 建立超大件领域模型和可配置默认值

**Files:**

- Create: packages/quote_engine/oversize_models.py
- Create: packages/quote_engine/oversize_config.py
- Create: tests/quote-engine/test_oversize_config.py
- Modify: packages/quote_engine/__init__.py

- [ ] 先写配置契约测试，确认当前模块不存在时测试失败：

  - 标准托盘固定为 121.92 × 101.60 cm，面积为 12387.072 cm²。
  - 默认扩托触发线为长边 150 cm 或短边 122 cm，首次轻度/中度分档为 135/110 cm 和小于 150/小于 122 cm。
  - 扩托方向容差为 5 cm，面积整数容差为 2%。
  - 重量基准 500 kg/托，高板正常上限 180 cm、自动上限 210 cm，单元重量自动上限 1000 kg。
  - 默认足迹边界费 25、中度超底盘费 50、高板费 50、重货费 75，金额保留报价币种的 Decimal。
  - 内置四个车辆档案：26_non_cdl、26_cdl、53_dry_van；尺寸、体积、载重、常规托数和紧密托数必须与规格文档第 11 节完全一致。
  - 规则模型拒绝负数、触发线倒置、common_pallet_limit > tight_pallet_limit、缺少车辆代码以及 max_auto_vehicles 不在 1..3 的配置。
  - HandlingUnitInput 拒绝数量小于 1、尺寸/单重为负、叠放状态为 stackable 但没有至少两层和承重上限的输入；unknown/non_stackable 不要求叠放字段。

~~~bash
pytest -q tests/quote-engine/test_oversize_config.py
~~~

预期：测试因缺少 packages.quote_engine.oversize_config 和领域模型而失败。

- [ ] 实现受控输入模型，所有数值字段使用 Decimal，extra="forbid"，不在模型层隐式把客户箱数变成搬运单元数量：

~~~python
class HandlingUnitInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    quantity: int = Field(ge=1)
    packaging_type: str
    length_cm: Decimal = Field(gt=0)
    width_cm: Decimal = Field(gt=0)
    height_cm: Decimal = Field(gt=0)
    unit_weight_kg: Decimal = Field(gt=0)
    cbm: Decimal | None = Field(default=None, gt=0)
    contained_customer_pieces: int | None = Field(default=None, ge=0)
    stackability: Literal["stackable", "non_stackable", "unknown"] = "unknown"
    max_stack_layers: int | None = Field(default=None, ge=2)
    max_top_load_kg: Decimal | None = Field(default=None, gt=0)
    floor_rotation_allowed: bool = True
    source_span: str | None = None

    @model_validator(mode="after")
    def validate_stackability(self) -> "HandlingUnitInput":
        if self.stackability == "stackable" and (
            self.max_stack_layers is None or self.max_top_load_kg is None
        ):
            raise ValueError("stackable handling units require max_stack_layers and max_top_load_kg")
        return self
~~~

- [ ] 在 oversize_config.py 建立不可变默认值模型：

  - OversizePalletRuleConfig：规则 ID NA_OVERSIZE_TEMP_V1、托盘尺寸、三段首次分档、扩托容差、面积容差、重量/高度阈值、四类附加费、箱数/重量/体积核对容差、最大自动车辆数、排布搜索节点上限、车辆档案列表。
  - VehicleProfile：code、label、内部长宽高、有效体积、载重、common_pallet_limit、tight_pallet_limit、可选的可比基础价；车辆尺寸统一为厘米和立方米。
  - default_oversize_pallet_rule() 返回深拷贝式新实例，避免测试或配置编辑修改全局默认对象。
  - 默认车辆数据固定为：26 尺非 CDL 762×243.84×243.84 cm / 45.3 m³ / 4536 kg / 12 / 14；26 尺 CDL 同尺寸体积、7711 kg / 12 / 14；53 尺干货车 1600.2×250.19×279.4 cm / 110.4 m³ / 19958 kg / 26 / 30。
  - 默认数据容差为箱数 max(2,5%)、重量 max(50 kg,5%)、体积 max(0.5 m³,10%)；搜索节点上限取确定性配置值并在超限时返回 INCONCLUSIVE，不能把启发式失败写成“证明装不下”。

- [ ] 从 packages.quote_engine 导出 HandlingUnitInput、OversizePalletRuleConfig、VehicleProfile 和 default_oversize_pallet_rule，让后续 Zone/API 模块只从领域模块导入。
- [ ] 运行配置测试，预期全部通过；提交第一笔独立变更。

~~~bash
pytest -q tests/quote-engine/test_oversize_config.py
git add packages/quote_engine/oversize_models.py packages/quote_engine/oversize_config.py packages/quote_engine/__init__.py tests/quote-engine/test_oversize_config.py
git commit -m "feat(quote): add configurable oversize pallet domain models"
~~~

## Task 2: 用实际搬运单元重写尺寸、重量和附加费计算

**Files:**

- Create: tests/quote-engine/test_pallet_calculator.py
- Modify: packages/quote_engine/pallet_calculator.py

- [ ] 先写失败测试，测试必须使用多行 HandlingUnitInput，不能只传总件数和全局最长边：

  - 标准 121.92×101.60 为 1 托、无足迹费。
  - 122×102 为 1 托、足迹费 25；149×121 为 1 托、中度费 50。
  - 150×100、150×122 为 2 托；243×100 为 2 托且无边界费；245×100、248.84×100、248.84×101.6 为 2 托且只收一次 25；249×100 为 3 托。
  - 200×130 木箱为 3 托，273×100 为 3 托，230×150 为 3 托，200×200 为 4 托；断言不能使用长槽数乘短槽数。
  - 同一行 quantity=7 的超大件只把该行乘 7；历史回归“总箱数 36、实际长件 7”结果为 14 托而不是 72 托。
  - 改变客户总箱数但不改变搬运单元行时，尺寸托数不变；完整 contained_customer_pieces 与总箱数差异在 max(2,5%) 内继续，刚超过则人工。
  - 重量按明细单重乘数量求和，声明总重量在容差内取较大值，重量托数为 ceil(calculation_weight/500)；700 kg 单元收重货费 75，1000 kg 仍可自动，1000.01 kg 人工。
  - 高度 180 正常、180.01..210 收高板费 50 且不增加尺寸托数、210.01 人工。
  - stackability 未知或不可叠放不改变计费托数；明确可叠放只进入内部车辆列计算，不降低计费托数。
  - 没有搬运单元、尺寸为空、单重为空、单位未归一或整行无效时，返回人工风险码；不得回退到 ceil(CBM/2)、piece_count*2 或全局最长边乘法。
  - 只改变 CBM 但保持搬运单元尺寸不变时，最终计费托数不因 CBM 直接变化；CBM 只参与车辆容量和容差核对。

~~~bash
pytest -q tests/quote-engine/test_pallet_calculator.py
~~~

预期：测试先因现有聚合公式和旧长件倍乘逻辑失败。

- [ ] 将 calculate_billing_pallets 改为接收 handling_units: Sequence[HandlingUnitInput] 和已发布规则快照，保留旧函数名供 Zone 调用，但移除旧常量 HARD_LONG_PIECE_THRESHOLD_CM、SUSPICIOUS_LONG_PIECE_MULTIPLIER 对最终结果的影响。
- [ ] 对每一行先归一化真实外部尺寸、单重和单件 CBM：

~~~python
floor_long = max(unit.length_cm, unit.width_cm)
floor_short = min(unit.length_cm, unit.width_cm)
derived_unit_cbm = unit.length_cm * unit.width_cm * unit.height_cm / Decimal("1000000")
line_quantity = unit.quantity
~~~

  保留原始长宽方向用于 floor_rotation_allowed=false 的车辆校验；计费分档始终按归一化地板长短边，不能横放高度。

- [ ] 按设计顺序实现首次扩托分档：标准档、135/110 轻度档、小于 150/小于 122 中度档；进入扩托后，对两个方向分别执行 effective_axis，仅把 0 < remainder <= 5 压回整数托位，真实尺寸仍保留在内部排布输入。
- [ ] 按 area_ratio 的相对整数 2% 容差计算面积托位，并用 max(2, long_slots, short_slots, area_slots) 得到单个搬运单元托数；边界容差的长短边同时命中只记一个足迹类别。
- [ ] 按行汇总 line_size_pallets = unit_size_pallets * quantity，严格禁止使用客户总箱数或全票件数乘任意超长倍数。
- [ ] 计算重量/箱数/体积核对：

  - 箱数只有所有行都提供 contained_customer_pieces 时才核对；超过 max(2,5%) 返回 customer_piece_count_mismatch，未完整提供则只记录 customer_piece_count_check_skipped。
  - 明细重量与申报总重量超过 max(50 kg,5%) 返回 declared_weight_out_of_tolerance；容差内采用较大值作为计费/车辆校验重量。
  - 尺寸推导体积与申报 CBM 超过 max(0.5 m³,10%) 返回 declared_volume_out_of_tolerance；容差内采用较大值，仅用于车辆校验，不换算托数。
  - 申报值高于明细且在容差内时，按比例缩放内部车辆分配权重/体积，不对单件重量分档或托数先做四舍五入。

- [ ] 计算最终托数 max(total_size_pallets, weight_pallets, explicit_pallet_count or 0)；内部结果新增 surcharges、internal_trace、risk_tags，追踪每行有效尺寸、方向托位、面积托位、边界费、行托数、重量托数、核对状态和规则版本。
- [ ] 任何硬阻断（缺单元/尺寸/单重、单位不明、箱数/重量/体积超容差、单元重于 1000 kg、单元高于 210 cm）都返回 manual_review_required=True，并把 billing_pallets 仅作为内部候选；公共 DTO 后续必须清空该候选。
- [ ] 运行尺寸/重量回归测试并提交。

~~~bash
pytest -q tests/quote-engine/test_pallet_calculator.py
git add packages/quote_engine/pallet_calculator.py tests/quote-engine/test_pallet_calculator.py
git commit -m "feat(quote): calculate pallets from handling units"
~~~

## Task 3: 实现确定性的车辆排布和三态装车校验

**Files:**

- Create: packages/quote_engine/vehicle_packing.py
- Create: tests/quote-engine/test_vehicle_packing.py
- Modify: packages/quote_engine/pallet_calculator.py

- [ ] 先写车辆校验失败测试，固定以下行为：

  - 单个搬运单元任一允许方向都超过车辆地板或高度时，状态为 PROVEN_NOT_FIT，不能静默换算成更多计费托。
  - 总重量超过车辆载重或采用后的总 CBM 超过有效体积时为 PROVEN_NOT_FIT。
  - floor_rotation_allowed=true 尝试原始长宽和旋转 90°；为 false 只尝试客户原始长宽，计费仍按规范化长短边。
  - 小批量标准托/木箱在 26 尺内能通过二维排布；需要 53 尺时选择 53 尺；一辆车通过时即使达到紧密托数也只返回一辆并标记 tight_loading=true。
  - 26 尺非 CDL 与 CDL 尺寸/体积相同时按载重淘汰非 CDL；载重、体积和布局都可行时按“车辆数、可比基础价、总体积、载重、稳定车型代码”排序。
  - 搜索穷举证明无布局时为 PROVEN_NOT_FIT；搜索节点达到配置上限时为 INCONCLUSIVE，不能因启发式失败直接增加车辆。
  - 明确 stackable、层数和顶载后，只让堆叠列底层占地；未明确或缺少约束时按不可叠放。叠放列高度超过车辆高度时先减少层数，再回退不叠放，仍不可装才人工。
  - 自动车辆最多 3 辆；需要第 4 辆或所有候选均为 INCONCLUSIVE 时人工。

~~~bash
pytest -q tests/quote-engine/test_vehicle_packing.py
~~~

预期：测试因缺少排布模块而失败。

- [ ] 在 vehicle_packing.py 定义内部结果：

~~~python
class PackingStatus(StrEnum):
    FIT = "FIT"
    PROVEN_NOT_FIT = "PROVEN_NOT_FIT"
    INCONCLUSIVE = "INCONCLUSIVE"

@dataclass(frozen=True)
class VehiclePackingResult:
    status: PackingStatus
    vehicle_code: str
    vehicle_count: int
    floor_columns: int
    volume_cbm: Decimal
    payload_kg: Decimal
    tight_loading: bool
    placements: tuple[dict[str, object], ...]
    reason_codes: tuple[str, ...]
~~~

- [ ] 实现确定性 2D 排布：按实际外部地板面积、长边、短边和稳定输入序号降序；候选位置按 (y, x, orientation) 排序；对每个候选递归尝试所有可行放置，穷举完成才允许 PROVEN_NOT_FIT，节点上限耗尽返回 INCONCLUSIVE。任何算法分支不得使用随机数、当前时间或未排序的集合遍历。
- [ ] 实现堆叠列生成：只合并相同地板 footprint、兼容旋转方向且满足层数、逐层顶载和车辆有效高度的单元；列的总重量/体积进入车辆校验，计费单元数量和尺寸托数保持不变。
- [ ] 实现四项硬校验：单元可装、二维布局、有效体积、车辆载重；对 26 尺非 CDL、26 尺 CDL、53 尺按配置档案尝试，并记录每个候选档案的状态。
- [ ] 在 calculate_billing_pallets 中调用车辆选择，保存 vehicle_profiles_checked、选中车型、车辆数、地板列、紧密装载、体积、载重和状态到 internal_trace；车辆不足或不确定时转人工，不能通过增加虚拟托数“解决”车辆问题。
- [ ] 运行车辆和托数联合测试，提交。

~~~bash
pytest -q tests/quote-engine/test_vehicle_packing.py tests/quote-engine/test_pallet_calculator.py
git add packages/quote_engine/vehicle_packing.py packages/quote_engine/pallet_calculator.py tests/quote-engine/test_vehicle_packing.py
git commit -m "feat(quote): validate oversize loading with deterministic vehicle packing"
~~~

## Task 4: 把搬运单元、内部轨迹和公共结果接入 Zone Quote Engine

**Files:**

- Modify: packages/quote_engine/zone_models.py
- Modify: packages/quote_engine/zone_engine.py
- Modify: packages/quote_engine/zone_pricing.py
- Create: tests/quote-engine/test_zone_engine_oversize.py
- Modify: tests/quote-engine/test_zone_pricing.py

- [ ] 先写接口失败测试：

  - ZoneQuoteRequest 接受 handling_units 数组并拒绝未知字段；每行数量、尺寸和单重按 HandlingUnitInput 校验。
  - 没有 handling_units 或只有聚合汇总行时，Zone 引擎返回人工风险码，不再产生旧的 ceil(CBM/2) 结果。
  - 多个搬运单元的最终托数只按行数量汇总，重量托数仍按整票重量。
  - ZoneQuoteResult 内部包含 pallet_breakdown、internal_trace、附加费类别和规则快照；这些字段不进入新的公共响应模型。
  - 超大件 surcharge 传给价格计算器后计入总价；同一类别只收最高档，不同类别可相加，按行数量乘附加费。

- [ ] 修改 ZoneQuoteRequest：保留 cbm、weight_kg、piece_count、explicit_pallet_count 作为订单级核对字段，新增 handling_units: list[HandlingUnitInput] = Field(default_factory=list)；保留旧字段仅用于兼容输入/审计，不允许旧字段决定托位。
- [ ] 扩展 ZoneQuoteResult：

  - 增加 internal_trace: dict[str, object]，用于保存规则 ID/发布版本/完整配置快照、每行计算、车辆校验、核对状态和人工原因。
  - pallet_breakdown 只存内部整数分解；附加费进入内部 accessorials。
  - 添加 to_public() 或同等显式转换方法，人工状态时不把内部候选托数暴露给公共结果。

- [ ] 新增 ZoneQuotePublicResult（allowlist），只包含现有报价流程真正需要的 quote_id、billing_pallets、total_price_usd、sales_note、manual_review_required 和受控的 public_flags；不包含 pallet_breakdown、车辆、附加费明细、规则版本、容差、match_trace、供应商/始发仓细节或人工内部原因。成功时 billing_pallets 为最终值；人工时为 null。
- [ ] 修改 ZoneQuoteEngine.__init__ 接受 oversize_rule 和 oversize_rule_version，在 quote() 中把搬运单元和规则快照传给 calculate_billing_pallets；保留邮编/Zone 查表顺序和现有始发仓安全校验。
- [ ] 确保 Zone 未命中、价格未命中、关闭价格和超大件人工都保留内部托数候选与原因，但 to_public() 统一输出人工状态而非推测托数。
- [ ] 修改 calculate_zone_price 增加 additional_accessorials: Mapping[str, Decimal] | None 参数；计算器先按类别得到 oversize_footprint_fee_usd、oversize_height_fee_usd、oversize_heavy_fee_usd，价格模块只负责合计和金额归一化，不重新判断托数。
- [ ] 添加测试断言：公共结果不存在内部字段；200×130 cm/900 kg 的内部结果为 3 托并收重货费，公共结果只含 3 托和正常报价字段；人工结果公共 billing_pallets is None。
- [ ] 运行引擎/定价测试并提交。

~~~bash
pytest -q tests/quote-engine/test_zone_engine_oversize.py tests/quote-engine/test_zone_pricing.py
git add packages/quote_engine/zone_models.py packages/quote_engine/zone_engine.py packages/quote_engine/zone_pricing.py tests/quote-engine/test_zone_engine_oversize.py tests/quote-engine/test_zone_pricing.py
git commit -m "feat(quote): connect handling units and public pallet result"
~~~

## Task 5: 建立可发布、不可变的超大件规则配置和数据库快照

**Files:**

- Modify: apps/api/db/models.py
- Create: migrations/versions/0022_add_oversize_pallet_rule_versions.py
- Create: apps/api/db/repositories/oversize_pallet_rule_repository.py
- Modify: apps/api/routes/quote_configs.py
- Create: tests/db/test_oversize_pallet_rule_repository.py
- Modify: tests/api/test_quote_configs.py

- [ ] 先写仓储/API 失败测试：

  - 没有数据库记录时运行时读取 default_oversize_pallet_rule()，规则 ID 为 NA_OVERSIZE_TEMP_V1。
  - 管理员可以读取/保存 draft、校验 draft、发布 draft；发布后生成递增数字版本和完整 JSON 快照。
  - 发布快照不可原地修改；再次修改必须生成新的 draft/发布版本，旧版本的 config_json 保持不变。
  - 非管理员只能按既有角色策略读取必要配置，不能保存、校验或发布超大件规则。
  - 规则校验拒绝触发线倒置、车辆缺失、车辆载重/体积非正数、最大自动车辆超过 3 等错误。
  - 发布快照能被运行时读取，报价审计中的 rule_version 和 config_snapshot 与发布时一致。

- [ ] 在 apps/api/db/models.py 新增 OversizePalletRuleVersion：

  - id 自增主键，rule_id、version 唯一索引组合，config_json JSON 非空，published_by、created_at、published_at。
  - 增加 status 仅允许 published 的历史快照；draft 仍由 QuoteRuleConfig 的 oversize_pallet_rule_draft JSON 记录保存，避免修改已发布行。

- [ ] 创建 Alembic 0022_add_oversize_pallet_rule_versions.py，down_revision="0021_fcl_quote_closed_loop"；升级创建快照表及索引，并写入一份规则 ID 为 NA_OVERSIZE_TEMP_V1、版本 1 的默认发布快照，降级只删除本迁移创建的索引/表。迁移中的默认 JSON 必须与 default_oversize_pallet_rule().model_dump(mode="json") 完全一致，不能依赖运行时网络或人工补录。
- [ ] 实现 OversizePalletRuleRepository，接口与现有 FCL 配置发布模式一致：get_draft()、save_draft()、validate_draft()、publish_draft(actor)、get_published()、admin_snapshot()；发布时用数据库 max(version)+1，并以 OversizePalletRuleConfig 校验完整快照。
- [ ] 在 apps/api/routes/quote_configs.py 增加：

  - GET /quote-configs/oversize-pallet-rule：返回 {draft, published, published_version}。
  - PUT /quote-configs/oversize-pallet-rule/draft：仅管理员。
  - POST /quote-configs/oversize-pallet-rule/validate：仅管理员，返回 valid/errors。
  - POST /quote-configs/oversize-pallet-rule/publish：仅管理员，返回发布配置和版本。

- [ ] 运行 SQLite 仓储/API 测试和 Alembic 语法检查，提交。

~~~bash
pytest -q tests/db/test_oversize_pallet_rule_repository.py tests/api/test_quote_configs.py
alembic heads
python -m compileall apps/api/db/repositories/oversize_pallet_rule_repository.py migrations/versions/0022_add_oversize_pallet_rule_versions.py
git add apps/api/db/models.py migrations/versions/0022_add_oversize_pallet_rule_versions.py apps/api/db/repositories/oversize_pallet_rule_repository.py apps/api/routes/quote_configs.py tests/db/test_oversize_pallet_rule_repository.py tests/api/test_quote_configs.py
git commit -m "feat(config): publish immutable oversize pallet rule snapshots"
~~~

## Task 6: 把已发布规则接入报价服务、审计和人工任务闭环

**Files:**

- Modify: apps/api/services/quote_service.py
- Modify: apps/api/services/ai_quote_service.py
- Modify: apps/api/routes/quotes.py
- Modify: apps/api/services/quote_logic_explainer.py
- Modify: apps/api/db/repositories/quote_audit_repository.py
- Modify: apps/api/db/repositories/learned_quote_rule_repository.py
- Create: tests/api/test_zone_quote_oversize_integration.py

- [ ] 在 calculate_zone_quote() 和 calculate_ai_auto_quote() 中用同一个 OversizePalletRuleRepository.get_published() 读取规则，构造 ZoneQuoteEngine；禁止一条路径读取 draft、另一条路径使用硬编码默认值。
- [ ] 在内部结果 internal_trace 中保存：

  - 原始 handling_units 和归一化后的每行数据；
  - 规则 ID、数字发布版本、完整配置快照；
  - 尺寸托数、重量托数、客户申报托数、最终托数；
  - 足迹/高板/重货附加费；
  - 叠放决策、实体地板列、车型候选、车辆数、体积和载重校验；
  - 数据容差结果、自动/人工状态和原因代码。

- [ ] 保持 QuoteAuditRepository.create_for_zone_quote() 和 ManualQuoteTaskRepository 接收完整内部 ZoneQuoteResult；审计 JSON 必须包含搬运单元而不是只有旧聚合字段，普通 API 返回前才转换公共 DTO。
- [ ] 修改 apps/api/routes/quotes.py：/quotes/zone-calculate 的 response_model 改为 ZoneQuotePublicResult，返回 to_public_zone_quote_result(internal_result)；通知、审计、学习候选仍使用内部结果。
- [ ] 修改 AIAutoQuoteResponse.quote_result 为公共 DTO；AI 服务在写审计/人工任务前使用内部结果，在响应/销售记录中使用 allowlist 公共结果。人工时不返回候选计费托数，不自动生成确定价格。
- [ ] 在 apply_learned_quote_if_available() 增加超大件硬阻断：handling_units_missing、handling_unit_dimensions_missing、handling_unit_weight_missing、declared_*_out_of_tolerance、oversize_vehicle_inconclusive、oversize_vehicle_not_fit 等风险码命中时，不得用历史学习托数/价格绕过当前人工确认；普通 Zone 未命中逻辑保持不变。
- [ ] 更新 quote_logic_explainer：内部解释可继续引用 pallet_breakdown 和车辆结果，但不把解释放入公共 DTO；确保 match_trace.quote_logic 只进入审计/内部页面。
- [ ] 集成测试覆盖直接 Zone API、AI API、审计记录、人工任务和学习规则阻断：真实明细完整时可报价；聚合汇总行进入人工且公共托数为空；历史学习规则不能将该人工结果改成成功报价。
- [ ] 运行集成测试并提交。

~~~bash
pytest -q tests/api/test_zone_quote_oversize_integration.py tests/api/test_zone_quotes.py tests/api/test_ai_auto_quote.py
git add apps/api/services/quote_service.py apps/api/services/ai_quote_service.py apps/api/routes/quotes.py apps/api/services/quote_logic_explainer.py apps/api/db/repositories/quote_audit_repository.py apps/api/db/repositories/learned_quote_rule_repository.py tests/api/test_zone_quote_oversize_integration.py
git commit -m "feat(api): use published oversize rules through quote workflow"
~~~

## Task 7: 修正 AI 提取和前端请求，使实际搬运单元完整传递

**Files:**

- Modify: packages/ai_assistant/quote_extractor.py
- Modify: packages/ai_assistant/prompts.py
- Modify: apps/api/services/ai_quote_service.py
- Modify: apps/web/src/api/client.ts
- Modify: apps/web/src/pages/QuotePage.tsx
- Modify: apps/web/src/utils/quoteParser.ts
- Create: tests/ai-assistant/test_oversize_cargo_items.py
- Modify: tests/api/test_ai_auto_quote.py

- [ ] 先写提取/适配失败测试：

  - 200×130 cm、900 kg 木箱生成一个完整搬运单元，后端得到 3 托。
  - 273×100 cm 生成一个完整搬运单元，后端得到 3 托。
  - “36 箱，其中 7 个长件”必须生成普通箱行和长件行，长件只按自身数量扩托。
  - “QTY/GW/CBM 只有汇总、没有尺寸”仍保留汇总 cargo item 以便审计，但 Zone Engine 返回人工；AI 不补造尺寸、单重、箱数、叠放能力。
  - cargo_items[].weight_kg 始终为单个搬运单元单重；total_weight_kg、total_cbm 只用于核对。

- [ ] 扩展 ExtractedCargoItem/CargoAgentExtraction 可选字段：contained_customer_pieces、stackability、max_stack_layers、max_top_load_kg、floor_rotation_allowed；只有原文明确给出时才填写，未给出保持 unknown/None，不由模型推断。
- [ ] 更新 CARGO_EXTRACTION_SYSTEM_PROMPT 和字段提取提示：明确“实际搬运单元是托位主计算输入；聚合行不得自动报价；客户总箱数只核对；缺尺寸/单重不得补造；堆放字段只有客户明确说明才写入”。保留现有单位转换和 source span 约束。
- [ ] 在 _zone_request_from_extraction() 中逐行映射 extraction.cargo_items 为 HandlingUnitInput；把顶层明确 is_stackable=true/false 作为未逐行声明时的栈状态，顶层为空则为 unknown；聚合行的空尺寸/空单重原样传递而不是删除。
- [ ] 更新 apps/web/src/api/client.ts：加入 HandlingUnitInput、公共 ZoneQuoteResult 类型和超大件配置类型；ZoneQuoteRequest 新增 handling_units；删除页面对 pallet_breakdown、match_trace、internal_note 的公共依赖，内部审计页面继续以 JsonValue 读取后端审计数据。
- [ ] 在 QuotePage.tsx/quoteParser.ts 中保留 AI 真实货物行和 source span；前端不把“客户箱数”重写成 handling-unit quantity，不把 aggregate summary row 转换成有效尺寸。直接 Zone 请求若由页面构造，发送每行数量、单长宽高和单重。
- [ ] 更新 AI 回归测试：聚合汇总不再断言返回 6 托候选，改为 manual_review_required=True、公共 billing_pallets is None，同时检查审计/人工任务内部保留缺失风险码。
- [ ] 运行提取器、AI API 和 TypeScript 类型检查，提交。

~~~bash
pytest -q tests/ai-assistant/test_oversize_cargo_items.py tests/ai-assistant/test_quote_extractor.py tests/api/test_ai_auto_quote.py
cd apps/web && npx tsc --noEmit && cd ../..
git add packages/ai_assistant/quote_extractor.py packages/ai_assistant/prompts.py apps/api/services/ai_quote_service.py apps/web/src/api/client.ts apps/web/src/pages/QuotePage.tsx apps/web/src/utils/quoteParser.ts tests/ai-assistant/test_oversize_cargo_items.py tests/api/test_ai_auto_quote.py
git commit -m "feat(quote): pass extracted handling units into oversize rules"
~~~

## Task 8: 实现超大件规则维护页面和普通结果最小展示

**Files:**

- Modify: apps/web/src/api/client.ts
- Modify: apps/web/src/pages/PricingSettingsPage.tsx
- Modify: apps/web/src/components/QuoteCalculationPanel.tsx
- Modify: apps/web/src/components/ResultCard.tsx
- Modify: apps/web/src/pages/AIQuotePage.tsx
- Create: apps/web/src/utils/quoteResultView.ts
- Create: apps/web/src/utils/quoteResultView.test.ts
- Modify: apps/web/package.json
- Modify: apps/web/package-lock.json

- [ ] 先写公共展示测试和 API 类型测试：

  - 成功结果的算托摘要严格为“计费托数：N”。
  - 人工结果严格为“需要人工确认”，不显示内部候选托数。
  - 普通结果工具函数不读取或输出 pallet_breakdown、车辆、附加费类别、规则版本和人工原因。

~~~bash
cd apps/web
npm install --save-dev vitest
npm run test -- src/utils/quoteResultView.test.ts
~~~

预期：测试先因 quoteResultView.ts 和 test 脚本不存在而失败；npm install 只更新前端测试依赖和锁文件。

- [ ] 新建 quoteResultView.ts，用 billing_pallets 和 manual_review_required 输出算托摘要；null 结果仍可由组件单独显示“待计算”，不得把内部 breakdown 作为 fallback。
- [ ] 在 QuoteCalculationPanel.tsx 移除“托数拆解”、车辆、规则和内部备注；保留现有商业报价合计和必要的乡村地址确认锁定，但算托结果区域只显示计费托数/人工状态，附加费区域不展开超大件类别和金额。
- [ ] 在 ResultCard.tsx 和 AIQuotePage.tsx 移除公共结果对 pallet_breakdown、match_trace、internal_note、matched_rule 的渲染；保留总报价、销售话术复制和人工状态。普通结果不显示始发仓/车辆/足迹/重量分解。
- [ ] 在 apps/web/src/api/client.ts 增加配置读写函数：getOversizePalletRule()、saveOversizePalletRuleDraft()、validateOversizePalletRule()、publishOversizePalletRule()；数字输入保留字符串到提交前由后端 Pydantic 精确校验。
- [ ] 在 PricingSettingsPage.tsx 增加“超大件规则”分区，复用现有轻软蓝灰管理页样式：

  - 展示当前 draft、已发布规则 ID/版本和最后发布时间。
  - 编辑标准托尺寸、首次分档、扩托容差、面积容差、重量/高度阈值、四类费用、数据核对容差、最大车辆数。
  - 展示并编辑 26 尺非 CDL、26 尺 CDL、53 尺干货车的尺寸/体积/载重/常规托数/紧密托数和可比基础价。
  - 提供“保存草稿”“校验草稿”“发布规则”三步操作；未通过服务端校验不能发布，发布后显示新版本并重新读取。
  - 明确标注这些是“可配置的暂行默认值”，不要在页面文案中写成承运商正式标准。

- [ ] 运行前端单测、类型检查和生产构建，提交。

~~~bash
cd apps/web
npm run test -- src/utils/quoteResultView.test.ts
npm run build
cd ../..
git add apps/web/src/api/client.ts apps/web/src/pages/PricingSettingsPage.tsx apps/web/src/components/QuoteCalculationPanel.tsx apps/web/src/components/ResultCard.tsx apps/web/src/pages/AIQuotePage.tsx apps/web/src/utils/quoteResultView.ts apps/web/src/utils/quoteResultView.test.ts apps/web/package.json apps/web/package-lock.json
git commit -m "feat(web): expose oversize rule config and minimal pallet output"
~~~

## Task 9: 更新现有 Zone、审计和回归夹具

**Files:**

- Modify: tests/api/test_zone_quotes.py
- Modify: tests/api/test_ai_auto_quote.py
- Modify: tests/api/test_quote_configs.py
- Modify: tests/db/test_quote_rule_config_repository.py
- Modify: tests/api/test_zone_quote_audit_tasks.py
- Modify: apps/web/src/pages/AuditPage.tsx
- Modify: apps/web/src/pages/ManualTasksPage.tsx

- [ ] 更新所有正常 Zone fixture：每个可自动报价的 payload 添加至少一条完整 handling_units（数量、长宽高、单重、包装类型），不能继续用只有 CBM/重量/件数的聚合 payload 伪造成功。
- [ ] 为公共响应添加字段泄露测试：

  - /quotes/zone-calculate 成功和人工响应均没有 pallet_breakdown、internal_trace、车辆、超大件费用类别、规则快照和 match_trace。
  - 成功响应包含计费托数和商业总价；人工响应只含人工状态，计费托数为空。
  - QuoteAuditLog.result_json 和人工任务 result_json 仍包含完整内部计算记录，以便运营复算。

- [ ] 更新现有 test_ai_aggregate_manual_required_still_returns_billing_pallet_estimate：改名为聚合数据人工测试，断言公共结果不显示候选托数，内部审计风险码表明缺实际搬运单元/尺寸。
- [ ] 添加固定业务回归：

  - 1 个 200×130 cm、900 kg 木箱最终 3 托；
  - 1 个 273×100 cm 最终 3 托；
  - 36 个客户箱但只有 7 个长件不超过 14 托；
  - 客户箱数从 36 改成 360、明细不变时尺寸托数不变；
  - 车辆能装 12/14/26/30 个实际托位时不把车辆数量乘到计费托数；
  - ceil(CBM/2) 对同一搬运单元输入变化不改变最终尺寸托数；
  - 缺价格矩阵、Zone 关闭、始发仓冲突的既有人工路径仍然人工，且不因新规则泄露内部候选托数。

- [ ] 审计/人工页面可以继续展示内部托数拆分和车辆信息，但在标题和文案中明确“内部审计”，不要复用普通销售 DTO；确保前端类型不再要求公共响应携带这些字段。
- [ ] 运行所有后端回归测试，提交。

~~~bash
pytest -q tests/api/test_zone_quotes.py tests/api/test_ai_auto_quote.py tests/api/test_quote_configs.py tests/db/test_quote_rule_config_repository.py tests/api/test_zone_quote_audit_tasks.py
git add tests/api/test_zone_quotes.py tests/api/test_ai_auto_quote.py tests/api/test_quote_configs.py tests/db/test_quote_rule_config_repository.py tests/api/test_zone_quote_audit_tasks.py apps/web/src/pages/AuditPage.tsx apps/web/src/pages/ManualTasksPage.tsx
git commit -m "test(quote): lock oversize regressions and public data boundary"
~~~

## Task 10: 完成迁移、全量验证和交付前审查

**Files:**

- Verify: docs/superpowers/specs/2026-08-03-north-america-oversize-pallet-rules-design.md
- Verify: docs/superpowers/plans/2026-08-03-north-america-oversize-pallet-rules.md

- [ ] 运行后端分层测试：

~~~bash
pytest -q tests/quote-engine/test_oversize_config.py tests/quote-engine/test_pallet_calculator.py tests/quote-engine/test_vehicle_packing.py tests/quote-engine/test_zone_engine_oversize.py tests/quote-engine/test_zone_pricing.py
pytest -q tests/db/test_oversize_pallet_rule_repository.py tests/db/test_quote_rule_config_repository.py
pytest -q tests/api/test_zone_quote_oversize_integration.py tests/api/test_zone_quotes.py tests/api/test_ai_auto_quote.py tests/api/test_quote_configs.py tests/api/test_zone_quote_audit_tasks.py
~~~

预期：全部通过；测试报告中必须包含关键边界值 150、122、5、2%、180、210、1000，以及 200×130=3、273×100=3、245×100=2+25。

- [ ] 运行全量 Python 测试和静态检查：

~~~bash
pytest -q
python -m compileall packages apps tests
git diff --check
~~~

- [ ] 运行数据库迁移验证：

~~~bash
alembic heads
alembic upgrade head
~~~

预期：只有一个 Alembic head，0022_add_oversize_pallet_rule_versions 可从当前 0021_fcl_quote_closed_loop 重放；真实 PostgreSQL 重放若环境不可用，必须在交付说明中明确“只完成 SQLite/静态迁移验证”，不能把未验证写成通过。

- [ ] 运行前端验证：

~~~bash
cd apps/web
npm run test
npm run build
cd ../..
~~~

- [ ] 做一次普通 DTO 泄露审查：递归检查 Zone API 和 AI API JSON 不含 pallet_breakdown、internal_trace、车辆档案、附加费类别/金额、规则快照、供应商/始发仓内部字段；审计 JSON 反向检查这些字段仍存在并可复算。
- [ ] 做一次规则一致性审查：Zone 直接请求和 AI 自动报价都读取同一发布版本；前端只能展示后端结果，不能在浏览器重算托数或价格；客户总箱数不参与托位乘法；高板和叠放没有互相替代。
- [ ] 做一次工作流审查：成功结果继续写审计/销售记录，人工结果继续进入人工任务池，学习规则不能绕过超大件硬阻断；没有创建平行报价流程。
- [ ] 明确执行用户的上线边界：本计划不执行生产发布、不修改生产规则、不向生产数据库写入默认快照；完成测试后只交付代码、测试结果和待批准的迁移/发布步骤。
- [ ] 检查工作区只包含本功能文件和必要锁文件，确认没有客户报价 JSON、密钥或无关临时文件；提交最终验证变更。

~~~bash
git status --short
git log -10 --oneline
git commit -m "chore(quote): verify oversize pallet rollout readiness"
~~~

完成标准：设计文档第 17.6 节的所有上线门槛均有测试或审计证据；规则仍标注为暂行默认值，未未经用户明确批准进入生产部署。
