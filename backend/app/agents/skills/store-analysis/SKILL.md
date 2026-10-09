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
仍有未读须说明部分完成，不能用首批明细冒充全部。context_capacity保留成功快照及已读/未读，停止本轮续页并解释容量限制；row_too_large说明单完整行所需容量，result_capacity_exceeded说明本轮4 MiB完整快照超量，不自行改字段/范围。引用仅本轮有效，结束/停止/重置/撤权即清理。store_chart引用本轮完整物化result_ref而非当前页，选择main/comparison、维度和已选指标；prepared随完成消息保存。趋势line、比较grouped_bar、可相加构成stacked_bar（分类series_by=category、series=[amount]），显式top_n排名horizontal_bar保留查询排序，明细日期维度date。不同单位自动分图且范围/粒度相同；时间366点连续分段/6系列、分类排名50项；不删点、抽样或自动改粒度。新增整组与已有草稿原子检查8图/单96KiB/总512KiB，失败整组拒绝并保留先前成功组。堆叠不混平均值、总收入与其分项、收入与其他数据；不提供饼/环形、双轴、下载、截图。按问题决定出图，遵从画图/不用图/明细要求。图表加简短分析，不默认重复表；失败明确说明，与成功图并存时不伪称全部完成。
用read_skill_resource按需读[指标口径参考](references/metrics.md)，经营日均台账营业额等口径依参考。技能不扩权限，只读受控文本，不执行脚本/Shell/用户文件。
