# Canada Final Mile Auto Quote

用于加拿大尾端卡车派送自动报价的项目仓库。

## 项目目标

- 根据派送地址、邮编、货物信息和服务要求自动生成尾端卡车派送报价。
- 支持区域/邮编分区、托盘数量、附加服务、燃油费、住宅派送、预约派送等费用规则。
- 预留报价 API、规则配置、报价记录和人工审核流程。

## 当前状态

仓库已初始化，Canada final-mile 报价资料已归档到 `reference/canada-final-mile/`。

## 资料入口

- 资料索引：`docs/reference-index.md`
- 实时报价 SOP：`reference/canada-final-mile/SOP_QUICK.md`
- 规则参数：`reference/canada-final-mile/RULES.yaml`
- 输出模板：`reference/canada-final-mile/QUOTE_TEMPLATE.md`
- 邮编/Zone/价格查表数据：`reference/canada-final-mile/`

## 下一步

- 搭建报价引擎的数据读取层。
- 实现计费托数、邮编/FSA、Zone、价格表查询和附加费计算。
- 用 `EDGE_CASES.md` 建立异常场景测试集。
