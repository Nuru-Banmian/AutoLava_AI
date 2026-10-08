# AI 对话（T2–T9 / #240–#247）

## 跨功能验收（T9）

整理和索引消费者已共同接入应用生命周期。完整迁移顺序为 `0026 → 0027`（向量索引）`→ 0028`（后台整理与候选）。本票沿用已发布迁移与实现，不新增迁移。

新增 8 项公开 HTTP/SSE、临时 SQLite 与真实本地 Qdrant 的集成验收，覆盖双在途屏障、范围隔离、重置/恢复、纠正/删除、备份恢复和 AI 未配置时业务可用。输入、失败记录、32 条故事归属与未验证边界见 [T9 验收记录](../../../docs/validation/issue-247-agent-integration.md)。

## 长期记忆索引与检索（T7）

SQLite 始终是权威记录，Qdrant 只存向量及 ID、管理员、门店和版本。普通对话按当前问题向量查询，服务端强制管理员/门店过滤，每条命中再回查 SQLite 的归属、active 状态、版本及删除标记；候选、旧版本和已删除记录不能注入。最多读取 12 条命中、注入 6 条去重记录，未命中不回退为全量记忆列表。记忆是低信任资料，不能改变系统指令、最新人工门店描述或经营工具结果。

先运行向前迁移 `0027`，分别配置百炼 Embedding 的 `AUTOLAVA_AGENT_EMBEDDING_BASE_URL`（HTTPS compatible-mode/v1）、`API_KEY`、`MODEL` 和 `DIMENSIONS`。向量存储选择持久 `AUTOLAVA_AGENT_VECTOR_PATH` 或独立服务 `AUTOLAVA_AGENT_VECTOR_URL`（可配 `API_KEY`）；不配置时不调用 Embedding，普通业务和聊天仍可用，长期记忆只保存、不注入。实际数据路径应在源码之外。当前后台消费者按单进程运行，本地 Qdrant 用路径锁拒绝第二个进程；使用 `uvicorn ... --workers 1`，独立服务模式也不代表已支持多消费者部署。

集合身份固定 Embedding endpoint/model、维度、索引版本和存储位置，更换配置产生独立集合。重建从 SQLite 的有效原文重新生成向量，每次写入后回读验证 ID、归属和版本；全部有效记录同步成功后才激活。重建期间明确显示检索受限，不用旧模型向量查询新集合。集合缺失时先提交重建待办，再创建物理集合，避免两者之间退出留下空的“就绪”索引；旧集合不再读取，物理回收属于维护操作。

记忆变更与索引待办在同一短事务提交。消费者读取持久待办后关闭 SQL 会话，再执行 Embedding/Qdrant 调用；确认任务时核对版本和操作。任务重复执行采用同一 UUID upsert/delete，进程退出留下待办。默认每项最多尝试 3 次，每次间隔至少 2 秒；耗尽后保持 failed，重启不会清零。手动重试或新的权威版本才重新安排。最近错误码保留供回看，不保存供应商错误原文。查询阶段失败另存当前管理员/门店的 `retrieval_error`，页面如实显示受限；后续查询仍可尝试，成功后清除该错误。

- `GET /api/agent/{store_id}/memory-index`：当前范围的 available/processing/failed/unavailable、错误码及待办/失败数。
- `POST /api/agent/{store_id}/memory-index/retry`：只重新安排当前范围的失败索引任务；没有索引待办时重新提问可重试检索。
- `POST /api/agent/{store_id}/memory-index/rebuild`：重新安排当前范围的已有索引任务，包括删除操作，不从旧向量恢复原文。
- 记忆列表返回索引尝试次数、最近错误及检索状态；页面支持刷新、重试。对话 SSE 的 `retrieval` 事件给出状态及实际命中 ID/版本，页面独立显示引用。检索受限时由运行代码写入提示，不依赖模型自述。

### T7 验证记录（2026-10-08）

固定审查基线为远端 main `660b3b8`；在独立工作树实现，原工作区已有文档、界面、启动脚本及输出未修改。Standards 审查发现存储切换/集合丢失和创建前后的恢复窗口，Spec 审查发现查询故障后状态仍显示可用，均已修正并复审。补充创建失败的有限重试检查，防止自动重建反复清零尝试次数。

