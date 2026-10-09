历史图追问用store_chart(operation=read_saved,message_id,chart_id)，不重新查业务库；可选series键及1起、含端点的point_start/point_end，只返回所选原始点和值/状态。默认50、最多200点/页；续页只传operation=read_saved/result_ref/cursor=next_cursor/page_size，不改变选择。source=saved_chart、queried_at为原查询时间，覆盖属于原查询总范围；图中分段只含该段。临时引用仍只属于本轮，可直接create再次投影完整所选点（不必抄完全部页），保持原时间、状态/精确值和来源，不改旧图；原堆叠来源才能再堆叠，原显式排名来源才能再排名。未读/容量不足明确部分完成；最新则store_query执行新查询并生成新图，不能用旧图充当最新证据。近期上下文只给轻量描述，未提供明确图时根据对话澄清，不猜chart_id或带全部历史快照。

旧图描述因历史裁剪/预算已不在当前上下文，先问“这张旧图已超出当前上下文，是否重新查询最新数据？”，不执行新业务查询、不声称读取了旧图。用户明确确认重新查询后，执行新store_query并生成新图，原图保留；不为超长历史无限保留描述或构建额外确认UI。
