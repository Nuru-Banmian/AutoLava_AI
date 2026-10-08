# Agent T9 集成验收（#247）

日期：2026-10-08。父规格：[32 条用户故事及测试约定](https://github.com/Nuru-Banmian/AutoLava_AI/issues/238)。
本票：[跨功能并发、恢复与备份验收](https://github.com/Nuru-Banmian/AutoLava_AI/issues/247)。

## 实施范围与迁移边界

审查基线固定为 `ef0deba239f5c4fd3bb62feacba4f3df3f172745`，工作树为
`D:\work\myself\AI-try\AutoLava-AI-247`，分支 `codex/issue-247-integration`。
原工作区的启动、登录、文档、OpenAPI 草稿及输出不参与本票提交。

基线已包含 T8，尚未包含远端 T7。整合已发布 T7 提交 `1a50d0b`，保留 T8 的整理任务、人工变更世代、候选确认/拒绝、页面刷新保护；同时启用生命周期内的整理和索引消费者，重新生成合并后的 OpenAPI/TypeScript 类型。

远端已发布 `0027_memory_vectors.py`，本地尚未发布的 T8 原来也使用 `0027`。
保持已发布向量迁移原文，将未发布整理迁移顺延为 `0028_memory_jobs.py`，形成单一路径：
`0026 → 0027（向量）→ 0028（整理）`。迁移预期及表清单已同步。
本次只读确认实际业务库 `D:\work\myself\AI-try\AutoLava-AI\.autolava-local\autolava.sqlite3`
仍为 `0022`，未升级或写入。临时库从 `0022` 和更早历史版本向前迁移，包含新对话与 retired 历史表的既有迁移测试已执行。

兼容范围是已发布迁移和实际业务库。曾在未发布 T8 分支生成、却标记为 `0027` 的临时库不是已发布向量版数据库，不能直接套用这条路径；本次验收重新创建临时库，没有对这种开发库执行 stamp 或删表修补。

## 公开行为与输入

`backend/tests/api/test_agent_integration.py` 新增 8 项验收，复用真实鉴权、HTTP/SSE、向前迁移 SQLite 和持久本地 Qdrant；仅聊天/整理模型及向量结果受控。

- 核心输入“以后分析先给结论，再列数据”：普通对话完成后自动整理，独立保存原话来源；重置、关闭重开应用和存储后，改写提问仍收到相同记忆 ID/版本。
- 切到门店 B 或换管理员后，公开对话模型输入没有该私人记忆。纠正为“以后先列数据，再给结论”后只召回版本 2。
- 备份中同时保留有效纠正记录、独立来源/变更、另一条已删除记忆及耗尽两次调用的失败整理任务。通过最终管理员 `GET /api/admin/database-backup` 下载 SQLite，检查完整性和 `0028`，在新数据库连接与空 Qdrant 目录启动，公开回读保持原记录和任务状态，只从有效记录重建召回。
- 再删除有效记录、手动重试与重建索引，公开列表和模型输入均为空。后台旧来源和重启防恢复另由 `test_memory_jobs.py` / `test_agent_memory.py` 的版本与墓碑测试覆盖。
- 在真实向量写入和整理模型各设独立屏障；两者同时等待时，HTTP 纠正、删除、全部清空、重置、描述更新、描述清空均能完成。释放屏障后旧整理任务为 stale，旧索引不能确认新版本，召回仅含当前有效版本，下一轮使用当前描述。
- AI 模型和向量均未配置时，实际供应商适配在本地返回 `model_not_configured`，HTTP/SSE 可回读失败；同一应用通过记账 HTTP 写入 125 并回读成功，索引状态为 unavailable。

并发顺序由屏障决定，不依赖固定睡眠碰撞。独立的旧测试继续覆盖重复请求/来源、有限预算、索引延迟和故障、会话/门店撤权、SSE 断线续读、停止、遗留 running 状态恢复、候选拒绝及资源权限。

## 当前执行结果与失败保留

日志均保存在本工作树 `.autolava-test/`，属于本地证据，不含实际业务数据。

| 检查 | 实际结果 | 证据 |
| --- | --- | --- |
| 整合依赖后整理/向量/迁移/表结构 | 33 passed | `integration247-focused.log` |
| 新增集成首次修正屏障后 | 7 passed，48.89 秒 | `integration247-final-focused.log` |
| 后端全量，仅一次 | 593 passed、1 failed、11 warnings；236 秒；覆盖率 88.26% | `backend247-full.log` |
| 修正失败后受影响集成文件 | 8 passed，54.98 秒 | `integration247-reviewed.log` |
| AI 未配置业务独立复验 | 1 passed | `integration247-unconfigured.log` |
| 前端全量，仅一次 | 378 passed、2 failed | `frontend247-full.log` |
| 原基线 App 文件复现 | 同两项失败，22 passed | `frontend247-baseline-app.log` |
| 当前 Agent 页面相关文件 | 12 passed | `frontend247-agent.log` |
| TypeScript 与生产构建 | 通过 | `frontend247-build-final.log` |
| Ruff、OpenAPI 快照及 diff 检查 | 通过 | 当前命令结果 |
| 实际 wheel 构建与仓库外读取 | 通过，导入时禁止 SQLite/socket 连接及后台任务 | `wheel247-build-final.log`、`wheel247-check.log` |

后端全量失败来自测试替身的可变响应模式：主回答完成仅表示整理任务已入队；测试在队列读取前切换为 save，误把“现在的分析偏好？”保存。现在先等待该查询整理完成并断言 not_saved，再切换模式。只复验受影响文件，不把全量改写成全绿。

此前新增并发夹具将查询和索引共用向量化屏障，首轮查询可能超时，表现似清理停住；改为仅屏障实际向量写入，保留 `integration247-new.log`、`integration247-diagnostic.log`、`integration247-stack.log`，诊断中的中断不算通过。最初 OpenAPI 导出脚本误读共享环境的原工作树安装包，导致前端类型缺失；显式设置当前后端 PYTHONPATH 后重导出通过。首次 wheel 禁用构建隔离时缺 hatchling，启用正常构建隔离后成功，保留 `wheel247-build.log`。

前端失败是 `App.test.tsx` 的 `loads the shared application shell` 与 `moves the global store selector out of More and into the shell`；原始 `ef0deba` 独立源副本复现同两项。本票未修改 App 或其测试。保留 MSW 未匹配台账请求、jsdom scrollTo 提示及 SQLite 连接 ResourceWarning。

## 浏览器与构建资源

真实 Chromium / Playwright CLI，临时迁移 SQLite、真实本地 Qdrant、可控模型，服务脚本 `.autolava-test/browser247.py`，API/Vite 日志及截图位于 `output/playwright/issue247/`。

实际点击验证自动保存、刷新恢复、候选确认（版本 1→2）、索引处理中/可用、重置后保留记忆、停止后的失败提示，以及生成已出现片段后切门店/切管理员的界面隔离。新管理员聊天和私人记忆为空。390×844 无水平溢出，截图已人工检查。

另外实际结束隔离 API 的旧 Python/uvicorn 进程，以同一个临时 SQLite 文件和 Qdrant 路径启动新进程，重新登录后保留两条记忆。改写输入“重启后我的分析习惯是什么？”的页面引用为 `58f299867e284b88b314b9a9dd4e978b`（版本 2）和 `7f5d8b7f27b04aa78faefd6cb00a7c79`（版本 1），与候选确认和自动保存的记录相符。旧账号生成在回读中显示 access_revoked，门店切换前的已完成回答仍仅在原范围可见。证据 `process-restart-retrieval.png`、`account-isolation-mobile.png`、`api-restart.log`，重启脚本 `.autolava-test/restart247.py`。此项证明本地单进程持久化恢复，不代表外部服务/主机故障恢复。

保留最初访问错误 `/agent` 的 404、随后改用 `/ai`；原话正文与隐藏来源重复导致 locator 不唯一，改为正文定位；首次切账号后过早导航取消了登录，重新提交并等页面返回后通过。保留未登录 401、favicon 404、首页未录入台账 404，以及 SSE 取消清理的 `no active connection` 服务日志；不声称零控制台或服务错误。描述编辑/冲突的浏览器操作本次未重复，归属 T1，当前自动化覆盖已执行。

wheel 从仓库外临时目录实际载入两个图的提示词、store-analysis 元数据/正文/参考和注册表。当前主 Agent 启用 `read_skill`、`read_skill_resource`、`store_overview` 与 `store-analysis`；记忆 Agent 仅启用 `propose_memory`，无技能。文档和实际清单一致。

## 父规格 32 条故事归属

“自动化”表示本次实际执行的公开行为/资源测试；涉及自然语言理解、语义召回或模型回答忠实度的结论仍属于 T10。

| 故事 | 归属 | 当前证据与边界 |
| --- | --- | --- |
| 1 当前门店入口 | T2/T3 | chat HTTP、Agent 页面测试及本次浏览器 |
| 2 通用问答 | T2/T3 | chat HTTP/SSE；真实回答质量 T10 |
| 3 流式/停止 | T3 | chat 断线/停止屏障及本次浏览器 |
| 4 刷新恢复 | T2/T3 | chat 持久化与页面恢复、本次浏览器 |
| 5 经营概览 | T4 | `test_agent_tools.py` 公开业务建数→对话工具 |
| 6 指标/缺失口径 | T4 | 工具日期、结算、洗车开关、空数据自动化 |
| 7 明确记住 | T5 | `test_agent_memory.py` 保存来源/失败预算 |
| 8 自动识别 | T8/T9 | jobs 自动整理→索引→召回；理解质量 T10 |
| 9 去重/合并 | T5/T8 | memory/jobs 来源去重、同义提议自动化；真实语义 T10 |
| 10 不确定内容 | T5/T8 | 拒绝引用、假设、临时要求与推断候选自动化；内容审阅 T10 |
| 11 冲突候选 | T5/T8 | jobs 确认/编辑确认/拒绝幂等；本次浏览器确认 |
| 12 来源/时间 | T5/T6 | memory 来源分页、纠正依据、备份恢复及页面测试 |
| 13 纠正 | T6/T7/T9 | 双在途屏障、只召回新版、恢复保持新版 |
| 14 删除 | T6/T7/T8/T9 | 墓碑、旧提议、索引重建/恢复不复活 |
| 15 全部清空 | T6/T8/T9 | 范围版本、空列表、双在途屏障 |
| 16 重置保留 | T3/T5/T9 | 自动记忆重置→重开→检索，本次浏览器 |
| 17 门店隔离 | T2/T7/T9 | 真实 Qdrant 范围过滤、公开对话与本次浏览器 |
| 18 管理员隔离 | T2/T7/T9 | 公开对话、来源/索引范围与本次浏览器 |
| 19 整理失败 | T8/T9 | 已完成回答不变、失败预算/状态和备份恢复 |
| 20 检索受限 | T7/T9 | 向量故障/重试、代码提示及无配置业务可用 |
| 21 独立模型配置 | T2/T5/T7 | Bailian/respx 请求契约；真实资源 T10 |
| 22 遗留任务恢复 | T3/T7/T8/T9 | 持久任务恢复及失败记录；浏览器真实服务进程重启另记 |
| 23 公开验收 | T1–T9 | HTTP/SSE、真实持久存储、浏览器与此记录 |
| 24 描述编辑 | T1 | 当前 stores 自动化；本次不重复浏览器流程 |
| 25 每轮最新描述 | T4/T8/T9 | tools 背景快照与双在途更新/清空 |
| 26 共享描述/私有聊天 | T4 | latest_description/shared_store/private_chat 自动化 |
| 27 空描述不预设行业 | T4/T9 | 模型输入接线自动化；真实多行业回答 T10 |
| 28 描述冲突保留草稿 | T1 | stores 版本及 Admin 页面测试；本次不重复浏览器流程 |
| 29 固定扩展目录 | T4/T8 | README、实际模块与 wheel 资源核对 |
| 30 工具注册/分配 | T4 | injected_capabilities、禁用/越权工具公开行为 |
| 31 技能启用/按需读 | T4 | skill/reference HTTP 工具流程、路径边界、wheel |
| 32 启用清单与权限 | T4/T8 | 注册表诊断、实际清单、身份/门店再鉴权 |

## 审查与未验证项

Standards / Spec 两个独立审查均未发现剩余代码问题。Standards 提醒的同号迁移风险已核对远端发布状态与实际业务库，并在上文限定兼容范围。后续测试替身改动仅用于固定队列顺序，未放宽预期结果。

已通过的是可控模型接线、真实向量存储、应用恢复、隔离 SQLite 备份恢复和本次列明浏览器行为。没有付费真实百炼调用，没有验证中文语义召回、自然语言记忆忠实度、多行业真实回答或长期内容质量；这些留给 T10。没有验证独立 Qdrant 服务、多进程消费者、Docker/代理、生产或异地/其他主机恢复。最终没有将“单次全量出现失败后定点通过”表述为整套全量通过。


## 发布基线复验

发布从远端 main `a8fc2ef2850fd0cd847eb796318ff757a8290c07` 的独立干净工作树进行。该基线已合并 T7（PR #256）和 T8（PR #257），包括正确的 `0027 → 0028`、生命周期接线及合并后类型。因此发布差异只新增本票 8 项集成验收和文档，不重复发布本地分支历史、不改写任何迁移，也不回退门店管理系统命名或 CI 的既有变更。

发布基线定点复验：`pytest tests/api/test_agent_integration.py -q` 为 **8 passed，52.98 秒**；日志 `.autolava-test/release247-focused.log`。Ruff 与 diff 检查通过。完整 PR CI 结果以对应 PR 的检查记录为准，保留前述本地历史失败。