- 模型替身与真实向量存储：`tests/api/test_agent_vectors.py` 使用迁移的临时 SQLite、真实本地持久 Qdrant、可控向量，从公开 HTTP/SSE 验证索引读写、管理员/门店隔离、候选与恶意 payload 拒绝、纠正/删除/清空后的陈旧命中、重建、关闭重开、更换模型、物理集合丢失、失败预算、手动恢复以及向量调用等待期间纠正和遗留任务恢复。百炼 HTTP 适配使用 respx 验证独立 endpoint/请求格式和维度拒绝。
- 首轮相关 API 回归为 51 passed、4 failed；4 项为新增检索受限提示影响旧输出/第一个 delta 假设，已修正断言。全量后端为 567 passed、5 failed（315.63 秒）；5 项是 schema 清单未加入 `agent_index_configuration`，修正后仅重跑相关 schema/迁移/向量测试，最终 20 passed（66 秒，含 10 条向量行为测试）。保留这些失败记录，不将全量报告为全绿；没有再次全量运行。
- 前端全量 379 passed；末次页面文案/独立引用状态调整后，相关两文件 11 passed，TypeScript 与生产构建通过。保留既有 jsdom `scrollTo` 提示。
- 真实 Chromium + 临时 SQLite + 真实 Qdrant + 可控模型：明确记住、失败 3 次仍保留原文、重试处理中、恢复可用、重置聊天后改写问题召回、显示实际记忆 ID/版本均通过；390px 无横向溢出。截图在本地 `output/playwright/issue245/`，临时服务脚本在 `.autolava-test/vector_demo.py`。保留初次 Vite Windows URL 路径错误、HMR 后过期 ref、未登录 401、缺 favicon 404 和临时 JWT 长度提示；修正路径/刷新 snapshot 后完成演示。演示不使用实际业务数据库。
- 真实百炼 Embedding/中文语义召回质量、模型回答忠实度、独立 Qdrant 服务、Docker、生产部署未验证，真实服务与内容审阅留在 T10。没有重复运行无关页面的全量 Playwright。

## 后台整理与候选处理（T8）

发布版基于已合入 T7 的远端 main 整合：保留向量索引消费者、检索状态和索引重试入口；T8 迁移顺延为 `0028`，依赖 T7 的 `0027`。应用启动同时恢复整理任务并启动索引消费者。

普通对话完成时，主回答、完成事件和 SQLite 整理任务在同一短事务中保存；失败、取消和未完成对话不入队，显式记忆指令独立提交且不重复入队。应用生命周期启动单个串行消费者，不引入消息队列。部署沿用单应用进程约束，不能由多个应用工作进程同时恢复同一任务。

任务保存管理员/门店范围、登录身份、来源运行/消息、对话世代、记忆版本、人工变更世代和描述版本。模型读取至多 12 条同范围用户对话片段、当前用户原话、最新描述和至多 50 条既有记忆；上下文/输出/时间/调用预算沿用独立记忆模型配置。每轮最多提出一条操作，不重新提取旧消息，不将助手或工具内容作为事实来源。

后台提议支持新增、同义合并、明确更正、冲突候选、推断候选及拒绝。保存来源必须逐字来自本轮用户原话；自动保存采取保守的长期表达和不安全内容校验，其余不确定提议进入候选。该校验不等于真实模型的自然语言理解或内容质量已验收。候选确认前不进入主对话有效记忆或索引回读。

- `GET /api/agent/{store_id}/memory-jobs`：每页 20 条，`next_before` 翻页；返回来源位置、版本、状态、调用次数、失败记录和结果，不返回会话凭据。页面提供整理状态、失败原因和历史任务。
- `POST /api/agent/{store_id}/memories/{memory_id}/confirm`：`expected_version`，可选修改后的 `content`。确认推进版本并安排索引；若候选指向冲突旧记录，必须核对旧记录版本后才能替换。
- `POST /api/agent/{store_id}/memories/{memory_id}/reject`：`expected_version`，成功返回 204，保留防重墓碑。同一版本与同一决定可重复提交，不再创建记忆。

所有人工纠正、删除、清空、确认及拒绝均推进人工变更世代；任务保留来源运行提交时的世代，不能给旧来源换用新的世代。领取排队任务时只允许未经历人工变更的普通后台追加重读记忆版本；模型等待后的提交仍严格核对版本、世代、身份及描述版本。重置和描述变更使旧任务失效，不恢复已删除内容或旧描述，不影响已完成主回答。

每任务最多两次消费尝试，累计模型调用不超过 `agent_memory_max_calls`（默认 2）；仅可重试供应商错误/超时，格式与权限/版本失败不透明重做。启动恢复遗留 running 任务并保留 interrupted 记录，已提交结果和记忆同事务保存。短暂状态写入错误由当前消费者保留任务所有权重试，不重复模型调用；账号级联删除任务后释放消费者。会话过期或被撤销时遗留任务失效，不能绕过登录授权。

### T8 本地验证（2026-10-08）

