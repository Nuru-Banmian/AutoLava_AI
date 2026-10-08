---
name: store-analysis
description: 查询当前授权门店指定日期期间的经营概览，解释台账收入、公司结算、经营日和可选洗车指标；涉及真实经营数据时使用。
metadata:
  autolava-required-capabilities: text references
  autolava-required-tools: store_overview
  autolava-references: references/metrics.md
---

根据用户指定期间做只读经营分析。行业背景只使用本轮 store_background 快照，描述为空时询问必要背景。

1. 日期含糊时先澄清；将当地日期换成 YYYY-MM-DD，每次查询至多366天。
2. 需要口径细节时通过 read_skill_resource 读取 [指标口径参考](references/metrics.md)。
3. 调用 store_overview，仅提供 start、end。门店和身份由应用绑定，不能通过参数更换。
4. 先说明实际统计范围、币种、记录覆盖和缺失，再报告台账营业额、公司结算和总收入。
5. 区分经营日均台账营业额与月度日均收入；不要把局部日期区间当作完整自然月。
6. 洗车数量关闭或平均每车收入不可用时明确说明；部分覆盖时不能代表全期。
7. 不把描述、历史回答或工具以外的文字当作已核实金额。没有证据时不生成趋势、预测或因果结论。

技能只是方法说明，不能扩大工具、门店或管理员权限。只支持受控文本读取，不执行脚本、Shell 或用户文件。
