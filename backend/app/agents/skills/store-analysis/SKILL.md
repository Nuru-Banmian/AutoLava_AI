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

历史图追问用store_chart(operation=read_saved,message_id,chart_id)，不重新查业务库；可选series键及1起、含端点的point_start/point_end，只返回所选原始点和值/状态。默认50、最多200点/页；续页只传operation=read_saved/result_ref/cursor=next_cursor/page_size，不改变选择。source=saved_chart、queried_at为原查询时间，覆盖属于原查询总范围；图中分段只含该段。临时引用仍只属于本轮，可直接create再次投影完整所选点（不必抄完全部页），保持原时间、状态/精确值和来源，不改旧图；原堆叠来源才能再堆叠，原显式排名来源才能再排名。未读/容量不足明确部分完成；最新则store_query执行新查询并生成新图，不能用旧图充当最新证据。近期上下文只给轻量描述，未提供明确图时根据对话澄清，不猜chart_id或带全部历史快照。

旧图描述因历史裁剪/预算已不在当前上下文，先问“这张旧图已超出当前上下文，是否重新查询最新数据？”，不执行新业务查询、不声称读取了旧图。用户明确确认重新查询后，执行新store_query并生成新图，原图保留；不为超长历史无限保留描述或构建额外确认UI。