- 真实迁移 SQLite、真实鉴权和 HTTP/SSE，可控模型：新增提取/同义合并/明确更新、候选确认/修改后确认/拒绝及幂等、范围隔离、失败预算、重启恢复、排队连续轮次、人工变更屏障和账号删除期间的队列恢复均已验证。
- 后端全量一次：575 passed、1 failed（新增表未列入 `test_schema.py` 清单）。修正后定点 15 passed；新增账号删除测试首次因夹具没有最终管理员权限失败，补齐夹具身份及 SQLite 外键后单项 1 passed。日志：`.autolava-test/backend246-full.log`、`agent246-final-focused.log`、`agent246-owner-deletion.log`。不将定点复验写成第二次全量通过。
- 前端全量 380 passed，最终相关文件 12 passed，TypeScript/生产构建、Ruff、OpenAPI 与 diff 检查通过。首次构建发现测试误用 Testing Library 的 `exact` 参数，移除后通过；保留既有 jsdom scrollTo 提示。日志 `.autolava-test/frontend246-{full,final-focused,build-final}.log`。
- 真实 Chromium + 临时 SQLite + 可控模型完成候选确认、修改后确认、拒绝、刷新回读及整理失败状态；390px 无横向溢出。截图 `output/playwright/issue246/`。首次浏览器夹具在迁移调整前创建，启动因缺少新字段失败，已改用新临时库；CLI 期间遇到 HMR 后过期引用、隐藏原话定位不唯一和过早刷新等待，修正定位/等待并最终回读验证。保留 API 日志中的 SSE 断开清理 `no active connection`，不声称零服务日志错误。
- Standards / Spec 两路审查基线 `aa09122`，发现的队列误失效、上下文/同义合并、状态写入与页面刷新竞争已修复并复查。本次仅本地提交，保护原有工作区改动；未修改实际业务数据库。
- T8 初次本地实现未验证真实百炼、真实 Qdrant/Embedding、自然语言内容质量、Docker、生产部署、跨进程任务竞争；发布时整合已合入的 T7，跨功能竞争完整验收仍留在 T9。

以下 T5/T6 记录保留其当时实现状态；当前候选闭环和普通对话整理以 T8 为准。

## 记忆管理（T6）

管理员在独立的 AI 记忆入口纠正、删除单条记忆或全部清空当前管理员与门店范围。删除和清空需再次确认；纠正最多 2,000 字，保留原始来源并追加独立变更依据（页面显示最近 20 条）。候选可纠正但仍保持待确认；确认/拒绝闭环由 T8 交付。

- `PATCH /api/agent/{store_id}/memories/{memory_id}`：提交 `content` 和 `expected_version`，成功返回推进版本后的记录；过期修改返回 409 和 `detail.current`，页面保留输入供核对。
- `DELETE /api/agent/{store_id}/memories/{memory_id}`：提交 `expected_version`，成功返回 204；过期版本返回 409，跨范围或已删除记录返回 404。
- `POST /api/agent/{store_id}/memories/clear`：提交列表回读的 `expected_revision`，成功返回空列表和新范围版本；过期范围版本返回 409，需刷新核对。

向前迁移 0026 增加删除标记、独立纠正依据和范围版本。每次保存、补充来源、纠正、删除、清空都推进范围版本；新运行在提交时记录它，模型读取及提交时再次核对，清空空列表也使此前任务失效。删除保留原来源处理身份与记录墓碑，清空不删除这些防护标记；未来新明确指令可创建新记录。T8 接入旧来源重扫时必须沿用来源运行的 `memory_revision`，不能给旧来源分配当前范围版本。

SQLite 变更与索引待办同事务提交，纠正产生新版本的 `upsert`，删除/清空产生新版本的 `delete`；不存在外部向量调用阻塞权威失效。T7 的索引适配器必须通过 `MemoryService.indexed_memory(scope, id, version)` 回读当前有效版本，拒绝已删除、候选、越权及版本不匹配的命中。真实向量删除/陈旧命中与后台重建的集成验收分别留在 T7/T8/T9。

删除记忆不等于删除聊天：旧聊天原文可能仍可见或仍在当前上下文中。清空记忆保留聊天和门店描述，重置聊天保留有效记忆与独立依据。

### T6 验证记录（2026-10-08）

