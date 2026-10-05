# AI 对话（T2 / #240）

管理员从当前门店进入 `/ai`，通过 `/api/agent/{store_id}` 访问：

- `POST /messages`：提交 `{"content":"你好"}`，202 返回运行。一个管理员、一个门店同时只允许一个运行，繁忙返回 409。
- `GET /conversation`：读取最近 100 条持久消息和最新运行，包括未完成的回答片段；`next_before` 配合 `?before=` 和页面“读取更早对话”入口向前翻页。
- `GET /runs/{run_id}`：运行状态、失败代码、配置模型名、调用尝试次数、可获得的 token 用量。
- `GET /runs/{run_id}/events`：持久事件 SSE；支持 `Last-Event-ID` 或 `after` 续读。连接或刷新不会提交新模型调用。

服务端通过已登录身份构造范围，并沿用“管理员可访问全部启用门店”的既有权限规则。运行的每次片段写入及 SSE 发送前重新验证当前会话、管理员能力、门店状态。查询不存在或其他范围的运行返回 404。页面在账号/门店切换时关闭旧流并丢弃迟到响应。

## 本地运行与配置

使用现有后端依赖及启动流程，先执行 `uv sync --locked --extra dev`、`uv run alembic upgrade head`。0023 只新增运行和事件表，保留 0017 的对话及消息。默认未配置时，应用和既有业务正常运行，聊天运行明确失败为 `model_not_configured`。

根目录 `.env.example` 列出独立的 `AUTOLAVA_AGENT_CHAT_*`、`AUTOLAVA_AGENT_MEMORY_*`、`AUTOLAVA_AGENT_EMBEDDING_*`。仅 CHAT 在 T2 使用；不要将服务端密钥放入 Vite 配置或前端。填写用户选择的百炼 OpenAI 兼容 HTTPS 地址（以 `/v1` 结尾）、业务空间对应密钥和支持普通文本流式聊天的模型。没有预选地域、模型或向量维度。本版未设置模型特有参数，特殊模型需要先按其官方协议联调。

每轮默认最多 2 次模型调用尝试，总时长 60 秒，系统提示词与历史文本合计最多 24,000 字符，回答最多 16,000 字符并向模型发送 `max_tokens=4096`。上下文按最新完整消息裁剪，聊天列表显示最近 100 条。仅在未收到回答片段且遇到超时、429、网络或 5xx 错误时有界重试；已经输出片段后失败不会重复生成或保存为完整助手消息。失败记录保留部分输出。错误代码不包含上游响应正文、密钥或完整输入，诊断以运行记录为准。

## 模块与扩展

- `assistant/graph.py`：`create_graph(model, storage, settings)` 工厂。LangGraph 的 context → generate 图实际组装有界历史并流式调用模型；依赖可注入。
- `assistant/state.py` 与 `prompts.md`：运行状态及随应用 wheel 发布的提示词，通过 `importlib.resources` 定位，与工作目录无关。
- `providers/bailian.py`：百炼兼容 HTTP 流解析及安全错误分类。`ChatModel` 是可控模型的注入边界。
- `runtime/repository.py`：复用应用 SQLAlchemy 元数据、会话工厂和 SQLite 短事务，持久保存运行/事件/消息。网络等待期间无数据库事务。
- `runtime/runner.py`：运行预算、任务生命周期和持久失败状态。仅提交消息会创建运行任务；导入 Agent 模块不启动任务或模型连接。
- `context.py`：不可由模型改写的身份与门店范围。

后续实际接入工具、技能、记忆 Agent 时，按 #238 的目标布局增设 `registry.py`、`tools/`、`skills/`、`memory_curator/`、`memory/` 等。T2 不创建空的未来模块，也不假称已查询经营数据、读取门店描述或保存长期记忆。

T3 负责停止、重置、请求幂等和异常进程中断恢复。T2 的正常应用退出会取消任务并记录 `interrupted`；突然终止进程后的遗留运行恢复尚不属于本次交付。当前运行方式为单个 FastAPI 进程，不支持热重载期间透明续跑。

## 验证入口

`uv run pytest tests/api/test_agent_chat.py` 使用真实登录、临时文件 SQLite 和向前迁移，模型/百炼网络响应为可控替身。真实百炼调用、向量库、内容质量和部署须分别验收，不能由上述测试推断通过。

协议依据：[百炼流式响应](https://help.aliyun.com/en/model-studio/stream)、[LangGraph 图工厂](https://reference.langchain.com/python/langgraph/graph/state/StateGraph)。

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
