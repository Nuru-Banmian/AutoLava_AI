---
name: store-analysis
description: 按需查询当前门店经营数据、分组指标与同期比较，说明覆盖和口径。
metadata:
  autolava-required-capabilities: text references
  autolava-required-tools: store_data_catalog store_query
  autolava-references: references/metrics.md
---

复用范围；默认本月至今并说明，全部历史不限366天；日期按目录的当地周期。有效data_catalog跨轮复用，无则空参store_data_catalog；catalog_stale整批未执行，刷新重试。
store_query带catalog_version，按目录选择必要参数，一次查多目标；calculate不重算指标。事件完整，超容量/不可用据实说明，分页/图表未上线。
用read_skill_resource按需读[指标口径参考](references/metrics.md)，经营日均台账营业额等口径依参考。技能不扩权限，只读受控文本，不执行脚本/Shell/用户文件。
