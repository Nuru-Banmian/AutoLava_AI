# Agent 聊天图表恢复限定验收

日期：2026-10-10，Asia/Shanghai。延续已有修复及最新交接，没有重新整合、迁移或启动服务。范围为当前本地 Agent 的针对性查询、计算、可信图表、消息快照保存及聊天交互；保留当前门店权限、有界 SQLite 记忆、未统计口径和已优化界面。

## 结论与现场

当前源码、运行库 0031 和在线图表契约已生效。限定测试集合首次结果为 **197 passed、2 failed**；两项失败均已修正并在最终三项相关切片中通过。没有重跑整个 199 项集合，也不将首次结果改写成“199 passed”。本报告不代表真实供应商聊天、全量回归、生产或负载验收。

原目录：`D:/work/myself/AI-try/AutoLava-AI`。隔离目录：`D:/codex worktrees/guest-chat-guide/AutoLava-AI`。后端测试使用隔离源码、迁移后的临时 SQLite、合成身份及受控响应。共享 venv 运行隔离脚本时显式设置 `PYTHONPATH` 指向隔离 backend，避免 editable 安装加载原目录代码。

## 实现与本轮收尾

- 恢复 `store_data_catalog`、`store_query`、`calculate`、`store_chart`，继续提供受限技能读取；`store_overview` 保留为内部兼容路径，不向模型公布为默认业务工具。
- 图表来自同轮不可变查询结果，不接受模型自填数值。completed 事务保存 assistant 消息、图表快照和事件；history/SSE 仅带描述，单图端点按当前身份、门店、消息关联读取。
- 前端按 chart_id 去重、共享读取缓存、附近加载/可见绘制，作用域失效时取消旧读取；保留零值与未知状态、精确值选择及失败重试。完成后清除“已准备图表，完成后保存”提示。
- 保留当前授权复验与有界 SQLite 有效记忆；待确认、其他管理员和其他门店记忆不会进入当前图表轮次。
- 追加 `0031_agent_charts`，保留既有迁移链；有保存图时拒绝不安全降级。没有引入向量记忆迁移。
- 保留既有聊天布局、示例会话、快捷提问、输入及滚动交互。顶部“AI 对话”标题和门店说明未恢复。
- 本轮新增的收尾修改仅为 `backend/tests/api/test_agent_tools.py` 的供应商分片响应夹具和断言；经文件前后段逐字节比对后只回写该文件。新增本验收报告。没有新增业务实现或修改运行库。

## 199 项原进程结果及失败修复

准确原命令，在隔离 backend 执行：

```powershell
.venv/Scripts/python.exe -m pytest tests/api/test_agent_store_query.py tests/api/test_agent_query_metrics.py tests/api/test_agent_query_categories.py tests/api/test_agent_query_income.py tests/api/test_agent_chart_groups.py tests/api/test_agent_saved_charts.py tests/api/test_agent_calculate.py tests/api/test_agent_pagination.py tests/api/test_agent_grounding.py tests/api/test_agent_tool_context.py tests/api/test_agent_unstatistical.py tests/api/test_agent_tools.py -q --tb=short
```

session 28484 句柄返回 `Unknown process id` 后，先确认 PID 68688/83460 仍运行，未启动重复集合。原进程随后完成；从原会话日志的工具完成事件收回 stdout、exit_code=1：**2 failed, 197 passed in 1196.72s**。最终 pytest lastfailed 同样列出这两项；不以缓存或进度点推算通过数量。

1. `test_out_of_context_old_chart_asks_before_latest_query_and_keeps_original`：原进程加载旧模块，依赖不存在的 `tests.browser.saved_chart_server`，报 `ModuleNotFoundError`。前轮已把必要受控模型独立放入测试文件，单项 **1 passed /11.65s，22 deselected**。本轮再次验证通过；没有引入浏览器服务器或监听器。
2. `test_bailian_fragmented_tool_call_and_result_messages`：旧夹具把 `store_overview` 调用作为第一条供应商响应，未提供现在必需的 `plan_response`；仍断言旧工具清单。原单项复现 **1 failed /9.95s**。改为计划、目录、分片 `store_query`、最终回答，使用目录真实返回的版本。保留真实 SQLite 查询金额 150、工具调用 ID、分片函数名和参数组装、四次请求以及 token 总量 80/15 的断言。首次适配因误把自动技能回执当查询完成仍失败（与旧图一起运行 **1 failed、1 passed /21.05s**），修正响应分派后单项 **1 passed /12.13s**。没有放宽生产计划检查或改供应商解析器。

最终相关切片，在隔离 backend 设置 `$env:PYTHONPATH=$PWD.Path` 后执行：

```powershell
.venv/Scripts/python.exe -m pytest tests/api/test_agent_tools.py::test_bailian_fragmented_tool_call_and_result_messages tests/api/test_agent_saved_charts.py::test_out_of_context_old_chart_asks_before_latest_query_and_keeps_original tests/api/test_agent_grounding.py::test_actual_transport_plan_triggers_query_without_model_business_tool_call -q --tb=short
```

结果：**3 passed /29.78s**。覆盖两项首次失败及相邻真实传输计划回归。修正后的两项已经通过；原 199 项结果仍保留首次失败记录，重复切片不累加成新的独立总数。

## 已通过的限定验证

以下前轮结果来自最新交接；本轮对源码和证据现场复核，不因收尾而重复运行无改动切片。