- 后端最终完整套件 564 passed，覆盖率 87%；6 条 SQLite ResourceWarning 保留在 `.autolava-test/backend-244-reviewed-full.log`。HTTP 回归覆盖纠正冲突、独立依据重置/重建回读、权限与范围、候选纠正、删除/清空竞争、空范围清空及未来重新记住。
- 前端最终完整套件 379 passed（`--maxWorkers=2`，日志 `.autolava-test/frontend-244-reviewed-full.log`）；TypeScript、生产构建、Ruff、OpenAPI 快照与 `git diff --check` 通过。保留既有 jsdom `scrollTo` 提示。
- 真实浏览器使用迁移到 0026 的临时 SQLite 和可控模型，完成纠正、删除、全部清空、重新明确记住及刷新回读；390px 无横向溢出，并验证冲突后当前记录与草稿并存。截图及服务日志在 `output/playwright/issue244/`；浏览器脚本初次包含过期 ref、等待文案不符、相同内容定位不唯一和相对 request URL 错误，修正后上述操作通过。
- 既有 Playwright 全量 95 passed、20 skipped、1 failed：日历预期 `2营业`，实际 `2€999.900.000营业`。已在本次确认基线 `68c7a092c69f0e62dc99a0b76620ca54012c162e` 的独立前端副本复现，日志为 `.autolava-test/e2e-244-full.log` 与 `e2e-244-baseline.log`，未改动无关日历功能。
- 首次后端全量的 3 个表清单断言失败及首次前端全量的 1 个既有登出草稿查找超时均保留；表清单已更新，登出测试单文件 17 passed。初次全量日志分别为 `.autolava-test/backend-244-full.log` 与 `frontend-244-full.log`。
- Standards 审查发现列表读取与清空版本可能不一致，已用真实 HTTP 并发屏障复现并显式 `BEGIN` 修复；分页期间范围版本改变时停止追加并保留旧清空前置条件。失败摘要/回归日志为 `.autolava-test/agent244-listing-red.txt`、`agent244-listing-green.log` 和 `frontend-244-pagination-red.log`。基于 `68c7a09` 的 Standards / Spec 最终复审均为 0 项剩余发现。
- 实际业务数据库仅只读核对为 0022，未升级或写入；本地实施阶段只提交代码，原有工作区改动保留。真实百炼、真实 Qdrant/Embedding、物理向量删除失败恢复、后台重扫/完整重建、模型内容质量、Docker 与生产部署均未验证。
- 后续发布分支从远端 main `dc792f5` 创建，仅带入 #244 的四个实施提交，重新生成契约并保留远端产品名称。发布工作区 40 项记忆 HTTP/迁移/表结构测试、379 项前端测试、TypeScript/生产构建、Ruff、OpenAPI 与类型生成无漂移检查全部通过；既有浏览器套件 96 passed、20 skipped，远端已有的日历修正消除了原工作区的基线失败。日志为 `.autolava-test/issue244-release-{api,frontend,e2e}.log`。

## 明确记忆指令（T5）

在 AI 对话中发送以“记住”“记下”“记得”开头的明确指令（可加“请”“帮我”），例如“记住：以后分析先给结论，再列数据”。单条记忆正文上限 2,000 字。普通聊天暂不自动整理记忆。

独立的 `memory_curator/{graph,state,prompts.md}`（图工厂支持注入受限工具清单，可缩减、不可扩大提议权限） 使用 `registry.MEMORY_CURATOR` 声明的 `propose_memory` 工具及 `AUTOLAVA_AGENT_MEMORY_*` 百炼配置，不复用聊天密钥或模型。默认最多 2 次调用（含重试）、30 秒、18,000 字符序列化上下文、4,000 字符输出、1 次结构化提议；模型输出 token 上限 8,192（独立可配置）。没有任意 SQL、业务写入或描述编辑权限。

`memory/service.py` 从登录身份、门店与当前运行读取原话及消息标识，验证提议内容逐字等于用户指令正文，并从权威原话构造依据，拒绝越权参数、无效目标版本及不可信内容。语义去重/冲突分类由受限模型提出，服务端强制范围、现有版本、原话与规范化文本去重。重复来源以运行 UUID 去重；新同义来源关联到原有效记忆，不覆盖内容。含义不明的冲突存为 `pending_confirmation`，不注入有效记忆。T8 再开放候选处理闭环。

SQLite 向前迁移 0025 新增记忆、独立来源与索引状态表；提交时重新验证身份、运行世代、运行状态、门店描述版本和记忆版本。在一个短事务内提交权威记忆、来源、待索引状态及 `memory` 事件，事务成功后才生成固定的保存反馈。模型等待不持有数据库会话或写锁。停止/重置使未提交工作失效，已经提交的记忆及独立原话依据保留，重启不再次调用模型。

- `GET /api/agent/{store_id}/memories`：当前管理员/门店的记忆列表，包含来源、版本、更新时间、有效/待确认状态及索引状态；每页 50 条，通过 `next_before` 翻页。
- `GET /api/agent/{store_id}/memories/{memory_id}/sources`：独立来源，每页 20 条，通过 `next_before` 翻页；记忆列表内也附带最近 20 条及 `sources_next_before`。其他范围返回 404。
- AI 对话页面的“查看记忆/刷新记忆”和“查看来源”提供回读，支持更早来源及更多记忆；切换账号/门店丢弃旧响应。

主 Agent 每轮读取最新人工门店描述及最多 30 条生效记忆，标明为有界 SQLite 上下文；记忆 Agent 完整比对至多 50 条既有记忆，超过数量或序列化预算明确失败，不静默跳过冲突检查。待确认内容不注入。门店描述和真实业务数据优先，记忆资料不能改变工具权限。Qdrant/Embedding 消费在 T7 接入，当前保存反馈明确“索引待处理，向量检索尚未就绪”，不声称已完成语义检索。

### 2026-10-08 T5 本地验收

