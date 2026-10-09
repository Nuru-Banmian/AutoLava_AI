---
name: store-analysis
description: 按需查询当前门店经营数据、分组指标与同期比较，说明覆盖和口径。
metadata:
  autolava-required-capabilities: text references
  autolava-required-tools: store_data_catalog store_query
  autolava-references: references/metrics.md
---

复用范围；默认本月至今并说明，全部历史不限366天；日期按目录的当地周期。有效data_catalog跨轮复用，无则空参store_data_catalog；catalog_stale整批未执行，刷新重试。
store_query新查询带catalog_version/targets，按目录选择必要参数，一次查多目标；calculate不重算指标。完整行默认50/最多200，事件不截断。续页只传continuations:[{result_ref,cursor:next_cursor,page_size}]，不得重选范围/字段，可批量继续多个目标。统计基于全匹配，top_n为显式选择，page_range为当前页，read_ranges/unread_ranges为累计进度；比较分页的row_count/进度按两侧同序号完整行对计。
仍有未读须说明部分完成，不能用首批明细冒充全部。context_capacity保留成功快照及已读/未读，停止本轮续页并解释容量限制；row_too_large说明单完整行所需容量，result_capacity_exceeded说明本轮4 MiB完整快照超量，不自行改字段/范围。引用仅本轮有效，结束/停止/重置/撤权即清理。图表由后续工单接入同一快照。
用read_skill_resource按需读[指标口径参考](references/metrics.md)，经营日均台账营业额等口径依参考。技能不扩权限，只读受控文本，不执行脚本/Shell/用户文件。
