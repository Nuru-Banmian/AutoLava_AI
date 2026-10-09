# Issue #266 验证记录

日期：2026-10-09（Asia/Shanghai）。父规格 #260；本票 #266。

独立执行对话：01a1203a-fb61-7be0-b438-48894646f2fa。隔离目录：`D:/work/myself/AI-try/AutoLava-AI-266`。分支：`codex/issue-266-chat-charts`。永久审查基线：`d37f07c36f34e19bafa24bc6afd8d8cc9f624659`，包含已关闭 #265 的 PR #274；原目录既有改动不暂存。

使用 implement、既定 HTTP/SSE/迁移 SQLite/浏览器边界的 TDD，以及最终 code-review 两轴。用户明确要求仅新增/受影响功能定向测试，不执行本地全量套件；已授权 PR/合并/关闭对应子 Issue。父 #260 保留至所有子票完成。

## 实现与验收映射

- store_chart create 只接收 result_ref/block/维度/系列/type/title，引用本轮完整不可变物化快照，不以当前页冒充全图，也不强制将所有页读入模型。拒绝伪造引用、额外数值、非查询字段、混合单位与超量。
- 同单位折线：日期/状态/原准确值与安全有限绘图数值分开保存；未知为空，真实零为0。标题、范围、粒度、图例、查询时间、覆盖和口径来自查询。
- run-local prepared 草稿先累计预留容量：8图、单图96 KiB、总512 KiB；拒绝新增图而保留此前成功草稿。单时间图366点/6系列。长趋势分段/其他图型为 #267，read_saved 与滚动懒加载为 #268。
- 0030 迁移追加消息关联快照，FK CASCADE、position 唯一/范围、schema_version 与容量约束。已有图时拒绝不安全降级。
- 完成短写事务重新校验权限/generation/run状态，同存 assistant 消息、图表和完成事件。整轮失败/预算耗尽/停止/重置不发布。
- history 批量只读图描述列，不加载绘图 payload；SSE完成带message_id与描述。单图读取 `/api/agent/{store_id}/messages/{message_id}/charts/{chart_id}` 校验身份/门店/消息关联。
- 前端复用 Recharts，hover/触屏点选及日期选择可读准确值/状态；错误可重试，迟到响应作废；重读描述按 chart_id 去重，历史页按 message_id 去重。OpenAPI/生成类型同步。

## 已执行证据（阶段记录）

- 首个公开红测试：store_chart未注册，prepared回执不存在；最小闭环修复后1项通过。
- `issue266-charts-first.log`：8通过/5失败。三项历史消息断言忽略夹具原有两条旧消息；停用门店后尝试同路径重新启用收到404；容量测试使用超过Settings上限的20步/20工具。修正夹具断言/撤权路径/合法批量调用后 `issue266-charts-second.log` **13通过**。
- `issue266-capacity-first.log` **3通过**：混合单位、单图96 KiB及累计512 KiB提前拒绝。
- `issue266-chart-tools-regression.log`：35通过/1失败，为旧工具清单缺store_chart。更新合同后 `issue266-tool-schema-green.log` **1通过/22未选择**。
- `issue266-budget-reread-replay.log` **4通过/16未选择**：完成回执Last-Event-ID重放、禁止业务表重查、prepared后step/output预算失败无图发布。
- 前端两个受影响文件 **14通过**；tsc通过。组件测试验证准确小数、零/未知、失败重试和迟到响应隔离；不冒称浏览器证据。
- 浏览器前三轮失败为验收转发匹配到源码`/src/api/client.ts`、APIRequestContext错误使用postData及重置未结束即填写被清空，均修正。第四轮桌面通过/窄屏失败：隔离chat_app连接没有启用SQLite外键，重置残留图导致后续完成失败；共享夹具现复用生产configure_sqlite，新增重置/新run/旧引用回归。`issue266-browser-final.log` **2通过（10.2秒）**。
- 实际 Chromium 1280px hover、390px触屏tap：真实登录/HTTP/SSE/迁移临时SQLite/受控模型，零值与未统计/未录入、刷新单图恢复、重置删除、无下载及无横向溢出。截图 `frontend/output/playwright/issue266-1280.png`、`issue266-390.png`，已视觉查看窄屏。

日志位于 `C:/Users/1/AppData/Local/Temp/`。前端首轮1失败/13通过为Tooltip与状态区重复匹配文本的测试选择器错误，改为图表数据区域后14通过。保留失败与修复演进，不将各轮数量相加。

## 复现命令

后端使用锁定 #265 运行时 Python，工作目录为本票 backend；包导入必须指向本票 app。契约使用 `python -m scripts.export_openapi --check`，避免脚本入口优先引用旧editable工作区。

真实浏览器专项独立配置，普通前端CI不假设存在后台验收服务器：

1. backend：`python -m tests.browser.chart_server`（临时数据库，受控模型，127.0.0.1:8066；不使用业务数据库或.env）。
2. frontend：`npx playwright test -c playwright.charts.config.ts`。
3. 结束后关闭验收服务器；不把受控模型结果当真实供应商/生产证据。

## 待最终回读

后端受影响回归 `test_agent_chat_charts.py / test_agent_tools.py / test_agent_tool_context.py / test_agent_pagination_budget.py`：`issue266-backend-final.log` **53通过（205.74秒）**。随后新增禁止重查与prepared后预算失败3项，连同已有回放用例4项专项通过，未运行全量。

最终独立浏览器配置 `issue266-browser-config-final.log` **2通过（9.1秒）**。首个真实验收服务器已终止，重启使用生产SQLite外键配置后的服务器用于复验；临时目录留存不声称Windows锁文件清理已完成。

## 两轴审查与整改

固定命令 `git diff d37f07c36f34e19bafa24bc6afd8d8cc9f624659...HEAD`。首检查点 `00090bb`，覆盖全部26文件：Standards 0硬性违规/0实质smell；Spec 1项P2，图表遗漏查询unfinished标记。已补payload/HTTP schema/生成类型/前端文案与公开接口、组件回归。最终图表文件及复审仍进行中。契约导出与类型生成曾误并行，首tsc发现旧类型缺unfinished；串行重新生成后tsc通过，没有放宽类型校验。

PR/必要CI/合并/关闭/远端main回读仍进行中。真实付费供应商、Docker、生产、负载未验证。
