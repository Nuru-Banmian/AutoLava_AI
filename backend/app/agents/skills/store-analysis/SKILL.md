---
name: store-analysis
description: 查询当前授权门店指定日期期间的经营概览，解释台账收入、公司结算、经营日和可选洗车指标；涉及真实经营数据时使用。
metadata:
  autolava-required-capabilities: text references
  autolava-required-tools: store_data_catalog store_query
  autolava-references: references/metrics.md
---

根据用户指定期间做只读经营分析。行业背景只使用本轮 store_background 快照，描述为空时询问必要背景。

1. 复用上下文范围；无范围默认本月至今并说明，全部历史不限366天。日期按门店时区自然日、周一周和自然月/年解析，未来截止截到当地今天。
2. 需要口径细节时通过 read_skill_resource 读取 [指标口径参考](references/metrics.md)。
3. 没有有效store_background.data_catalog时调用store_data_catalog（空参数）；有效目录跨轮复用。store_query携带catalog_version和最多6个唯一id目标，只选问题需要的台账或历史分类明细字段、范围、筛选、排序或top_n。catalog_stale整批未执行，刷新目录后重试。门店身份由服务端绑定。当前仅上线完整明细；汇总/比较/分页/图表待后续工单，超容量明确说明失败，不截断事件或假装已读全。
4. 先说明实际统计范围、币种、记录覆盖和缺失，再报告台账营业额、公司结算和总收入。
5. 区分经营日均台账营业额与月度日均收入；不要把局部日期区间当作完整自然月。
6. 洗车数量关闭或平均每车收入不可用时明确说明；部分覆盖时不能代表全期。
7. 不把描述、历史回答或工具以外的文字当作已核实金额。没有证据时不生成趋势、预测或因果结论。
8. 分别报告已统计、未统计与未录入覆盖。未统计的经营数值未知，全未统计的期间不能解释为已知零收入；公司结算按自身月份独立计入。
9. 集中清点收入保留在清点当天。仅在事件或上下文提供证据时解释集中统计，注明依据和已知覆盖时段；相邻未统计日期本身不能确定收入覆盖范围。

技能只是方法说明，不能扩大工具、门店或管理员权限。只支持受控文本读取，不执行脚本、Shell 或用户文件。