| 范围 | 结果 | 证据边界 |
| --- | --- | --- |
| `test_agent_chat_charts.py` | 21 passed /143.06s | 认证 HTTP/SSE、真实工具、迁移 SQLite、受控模型；持久化、重放、生命周期与快照 |
| `test_agent_chart_migration.py` | 1 passed /9.74s | 临时 0030→0031，原行/结构/索引、未统计行、FK/完整性、降级保护和消息级联 |
| 范围/记忆及显式保存/冲突切片 | 4 passed /27.59s，28 deselected | 当前授权撤销、旧图读权恢复、reset 保留有效私有 SQLite 记忆 |
| manual_changes_reject / clear_is_versioned | 5 passed /37.92s，25 deselected | 与上一切片不重叠，原记忆版本、清理与隔离行为 |
| ChatPage + AgentChart | 30 passed /11.21s | 20 页测试、10 图表测试；模拟 API 的组件证据，含重复图和 completed 重放 |
| 最后 completed 提示修正 | 1 passed /5.16s，19 skipped | 属于上述 30 项的重复验证 |
| 前端最后 build | 成功 | 源码提示修正后构建；本轮仅改后端测试及报告，未再构建 |
| Ruff / 源码契约 check | 前轮通过 | 清单后端文件；隔离显式源码导出检查，不代表真实模型 |
| 本轮 Ruff / diff-check | 通过 | 两个失败所在测试文件，以及清单限定 diff-check |

## 浏览器与模型证据分层

1. **先前纯模拟浏览器响应**：支持既有聊天界面证据，不能证明图表真实查询或持久化。
2. **真实应用 + 隔离 SQLite + 受控模型的 Chromium**：真实构建产物通过一次性请求桥进入 FastAPI、认证、ASGITransport 和迁移 SQLite；没有合成图表 API 响应，也没有新增网络监听器。不是浏览器直接连接在线 8000 的 TCP 端到端。
3. **供应商传输协议测试**：使用实际 BailianChat 解析器和 respx 合成 SSE，验证计划、分片调用、真实工具结果与使用量；没有访问真实供应商。
4. **在线服务**：用户通过正常启动器重启后，前轮 `/health`、在线/导出 OpenAPI 一致、未认证接口 401 已通过。本轮只读再次确认 health=ok、契约完全一致；未发送真实聊天或业务写入。
5. **真实供应商/付费模型**：未验证、未调用。

真实隔离应用浏览器已验证：桌面 1440×1000 悬浮准确 0；窄屏 375×812 选择未统计/未录入时显示未知及独立状态；SVG 有两个已知点，四个日期完整保留；刷新仍只有一图；隔离台账首日 19→999 后历史图仍为 19 且完整 payload 不变；新 app/engine 读取同一隔离库恢复图表；无页面错误和横向溢出。首次成功 12 个真实 API 请求含 SSE，随后 display-only 8 个请求不要求新 SSE。

夹具过程保留：首次非安全来源缺 `crypto.randomUUID` 未进入后端；第二次选错门店得到真实空结果、金额断言失败；明确 localhost 来源和门店甲后成功，未降低金额断言。本轮重新视觉查看桌面及手机详情截图，准确零/未知、完成提示和无顶部标题保持。

截图（本地未提交产物）：

- `output/playwright/agent-chart-real-desktop.png`
- `output/playwright/agent-chart-real-mobile.png`
- `output/playwright/agent-chart-real-mobile-detail.png`

长图分段、懒加载、重试及门店/账号/reset 失效分别有 API 或组件验证；没有逐项补做真实浏览器交互，不将这些组件结果冒称浏览器完整验收。

## 数据与工作区保留审计

前轮已在运行库锁内安全原地升级 0030→0031：SQLite backup 含 WAL，锁内备份与当前快照一致，同连接事务迁移，提交前后原 32 表旧行及 schema/索引保持，integrity ok、FK 0。升级前备份为 `.autolava-local/backups/before-agent-charts-20261010-021934.sqlite3`。本轮未迁移、替换、恢复或写入运行库；不会把旧备份与当前后来录入的数据强行对齐。

本轮最终只读审计确认：

- 运行库 revision=0031、integrity=ok、foreign_key_errors=0；在线 OpenAPI 与当前原目录导出完全一致。
- 基线 `autolava-chart-repair-baseline-20261010/hashes.json` 共 389 文件；53 项源清单内原/隔离内容一致，清单外基线文件保持原 hash。报告为额外新增文件，不计入 53 项源清单。
- `git ls-files --stage` 与回写前快照逐行一致，index 摘要 `de0a1e050ffbb835283c0707ff60415a36a09472f618784bbdfd0ff17ae5e2b8`；未暂存、未提交。隔离 vite 路径修正未回写。
- 原 OpenAPI 每个旧结构和值递归保留；generated.ts 与基线仅插入行，没有删改旧行。原契约和未统计改动保留。

临时证据均在 OS 临时目录，不纳入提交：最新交接 `autolava-handoff-2026-10-10-chart-restored-validation-progress.md`、53 项 `autolava-chart-repair-manifest.txt`、回写前 index 快照、`autolava-chart-session28484-final.txt`、`autolava-chart-runtime-migration-20261010.jsonl`、只读最终审计脚本及 JSON。辅助复制/整合脚本非原子且有旧状态前置条件，不可盲目重跑。

## 最终状态及未验证范围

本轮新启动的限定验证均已完成，没有运行中的测试；已知两项失败修正后的相关切片通过。未重跑整个 199 项集合或全量后端/前端测试。未验证真实供应商、付费模型、完整在线聊天、生产、并发负载及所有规格项的真实浏览器流程。

没有提交、推送、部署、GitHub 评论/Issue 操作、生产数据库操作或真实访客创建；没有绕过后台启动器策略拒绝。所有原有未提交工作、暂存隔离和运行库后续数据保留。
