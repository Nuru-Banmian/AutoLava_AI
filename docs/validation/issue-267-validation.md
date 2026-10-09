# Issue #267 验证记录

日期：2026-10-09（Asia/Shanghai）。父规格 #260；本票 #267。

独立工作区 `D:/work/myself/AI-try/AutoLava-AI-267`，分支 `codex/issue-267-chart-groups`。固定基线 `de731bf2537f181fa46966c84cf8144ab5a779ce`（#266 PR #275 已合并）。原项目既有改动不暂存；从更新的 origin/main 实施。提交检查发现两份README因Windows文本写入改变行尾，已恢复原LF，diff检查通过且文档只保留本票四行变化。

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
- 最终受影响后端回归：`test_agent_chart_groups.py`、`test_agent_chat_charts.py`、`test_agent_tools.py`、`test_agent_pagination_budget.py`。日志 `C:/Users/1/AppData/Local/Temp/issue267-backend-final.log`，**63项通过（235.85秒）**。随后新增金额/占比精确8.33及不安全数量整组拒绝2项专项通过（9.12秒）；最终审查修复的排名透视拒绝与相关构成/普通排名5项专项通过（19.42秒）。重复用例不相加，相关用例合计66项均有通过证据。
- 前端 `AgentChart.test.tsx` / `AgentChatPage.test.tsx`：17项通过（5.83秒）；tsc、build、受影响Python Ruff及 OpenAPI --check 通过。
- 实际 Chromium 1280px/390px：10项通过（41.2秒）。构成、比较及单位拆分、排名、长趋势、同轮多次创建超量；桌面hover/手机tap显示准确值，真实零/未知、分段范围/段数、末日99、刷新恢复和无下载入口/无横向溢出。使用真实 HTTP/SSE，非拦截伪造图表payload；转发到隔离临时数据库验收服务器。
- 截图 `frontend/output/playwright/issue267-{构成,比较,排名,长趋势,超量长趋势}-{1280,390}.png`。已视觉查看390构成和1280长趋势；截图是验收证据，不是产品截图存储能力。

复现浏览器：当前backend使用 `python -m tests.browser.chart_groups_server`（127.0.0.1:8067，临时数据库），frontend使用 `npx playwright test --config playwright.chart-groups.config.ts`。复用锁定#265 Python依赖与锁定前端node_modules，不改锁文件；Python导入必须指向267。普通前端CI不要求验收服务器在线。

## 审查、CI 与未验证范围

固定命令 `git diff de731bf2537f181fa46966c84cf8144ab5a779ce...HEAD`。首检查点30f388c（17文件）：Standards 0违规/0实质smell；Spec 1项P2：横向排名分类透视重排来源次序。公开HTTP用例复现后，明确拒绝horizontal_bar+series_by=category，普通单维/日期排名不变。f622bc6代码最终两轴复核均0未闭合。两轴发现本记录编辑误把本地63项pytest证据接到自动CI状态后，已修正文档。PR与自动CI尚未执行，其最终状态通过PR及发布回读报告；本地测试、浏览器与CI分别记录。

未执行真实供应商/付费模型调用、生产部署、生产数据验收或生产负载性能测试。受控模型、浏览器和CI证据分别报告，不将它们当作真实供应商或生产证据。#268功能和#260其他子票不在本票完成范围。

## 首轮 CI 与上下文整改

PR #276，首轮 CI run `37926251243`：后端811通过/2失败/6跳过（482.38秒）；后端质量、OpenAPI、前端单测/构建及两组前端端到端成功。失败是 `test_history_pagination_input_scope_and_context_budget`（8000预算下当前6000字消息失败）和 `test_composition_historical_category_filters_keep_other_data_separate`（三目标结果后项缺metrics）。原始失败日志 `C:/Users/1/AppData/Local/Temp/issue267-ci-first-failure.log`；本地仅这两项复现2失败（9.63秒），日志 `issue267-ci-local-red.log`。

diagnosing-bugs反馈循环使用这两个公开用例。单变量压缩常驻图表提示：原基线1204字符，本票曾增至1523字符；重复图型/容量规则保留在真实工具schema与已读取的store-analysis skill，常驻提示只保留行为原则和明确指针。仅改该提示后两项均通过（9.68秒），日志 `issue267-ci-compact-prompt.log`。不修改8000历史预算、完整当前消息合同、默认生产预算或任何容量护栏，也未提高多目标测试预算。压缩后常驻提示1160字符。定向复验预算护栏、上述失败及默认图表预算 **11项通过（48.16秒）**，日志 `issue267-ci-budget-green.log`。新增两个受影响旧用例与原66项去重后68项均有定向通过证据；未运行本地全量。

Git HTTPS握手连续失败，使用Git对象API后备上传原始blob/tree/commit，各SHA与本地完全一致后发布分支引用；首PR远端HEAD为已审查8f3c053。后续整改仍固定原基线、重新两轴审查精确HEAD，再发布并等待新CI，未在首轮失败时合并。