- 审查前启动的后端全量：555 passed，覆盖率 87%，10 条 SQLite 连接未关闭 ResourceWarning；日志 `.autolava-test/backend-243-full.log`。审查修正后的记忆专项：23 passed，含小数冲突和 2,000 字上限回归；日志 `.autolava-test/agent243-review-green.log`。两项回归先复现失败，保留 `.autolava-test/agent243-review-red.log`；首次扩展专项的测试生命周期错误也保留在 `agent243-http.log`，迁移及修正后的供应商接线专项 11 passed。
- 前端全量 377 passed，TypeScript/生产构建通过；Ruff、OpenAPI 快照及 `git diff --check` 通过。保留前端既有 jsdom scrollTo 提示。
- 真实浏览器、真实迁移临时 SQLite、可控模型完成明确保存、来源展示、重置保留、刷新回读、门店切换和 390px 布局。修正后重验保存及重置来源回读；截图 `output/playwright/issue243/final-saved-source-after-reset.png`。首次浏览器夹具缺少 json 导入导致失败，已修正，日志保留在该目录 `first-fixture-failure-*`。
- 既有 Playwright 套件：95 passed、20 skipped、1 failed。日历断言预期 `2营业`、实际 `2€999.900.000营业`，在确认基线 `51fc114bf58ba897a571a8852cd1914260e14f6e` 的独立前端副本复现；保留 `.autolava-test/e2e-243-full.log` 和 `e2e-243-baseline.log`，未修改无关日历功能。
- 实际构建 wheel，仓库外工作目录可读取记忆提示词和受限工具清单；禁止 SQLite/socket 连接及 asyncio 后台任务后导入通过。构建使用已有缓存中的 Hatchling，不改项目依赖或锁文件。
- Standards / Spec 审查基线为 `51fc114`。已修正能力注入入口、小数点去重和重复原话导致的输出预算问题，复审均为 0 项剩余发现。
- 实际业务数据库只读核对为 0022，未升级或写入。原有未提交改动保留，当前仅本地提交。真实百炼、真实向量存储/Embedding、模型记忆质量与回答遵循偏好的内容审阅、Docker、生产部署均未执行。

### 2026-10-08 T5 发布分支复验

从远端 `1daec6c` 创建干净发布分支，仅带入 #243 的三笔提交并补充本记录；OpenAPI 冲突通过重新生成解决，保留远端系统标题和新记忆接口。最终代码全量后端 557 passed，覆盖率 87.35%，5 条 SQLite ResourceWarning；前端 377 passed、构建及 OpenAPI/Ruff/diff 检查通过；Playwright 96 passed、20 skipped。远端 main 已更新日历断言，原工作区的日历失败在发布分支不再出现。日志保留在原工作区 `.autolava-test/release243/`。此记录为本地干净发布分支验证，不代表真实供应商、向量服务或部署验收。

管理员从当前门店进入 `/ai`，通过 `/api/agent/{store_id}` 访问：

- `POST /messages`：提交 `{"content":"你好","request_id":"客户端生成的唯一标识","generation":0}`，202 返回运行。世代取自当前对话；同范围、同标识及内容的请求返回同一运行，不再次调用模型。标识内容冲突、旧世代或另一运行占用时返回 409。
- `GET /conversation`：读取最近 100 条持久消息和最新运行，包括未完成的回答片段；`next_before` 配合 `?before=` 和页面“读取更早对话”入口向前翻页。
- `GET /runs/{run_id}`：运行状态、失败代码、配置模型名、调用尝试次数、可获得的 token 用量。
- `GET /runs/{run_id}/events`：持久事件 SSE；支持 `Last-Event-ID` 或 `after` 续读。连接或刷新不会提交新模型调用。
- `POST /runs/{run_id}/stop`：持久标记 `failed/cancelled` 后取消任务，保留已有片段供辨认；迟到片段不能追加或完成。
- `POST /conversation/reset`：提交 `{"generation":当前世代}`，清空聊天内容并递增世代。旧请求、旧运行及待提交的整理来源失效；保留不含聊天正文的运行审计状态。旧世代重置重试返回 409，不能清除新对话。

服务端通过已登录身份构造范围，并沿用“管理员可访问全部启用门店”的既有权限规则。运行的每次片段写入及 SSE 发送前重新验证当前会话、管理员能力、门店状态。查询不存在或其他范围的运行返回 404。页面在账号/门店切换时关闭旧流并丢弃迟到响应。

## 本地运行与配置

使用现有后端依赖及启动流程，先执行 `uv sync --locked --extra dev`、`uv run alembic upgrade head`。0023 只新增运行和事件表，保留 0017 的对话及消息。默认未配置时，应用和既有业务正常运行，聊天运行明确失败为 `model_not_configured`。

根目录 `.env.example` 列出独立的 `AUTOLAVA_AGENT_CHAT_*`、`AUTOLAVA_AGENT_MEMORY_*`、`AUTOLAVA_AGENT_EMBEDDING_*`。当前 CHAT 用于主 Agent，MEMORY 用于记忆 Agent；不要将服务端密钥放入 Vite 配置或前端。填写用户选择的百炼 OpenAI 兼容 HTTPS 地址（以 `/v1` 结尾）、业务空间对应密钥和支持流式工具调用的聊天模型。没有预选地域、模型或向量维度。本版未设置模型特有参数，特殊模型需要先按其官方协议联调。

