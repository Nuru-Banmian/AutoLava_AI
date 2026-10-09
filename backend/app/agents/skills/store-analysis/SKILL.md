---
name: store-analysis
description: 按需查询当前门店经营数据、分组指标与同期比较，说明覆盖和口径。
metadata:
  autolava-required-capabilities: text references
  autolava-required-tools: store_data_catalog store_query
  autolava-references: references/metrics.md
---

一般查询先大范围汇总：月收入用一次整月查询、metrics且不按天拆；年收入用一次全年查询先给总结，不默认逐月；周查询一次查完整周、group_by:["day"]，不要逐日调用。当前周期截至当地今天。用户细问后再按月、日或分类拆分；明确明细、图表、分类和比较请求按用户粒度。月度公司结算不能重复摊入每天。
复用范围及有效data_catalog，无目录则空参store_data_catalog；catalog_stale整批未执行，刷新重试。默认本月至今；日期按门店当地周期，历史日期放range.start/end。不连续日期的状态/金额问答优先每日期一个目标，range.start=end=该日期，分别核对matched_count；其他日期列表可用覆盖range加date的in筛选。targets直接传对象数组，不把数组序列化为字符串。全历史range:{all_history:true}不限366天。
筛选交后端：“包含优惠且营业”用filters:[{field:"activity",op:"contains",value:"优惠"},{field:"is_open",op:"eq",value:"营业"}]。
daily_ledger的经营日均台账营业额用average_ledger_revenue，以经营日为分母、不含公司结算；详细口径按需读指标参考。
期间比较先取得后端comparison.changes回执。例：7月对6月台账，用一个目标{domain:"daily_ledger",range:{start:"2026-07-01",end:"2026-07-31"},metrics:["total_revenue"],compare:{range:{start:"2026-06-01",end:"2026-06-30"}}}并补id；上期也可compare:{preset:"previous_period"}。本期metrics、comparison.metrics及comparison.changes分别给本期、基期、差额/变化率，按difference/change_percent原值回答。
连续多月优先一目标及group_by:["month"]；分类合计income_items、metrics:["amount","share_percent"]、group_by:["category"]；其他数据加include_in_total=false。fields与metrics二选一。历史最高五天用range:{all_history:true}、fields:["date","daily_revenue","activity"]、order_by:[{field:"daily_revenue",direction:"desc"}]、top_n:5。
store_query只支持新查询catalog_version/targets，不支持游标续页。row_limit为单次返回完整行上限，默认/最多200；容量不足明确部分完成及未返回范围。需要更多明细用更小日期范围重新查询；汇总、图表使用本轮全匹配结果，不能声称明细全部已读。
未读说明部分完成、已读/总行数和未读范围。context_capacity停止本轮读取并保留成功证据；row_too_large为单完整行过大，result_capacity_exceeded为本轮4MiB快照超量；保留用户范围/字段。引用仅本轮有效，结束/停止/重置/撤权清理。
每日台账折线查询daily_ledger、metrics:["total_revenue"]、group_by:["day"]；store_chart用dimension:"day"、series:["total_revenue"]、type:"line"，保留未知和零。明细fields仅用于top_n横向排名，dimension:"date"、series:["daily_revenue"]、type:"horizontal_bar"。两月台账柱图需另一个覆盖两月的range及group_by:["month"]，用dimension:"month"、type:"grouped_bar"。main仅本期行、comparison仅基期行，均不合并两期；compare目标计算差额，画双月图另查跨月行。
画图先调用store_chart取得prepared，再说明已生成；引用完整快照result_ref，选main/comparison、维度和已选指标，不传值。例：台账/结算月堆叠查monthly_income、metrics:["daily_ledger_revenue","confirmed_settlement_income"]、group_by:["month"]，再用dimension:"month"、series:["daily_ledger_revenue","confirmed_settlement_income"]、type:"stacked_bar"。prepared随完成回复保存。堆叠仅可相加构成；分类series_by:"category"、series:["amount"]；排除其他数据，不混总额与分项或平均值。不同单位自动分图。时间366点连续分段/6系列、分类排名50项、8图/单96KiB/总512KiB；整组原子检查，失败保留之前成功图。不删点/抽样/改粒度，无饼图/双轴/下载/截图。遵从不用图/明细要求，简短分析；失败说明。
现金/刷卡/公司结算的月度构成必查income_composition、metrics:["amount"]、group_by:["month","category"]，用series_by:"category"及series:["amount"]堆叠；monthly_income的台账合计不能代替现金与刷卡两类。
按需读[指标口径参考](references/metrics.md)。图表追问重新store_query，沿用近期日期/指标/分组；信息不足先追问，说明最新数据，需要时生成新图，旧图保留查看。见[图表追问参考](references/saved-charts.md)。技能只读文本，不扩权限或执行脚本。
