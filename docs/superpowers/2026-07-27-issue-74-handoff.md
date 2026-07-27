# Issue #74 交接：Agent 安全评估与发布否决门禁

## 当前状态

- 仓库：`Nuru-Banmian/AutoLava_AI`
- Issue：[#74 建立 Agent 安全评估与发布否决门禁](https://github.com/Nuru-Banmian/AutoLava_AI/issues/74)
- 当前分支：`codex/add-agent`
- 审查固定点：`6eec1e7d81eadc2dd97d6d31e446f1c3e76b50bf`
- 主要实现提交：`3aea360 feat: add Agent safety release gate (#74)`
- #71、#72、#73 已关闭并在开始 #74 前合入当前分支。
- #74 仍为 open，尚未评论或关闭，也没有 push。
- 本窗口使用了用户指定的 `implement` skill；该 skill 要求 TDD、完整测试、双轴 code review 和提交当前分支。

开始下一窗口时先运行：

```powershell
git status --short --branch
git log -3 --oneline --decorate
Get-Content -Raw docs/superpowers/2026-07-27-issue-74-handoff.md
gh issue view 74 --comments
```

## 已实现内容

### 机器可读发布评估集与 CI 门禁

- 新增 `backend/tests/release/agent_release_cases.json`，记录真实中文经营问法、覆盖标签、对应 pytest node 和一票否决类别。
- 新增 `backend/tests/release/test_agent_release_manifest.py`，验证：
  - 所有期间对象；
  - 动态收入分类、缺失数据、公司结算、经营分析、会话重置；
  - 权限攻击、五类提示注入、EvidencePlan 攻击；
  - 回答编造、SQLite 一致性/重试、备用模型范围；
  - Playwright 覆盖声明；
  - CI 使用 Fake Model Adapter 且不声明真实模型密钥。
- `backend/tests/conftest.py` 根据评估清单给真实测试动态添加 `agent_release_gate` marker。
- `.github/workflows/ci.yml` 在完整后端套件前运行：

```text
python -m pytest -m agent_release_gate --strict-markers
```

### 已捕获并修复的问题

1. Agent 请求中途撤销管理员角色后，路由过去仍会保存并返回回答。
   - `backend/app/api/routes/agent.py` 现在在模型运行后、最终持久化前，在同一个短写事务内重新验证管理员身份与门店访问。
   - HTTP 回归测试：
     `test_in_flight_turn_revalidates_authorization_before_returning_answer`。

2. `aiosqlite` legacy transaction mode 使同一个 `_read_snapshot` 的多条 SELECT 看到不同提交版本。
   - `backend/app/core/database.py` 现在由 `create_sqlite_engine` 统一创建引擎：
     驱动 `isolation_level=None`，SQLAlchemy `begin` 事件显式发送 `BEGIN`。
   - 真实 WAL 双连接测试在首条查询后并发提交洗车数量变化，证明单个简单 EvidenceBundle 仍读取旧快照。

3. 模型可把经营问题误路由为 `direct_answer`，绕过取证直接输出金额等经营声明。
   - `backend/app/agent/workflow.py` 增加了初步的 `DIRECT_ANSWER_BUSINESS_CLAIM` 拦截。
   - 注意：Spec 审查已确认该正则仍可绕过，必须继续修复，见下方 P1。

### 新增/扩展测试

- 回答验证覆盖新增金额、日期、指标、页面操作、因果结论。
- 提示注入参数覆盖用户问题、原始事件、收入分类名称、结算公司名称和经营证据。
- Playwright 新增普通用户看不到或调用不到 Agent。
- SQLite 临时故障整批重试与第二次失败测试纳入发布清单。

## 已完成验证

以下命令均已通过：

```text
backend release gate: 52 passed, 497 deselected
backend full suite:    549 passed, coverage 86%
frontend unit:         328 passed
frontend Playwright:   36 passed
frontend build:        passed
backend Ruff:          passed
git diff --check:      passed
```

本地 `backend/.venv` 缺少 `pytest-xdist`，因此 CI 形式的 `-n 2 --dist loadscope` 在收集前报“不认识参数”，不是测试失败。完整后端套件已用以下串行等价命令运行：

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest --cov=app --cov-report=term-missing
```

CI 会由 `python -m pip install -e ".[dev]"` 安装 `pytest-xdist`，并使用 Python 3.12、`AUTOLAVA_MODEL_ADAPTER=fake`。

## 双轴 code review 结果

### Standards

没有硬性规范违规。

唯一判断性发现是同一 CI Fake/gate 合同同时存在于：

- `backend/tests/release/test_agent_release_manifest.py`
- `backend/tests/test_deployment_config.py`

已在工作树中删除 `test_deployment_config.py` 的重复断言，并通过：

```text
3 passed:
- tests/release/test_agent_release_manifest.py
- tests/test_deployment_config.py::test_ci_runs_backend_and_frontend_checks_without_containers
```

该修正不在 `3aea360` 内，已随本交接提交一并保存。

### Spec

Spec 审查发现以下未完成项。它们是下一窗口的首要工作，不能关闭 #74。

#### P1：比较型 EvidenceBundle 仍可能混合两个 SQLite 版本

规范要求：“SQLite 并发测试证明一个 EvidenceBundle 不混合两个数据版本。”

`backend/app/agent/business_evidence.py` 对普通 comparison 分别调用两次 `_read_snapshot`，每次都会新建 session/事务。两次读取之间若发生提交，当前期间和比较期间会来自不同版本。

当前新增并发测试只覆盖没有 comparison 的 `average_revenue_per_car`，没有覆盖该路径。

建议下一步：

1. 先写失败测试：第一次 period snapshot 后由另一连接提交，断言 current 与 comparison 仍来自同一版本。
2. 将一个 EvidenceBundle 所需的分类解析、主期间、比较期间和相关补充读取收进同一个只读 session/事务。
3. 确保重试时丢弃整个 session 和全部已读中间结果。

#### P1：临时故障整批重试没有覆盖所有 EvidenceBundle 路径

规范要求：“临时故障只整批重试一次，第二次失败不保留部分证据。”

当前问题：

- 收入分类解析在普通指标的重试循环之外；
- 分组和极值分支在该重试循环之前直接返回；
- 第二次失败测试在第一次查询就失败，未证明“已经读取部分数据后”不会保留部分证据。

建议下一步：

1. 先为分类解析、分组、极值分别写临时 locked/busy 失败测试。
2. 再写“第一条查询成功、后续查询失败；整批重试；第二次仍在后续失败”的测试。
3. 把一次 request 的全部 DB 工作放入统一的 outer batch retry；每次 attempt 使用全新只读 session 和本地结果。

#### P1：无证据 direct answer 的声明拦截仍可绕过

规范要求：“模型不能添加后端证据中不存在的新金额、日期、指标、页面操作或因果结论。”

当前有限正则不会拦截例如：

- `本月利润翻倍`
- `今天收入异常`
- `天气拖累了收入`
- `我已进入台账`

不要继续无边界地枚举同义词。更安全的方向是让 `direct_answer` 只适用于后端能确定为安全的一般帮助/能力问法；任何可能涉及当前门店经营事实、时间、指标、数量、分析或页面状态的请求必须走 evidence/action/clarify，否则关闭式失败。

先写上述四个红态测试，并补一组应继续允许的一般能力说明测试。

#### P2：五类提示注入测试没有经过真实来源边界

规范要求分别覆盖用户问题、原始事件、收入分类名称、结算公司名称和经营证据。

当前参数化测试只是把五个 payload 拼进同一个 fake collector summary；这证明最终摘要不可被模型改写，但没有证明恶意值经过真实：

- HTTP 用户问题；
- `StoreDailyRecord.activity`；
- `IncomeCategory` / `DailyIncomeItem.category_name`；
- `SettlementCompany.name` / `SettlementRecord.company_name`；
- `BusinessEvidenceCollector` 输出；

之后仍保持数据身份且不能改变 scope、计划、金额或最终回答。

建议增加真实 SQLite + Fake Model Adapter 的 HTTP/integration vertical slices，并断言当前门店 ID、金标准金额、最终安全摘要以及不存在攻击者要求的动作/跨店数据。

## 推荐继续顺序

1. 读取 `CONTEXT.md` 和本交接；不要修改 `.scratch/`。
2. 检查当前工作树和最近提交，保存 Standards 去重修正。
3. 按上面三个 P1 依次执行 TDD 红→绿，每个切片只测试公共 seam：
   - `BusinessEvidenceCollector` 的单批只读快照；
   - Agent HTTP interface；
   - Model Adapter / workflow 输出。
4. 补 P2 的真实来源注入 integration tests。
5. 把新增测试 node 加入 `agent_release_cases.json`，确保专用 gate 真正执行它们。
6. 运行：

```powershell
cd backend
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -m agent_release_gate --strict-markers
.\.venv\Scripts\python.exe -m pytest --cov=app --cov-report=term-missing

cd ..\frontend
npm test
npm run build
npm run test:e2e
```

7. 再次运行双轴 code review，固定点仍使用 `6eec1e7`：

```text
git diff 6eec1e7...HEAD
git log 6eec1e7..HEAD --oneline
```

8. 修完所有 P1/P2 后再决定是否评论/关闭 #74；本窗口没有执行 issue 写操作，也没有 push。

## 重要约束

- 领域词汇遵守根目录 `CONTEXT.md`。
- 主要后端 seam 是管理员向当前门店 Agent 发送消息的 HTTP interface；不要测试 LangGraph 私有节点或 SQL 形状。
- Model Interface 测试必须使用 Fake Model Adapter。
- 真实密钥不得进入聊天、Git、日志、前端或 `.env.example`。
- 当前生产形态为单 FastAPI 进程、单 Uvicorn worker、SQLite WAL；模型网络调用必须离开 SQLite 事务。
- 保留用户已有文件和修改，尤其不要修改、删除或提交 `.scratch/`。