每轮默认最多 8 次模型调用尝试（含重试），每个模型步骤最多尝试 2 次，最多执行 8 次工具，总时长 60 秒。序列化消息（含背景、技能目录、工具结果）与工具 schema 合计最多 24,000 字符，回答最多 16,000 字符并向模型发送 `max_tokens=4096`。上下文按最新完整消息裁剪，聊天列表显示最近 100 条。仅在未收到回答片段且遇到超时、429、网络或 5xx 错误时有界重试；已经输出片段后失败不会重复生成或保存为完整助手消息。失败记录保留部分输出。错误代码不包含上游响应正文、密钥或完整输入，诊断以运行记录为准。

## 模块与扩展

- `assistant/graph.py`：`create_graph(model, storage, settings, *, agent_capabilities=None)` 工厂，能力依赖可注入 `(SkillLoader, BoundTools)`，默认从显式 Agent 定义构造。LangGraph 的 context → generate 图组装有界历史，在 generate 中执行有限的模型与工具循环；依赖可注入。
- `assistant/state.py` 与 `prompts.md`：运行状态及随应用 wheel 发布的提示词，通过 `importlib.resources` 定位，与工作目录无关。
- `providers/bailian.py`：百炼兼容 HTTP 流解析及安全错误分类。`ChatModel` 是可控模型的注入边界。
- `runtime/repository.py`：复用应用 SQLAlchemy 元数据、会话工厂和 SQLite 短事务，持久保存运行/事件/消息。网络等待期间无数据库事务。
- `runtime/runner.py`：运行预算、任务生命周期和持久失败状态。仅提交消息会创建运行任务；导入 Agent 模块不启动任务或模型连接。
- `context.py`：不可由模型改写的身份与门店范围。

T4 已接入 `registry.py`、`tools/`、`skills/`。后续记忆 Agent 与记忆服务仍按 #238 的目标布局分别放在 `memory_curator/`、`memory/`；当前没有长期记忆或摘要生成，不声称验证了摘要持久化。

0024 增加对话世代和持久请求标识。当前运行方式为单个 FastAPI 进程：启动 lifespan 将遗留运行标记为 `failed/interrupted`，不自动恢复模型调用；用户可主动重试。正常退出也记录中断。停止和重置不意味着能够撤销已经发往供应商的计算或费用，只保证旧结果不能继续提交。

页面区分请求送达不确定时的同标识重试与已确认失败后的新运行重试。停止、重置及账号/门店切换立即作废旧异步响应；另一个页面收到 reset SSE 后重新读取当前世代。

后续记忆整理任务必须保存来源世代，并在每次外部等待后的提交事务内调用 `ChatRepository.authorize_generation(session, scope, generation)`，与实际写入共用短事务。已独立提交的记忆应使用独立存储；聊天重置只修改聊天表。T4 的工具执行沿用同一范围、运行与世代校验；长期记忆尚未接入。

## T4 背景、工具与技能

每轮开始通过 `ChatRepository.background` 读取当前授权门店描述，附来源、revision、时区与当地 `local_date`，并冻结为该轮快照。更新或清空后下一轮采用新状态；同店管理员共享描述，私人聊天仍隔离。历史回答只能作历史资料，不能覆盖当前背景。描述是资料，不能改变系统指令、服务端身份、结构化业务开关或工具授权。

`store_overview` 只接受 start/end（YYYY-MM-DD，1 至 366 天），身份与门店从服务端 scope 绑定。工具边界再次鉴权并复用 AnalyticsService；结束日期截到门店当地今天。结果包含 requested_range、实际 range、as_of_date、收入与指标、休息日/缺失日/洗车经营日覆盖、不可用项和口径。公司结算按重叠开票月份整笔计入；平均每车收入仅使用同时记录洗车数量的经营日，不包含公司结算。关闭洗车数量时不使用历史洗车数据；未录入不作为零收入。覆盖计数不提供逐日归属，回答不能据此猜测具体日期。

`registry.py` 中的 AgentDefinition 显式列出工具和技能。注册不授予身份；每次工具执行前检查运行、权限与世代，结果发布前再次校验。技能的 allowed-tools 等声明不是授权。当前只读工具不开放 SQL、凭证、备份、业务写入、Shell 或个人文件系统。

启动只读启用技能的 YAML 元数据，模型选择后用 read_skill 读取正文，用 read_skill_resource 读取参考。名称与目录一致（小写字母、数字及单连字符，至多64字符），description 非空且至多1024字符；metadata 键值均为字符串。应用约定：

- `autolava-required-capabilities`：空格分隔，仅支持 text、references。
- `autolava-required-tools`：空格分隔，必须出现在该 Agent 启用工具中。
- `autolava-references`：空格分隔的必要资源路径，启动检查存在性与路径边界。

