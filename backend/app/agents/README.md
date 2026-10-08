# AI 对话（T2 / #240、T3 / #241、T4 / #242、T5 / #243）

## 明确记忆指令（T5）

在 AI 对话中发送以“记住”“记下”“记得”开头的明确指令（可加“请”“帮我”），例如“记住：以后分析先给结论，再列数据”。单条记忆正文上限 2,000 字。普通聊天暂不自动整理记忆。

独立的 `memory_curator/{graph,state,prompts.md}`（图工厂支持注入受限工具清单，可缩减、不可扩大提议权限） 使用 `registry.MEMORY_CURATOR` 声明的 `propose_memory` 工具及 `AUTOLAVA_AGENT_MEMORY_*` 百炼配置，不复用聊天密钥或模型。默认最多 2 次调用（含重试）、30 秒、18,000 字符序列化上下文、4,000 字符输出、1 次结构化提议；模型输出 token 上限 8,192（独立可配置）。没有任意 SQL、业务写入或描述编辑权限。

`memory/service.py` 从登录身份、门店与当前运行读取原话及消息标识，验证提议内容逐字等于用户指令正文，并从权威原话构造依据，拒绝越权参数、无效目标版本及不可信内容。语义去重/冲突分类由受限模型提出，服务端强制范围、现有版本、原话与规范化文本去重。重复来源以运行 UUID 去重；新同义来源关联到原有效记忆，不覆盖内容。含义不明的冲突存为 `pending_confirmation`，不注入有效记忆。T8 再开放候选处理闭环，T6 再开放纠正和删除。

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
