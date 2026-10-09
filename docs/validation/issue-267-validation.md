# Issue #267 验证记录

日期：2026-10-09（Asia/Shanghai）。父规格 #260；本票 #267。

独立工作区 `D:/work/myself/AI-try/AutoLava-AI-267`，分支 `codex/issue-267-chart-groups`。固定基线 `de731bf2537f181fa46966c84cf8144ab5a779ce`（#266 PR #275 已合并）。原项目既有改动不暂存；从更新的 origin/main 实施。

使用 implement、tdd、writing-for-agents、Playwright；完成后使用 code-review 两轴及 pr。遵从用户仅运行新增/受影响定向测试的要求，不运行本地全量测试。read_saved、历史图懒加载及缓存属于 #268，本票不将其标为已完成。

## 实施边界

store_chart create 新增 grouped_bar、stacked_bar、horizontal_bar；series_by=category 从查询快照的历史分类身份透视，不接收模型数值。不同单位自动分图，范围/粒度一致。堆叠只允许月度台账额+已确认结算，或同收入口径 amount 分类；重复总额/均值/其他数据拒绝。横向排名要求查询显式 top_n，保留查询次序，最多50项。

时间图按原粒度连续分段，每段最多366点/6系列，保存总范围、各段范围、段数及共享纵轴。整次创建先生成所有单位/分段，再由本轮结果仓库一次预留累计8图/单96KiB/总512KiB；失败不留新增半组，保留此前成功图。准确值与plot分别保存，未知为空，真实零保留；堆叠总量也检查安全绘制表示。同步 schema、OpenAPI、前端生成类型、模型提示、业务技能及 README。

## Red→green 与具体失败记录

- 第一轮新测试失败于测试预算96000超过 Settings 上限，迁移子进程报 Pydantic less_than_equal；改为允许的64000，未放宽生产上限。随后业务 red：grouped_bar 返回 invalid_tool_arguments。实现图型与自动单位分图后首项通过。
- 构成 red：series_by 未上线返回 invalid_tool_arguments；重叠总收入与台账额堆叠误返回 prepared。实现分类透视与 chart_incompatible_stack 后3项通过，包含25/75、真实0及未知月份。
- 长趋势 red：916日返回 chart_capacity_exceeded，重复创建没有成功组。实现连续分段后5项通过；独立期望366/366/184点、共享[0,99]纵轴、三次创建保留前六图并拒绝第三组。
- 排名 red：公开输入尚不支持明细 date；实现后用例误留一个无条件 charts==[] 断言，修正测试分支。明确前3名保留99/40/19顺序；未指定top_n返回 chart_explicit_ranking_required。
- 前端 red：三种柱状图测试均找不到分段说明，原组件只绘制 LineChart。增加 BarChart、横向坐标及段数说明后组件6项通过。
- 首构建失败：复用#265 editable环境，以 python scripts/export_openapi.py 导出时误读旧应用，生成类型缺 ChartDescriptor/ChatChart。核对 app.__file__ 指向267，使用当前backend的 python -m scripts.export_openapi，串行生成前端类型后 build通过。最终类型diff仅本票扩展。
- 首相关后端运行28通过/1失败（110.25秒）：旧断言要求混合单位 chart_mixed_units，与#267自动分图规格冲突。删除过时拒绝案例，保留单图字节上限案例；新增公开测试已验证同范围/粒度的两单位分图。

## 定向与浏览器证据

- 新增 HTTP/SSE 用例使用真实登录、真实查询工具、逐级迁移临时 SQLite 与受控模型；保存图通过公开 history/单图端点读取。覆盖一次查询、构成、单位拆分、排名顺序、50/51边界、916日完整分段、重复创建累计超量、单图超量导致新增整组拒绝并保留先前图，以及默认24000预算普通图成功。
- 最终受影响后端回归：`test_agent_chart_groups.py`、`test_agent_chat_charts.py`、`test_agent_tools.py`、`test_agent_pagination_budget.py`。日志 `C:/Users/1/AppData/Local/Temp/issue267-backend-final.log`，结果待回读。
- 前端 `AgentChart.test.tsx` / `AgentChatPage.test.tsx`：17项通过（5.83秒）；tsc、build、受影响Python Ruff及 OpenAPI --check 通过。
- 实际 Chromium 1280px/390px：10项通过（41.2秒）。构成、比较及单位拆分、排名、长趋势、同轮多次创建超量；桌面hover/手机tap显示准确值，真实零/未知、分段范围/段数、末日99、刷新恢复和无下载入口/无横向溢出。使用真实 HTTP/SSE，非拦截伪造图表payload；转发到隔离临时数据库验收服务器。
- 截图 `frontend/output/playwright/issue267-{构成,比较,排名,长趋势,超量长趋势}-{1280,390}.png`。已视觉查看390构成和1280长趋势；截图是验收证据，不是产品截图存储能力。

复现浏览器：当前backend使用 `python -m tests.browser.chart_groups_server`（127.0.0.1:8067，临时数据库），frontend使用 `npx playwright test --config playwright.chart-groups.config.ts`。复用锁定#265 Python依赖与锁定前端node_modules，不改锁文件；Python导入必须指向267。普通前端CI不要求验收服务器在线。

## 审查、CI 与未验证范围

固定命令 `git diff de731bf2537f181fa46966c84cf8144ab5a779ce...HEAD`。规范与规格两轴审查结果、精确最终HEAD、PR及自动CI结果待回读。

未执行真实供应商/付费模型调用、生产部署、生产数据验收或生产负载性能测试。受控模型、浏览器和CI证据分别报告，不将它们当作真实供应商或生产证据。#268功能和#260其他子票不在本票完成范围。