正文和资源每份最多12,000字符；资源只允许 references/ 或 assets/ 下的相对 .md/.txt/.json/.csv 文本，拒绝越界、符号链接逃逸、未启用技能和脚本。不扫描个人技能目录。元数据不合规、未知/重复工具或技能、必要工具/资源缺失、不支持的必要能力均在构图时明确失败。资源随 wheel 发布，使用 importlib.resources，与启动工作目录无关。

### 扩展步骤

新增只读工具：在 tools/ 实现受约束的 Pydantic 参数（拒绝额外字段）和 async handler(session, scope, arguments)，在 handler 的业务边界显式鉴权，用 scope 绑定门店；复用领域服务并返回范围、覆盖与口径。在 tools/registry.py 的 default_registry 注册 Tool，再在 registry.py 的对应 AgentDefinition.tools 显式启用。通过业务 HTTP 建数据，从公开 AI 消息/SSE 验证参数拒绝、权限、指标和范围隔离；通常无需修改运行循环或路由。

新增技能：在 skills/<name>/SKILL.md 写 name、description 与必要能力/工具/参考元数据，正文放步骤和完成条件，按需资料放 references/ 或 assets/。在对应 AgentDefinition.skills 启用；测试启动诊断、按需读取、禁用与越界拒绝，重新构建 wheel 并从仓库外工作目录读取资源。

新增 Agent：在独立 <agent_name>/ 放图工厂、state.py 和 prompts.md，在 registry.py 声明独立工具/技能清单，通过 capabilities(definition) 构造受限能力。图工厂注入供应商、受限工具/技能能力和存储，复用 context.py 的服务端范围和 runtime 的生命周期；为其配置独立预算和明确的公开调用入口，不动态扩大主 Agent 权限。仅导入模块不能连接网络、数据库或启动后台任务。

### 预算与失败

`.env.example` 给出 `AUTOLAVA_AGENT_MAX_STEPS=8`（总模型尝试）、`AUTOLAVA_AGENT_MAX_CALLS=2`（单步骤尝试）和 `AUTOLAVA_AGENT_MAX_TOOL_CALLS=8`。重试消耗总步骤；无进展的工具循环也必须在预算处终止。时间、序列化上下文、总输出字符及每次调用 max_tokens 分别受限。多次调用的供应商用量累加保存；step_budget、tool_budget、context_budget、output_budget 在页面给出可理解提示。停止、重置或撤权后的结果不能发布，但不能撤销已发出的供应商计算与费用。

## 验证入口

`uv run pytest tests/api/test_agent_chat.py` 使用真实登录、临时文件 SQLite 和向前迁移，模型/百炼网络响应为可控替身。真实百炼调用、向量库、内容质量和部署须分别验收，不能由上述测试推断通过。

协议依据：[百炼流式响应](https://help.aliyun.com/en/model-studio/stream)、[LangGraph 图工厂](https://reference.langchain.com/python/langgraph/graph/state/StateGraph)。

### 2026-10-08 T4 本地验收记录

- 最终后端全量534 passed，覆盖率87%，保留8条测试警告（含已有SQLite连接ResourceWarning）；日志 `.autolava-test/backend-242-reviewed-final.log`。日期/覆盖字段先复测：2 passed；审查修复后的公开 HTTP 工具测试与资源/启动测试共32 passed，含可注入受限能力、禁用工具、停止/重置/撤权、最新描述及实际指标口径。使用真实迁移临时 SQLite 与可控模型；不由此推断真实模型内容质量。
- 前端全量376 passed（36文件），TypeScript与生产构建通过；保留已有 MSW/jsdom 提示。Ruff、OpenAPI、uv 0.11.26 离线锁文件check通过。最终 wheel 在仓库外读取提示词、技能正文、参考及注册表通过，导入期间禁止数据库、socket连接和后台任务。
- 真实 Chromium 使用可控模型，390px实际点击发送，SSE显示技能/指标参考/实际查询范围，完成后刷新恢复，切换门店聊天隔离。人工查看桌面与移动截图；移动发送按钮44px高、横排，滚动到底后距固定导航约43px，无水平溢出。证据 `output/playwright/issue242/query-{mobile,desktop}-final.png`。首次打开遇到测试服务未就绪502，随后登录复验通过；401、favicon404及首页未录入台账404保留在本地CLI console记录，不声称零console错误。全量Playwright本轮未运行，历史T3失败不能当成本轮结果。
- 既有真实百炼 qwen-plus 两轮均通过公开HTTP/SSE与合成业务数据联调，每轮4次模型调用。第一轮6389 tokens，日期与覆盖归属误述，保留 `.autolava-test/live242-attempt1.json`；补充当地日期和经营日覆盖字段后，第二轮6660 tokens，保留 `live242.json`。本次继续工作未重复付费调用。
- 内容审阅分别核对两轮原始回答：首轮内容失败；第二轮本例日期关系、225台账+200结算=425总收入、2经营日、2缺失日、平均每车50及1有数/1缺数经营日覆盖说明通过。仅为该合成样例，不是T10多行业全面验收。
- Standards与Spec两个独立子代理按固定基线 `80ed78ec6d9260062025f3094d38b7c3d250f386` 审查本票差异及新增文件。分别发现frontmatter分隔解析和图工厂能力注入问题，修复后复审均0项剩余发现。回归red证据 `.autolava-test/agent242-review-red.log` 与32项green日志 `agent242-review-green.log` 保留；前序失败亦保留。
- 全部检查基于含既有无关改动的当前工作区，不称为干净基线验收。未执行真实向量/Embedding、长期记忆/摘要、Docker或生产部署；本票仅本地提交，不执行远端发布。

### 2026-10-07 T3 本地验收记录

- 后端全量 502 passed，覆盖率 87%；Agent 公开 HTTP/SSE 验收 17 项，使用真实迁移 SQLite、真实登录及可控模型，包括忽略取消后仍返回结果的模型。活动 SSE 在收到片段后精确断开，再按游标恢复，覆盖完成和重置。保留既有 SQLite 连接 ResourceWarning。
- 前端全量 375 passed，TypeScript、生产构建、Ruff、OpenAPI 与 diff 检查通过。页面测试覆盖响应丢失后的请求去重、首次主动重试、迟到提交及旧 SSE 隔离。
- 真实 Chromium + 临时迁移 SQLite + 可控模型通过停止、重置、生成中/完成后刷新、双页面重置通知、生成中门店与账号切换；390px 布局截图已检查。证据位于本地 `output/playwright/issue241/`。
- 全量 Playwright 为 94 passed、20 skipped、2 failed。日历金额文本断言在原始基线 `2330acff` 的独立副本复现；分析加载失败提示的 390px 用例在基线与当前代码单独复测均通过。未修改这些无关页面或断言，保留 `.autolava-test/e2e-241-full.log`、`e2e-241-baseline.log`、`e2e-241-analysis-recheck.log`。
- 后端前两次并行全量的限流替身测试超过原 10 秒状态等待；单独复测通过。状态等待预算调整到覆盖默认 60 秒运行预算后，全量通过；竞争顺序仍由确定性屏障控制。最终日志 `.autolava-test/backend-241-final.log`，前序失败保留在 `backend-241-full.log` 和 `backend-241-verified.log`。前端一次全量的无关登录草稿测试失败后，单独复测和最终全量均通过；原记录保留在 `frontend-241-verified.log`。
- Standards / Spec 独立审查发现并修复事件游标复用与失败首次重试两项问题，复审均无剩余发现。固定基线 `2330acff`；仅提交 T3 文件及共享文件内的 T3 变更，保留其他工作区改动。
- 真实百炼调用、真实向量存储/Embedding、回答内容质量、工具/记忆集成、Docker 与生产部署未执行。上述为 T3 当时的上下文 → 模型生成图证据；T4 在 generate 节点内新增有界工具执行。

### 2026-10-05 本地验收记录

- 后端全量：496 passed，覆盖率 87%（门槛 85%）；保留既有 SQLite 测试的 6 条连接未关闭 ResourceWarning。新增 HTTP 验收包含 11 项测试。
- 前端：371 项单元测试、TypeScript 检查和生产构建通过；既有测试仍输出部分 MSW 未匹配请求和 jsdom scrollTo 提示。
- Ruff、OpenAPI 快照/生成类型、锁文件检查及 `git diff --check` 通过。使用 CI 相同版本 uv 0.11.26 验证锁文件。
- 实际构建 wheel，在仓库之外的工作目录加载 Agent 与提示词，并禁止 SQLite/socket 连接和后台任务创建，验证导入及资源加载通过。
- 真实浏览器 + 临时迁移 SQLite + 可控模型：发送、生成中刷新、完成回读、门店切换及 390px 布局通过。截图位于本地 `.autolava-test/agent240-completed.png`、`agent240-mobile.png`。
- 既有 Playwright 套件：95 passed、20 skipped、1 failed。失败是 `business-record-month-navigation.spec.ts:55` 的日历文本断言（预期 `2营业`，实际 `2€999.900.000营业`），已在原始基线 `13228ea4` 的独立副本复现；未修改无关日历实现。日志保留在 `.autolava-test/calendar-baseline-240.log`。
- 后端首次全量失败来自新增表/迁移版本的旧断言，随后更新预期；新增门店撤销测试曾错误假定归档门店可直接重新启用，已改为验收拒绝访问和迟到回答隔离。最终后端全量日志为 `.autolava-test/backend-240-verified.log`，先前失败保留在 `backend-240-final.log`。
- 验证针对当前工作区，原有界面命名等未提交改动得到保留，未混入本任务提交。Standards / Spec 两个独立审查均为 0 项发现，基线为 `13228ea4`。
- 真实百炼调用、向量存储/Embedding、模型内容质量、Docker 和生产部署：未执行。本地实际业务数据库只读核对迁移为 0022，未为本次测试升级或写入。
