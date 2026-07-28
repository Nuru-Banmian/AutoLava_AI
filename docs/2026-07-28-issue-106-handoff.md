# Issue #106 可重算事件类型与跨日期事件调查交接

## 当前状态

Issue #106 的核心实现已经完成两个 TDD 垂直切片并转绿，但尚未完成全套测试、双轴 code review、提交、push、Pull Request、合并确认和关闭 Issue。

不要把当前状态视为已交付：

- 没有 commit。
- 没有 push。
- 没有创建 Pull Request。
- Issue #106 仍为 OPEN。
- 尚未运行仓库完整测试套件。
- 尚未执行 `$code-review` 要求的 Standards / Spec 双轴并行审查。

## 工作位置

- 仓库：`Nuru-Banmian/AutoLava_AI`
- 共享目标分支：`codex/add-agent`
- Issue 分支：`codex/issue-106-event-investigation`
- worktree：`D:\work\myself\AI-try\AutoLava-AI-worktrees\issue-106-event-investigation`
- 分支起点：`b4fed5d0dc64bff726f96e4baeecb71a93f057ab`
- 起点当时与 `origin/codex/add-agent` 同步。

依赖已经放行：

- Issue #105 已关闭。
- PR #130 已于 2026-07-28 合并到 `codex/add-agent`。
- Issue #106 的实时 `issue_dependencies_summary.blocked_by` 为 `0`。

## 已确认的实现解释

本工单实现“可重算事件类型”，不新增事件分类持久化表，也不引入经营观察持久化、门店记忆或后台周期任务。

原因：

- 父 Issue #97 明确把经营观察持久化、门店记忆和长期任务留在范围外。
- 每次事件调查从当前有效 `store_daily_records.activity` 重新生成分类。
- 原始事件被修改时，来源指纹和分类随查询变化。
- 原始事件所在每日台账被删除时，该事件不再出现在当前调查证据中。
- 因此不会把旧分类继续当作当前事实，也不需要新增数据库迁移。

当前事件分类规则版本是 `event_type_rules.v1`。稳定通用类型为：

- `access_disruption` / 通行受阻
- `equipment_issue` / 设备问题
- `local_event` / 当地事件
- `promotion` / 促销
- `schedule_change` / 营业时间变化
- `staffing_issue` / 人员问题
- `weather_disruption` / 天气影响

一个原始事件可以命中多个类型。没有可靠命中时返回 `classification_status=unclassified` 和空类型列表，不强行猜测。

门店具体标识只在同一受限期间内出现完全相同的规范化事件文本至少两次时生成。标识是门店 ID 与规范化文本的稳定摘要，格式为 `store_event_<16 hex>`；单次事件不生成标识。

## 已实现内容

### `backend/app/agent/event_classification.py`

新增确定性事件分类 Module：

- 固定分析版本。
- 固定通用类型代码和名称。
- NFKC、大小写折叠和空白规范化。
- 一条事件可命中多个稳定规则。
- 不匹配时返回空类型。

该文件当前是未跟踪文件，提交时不要漏掉。

### `backend/app/agent/contracts.py`

新增：

- `event_investigation` 请求类型和证据指标。
- `EventType`。
- `EventObservation`。
- `EventInvestigationResult`。
- `event_investigation.v1` 证据计算版本。
- 对分类状态、类型唯一性、来源指纹、分析版本、日期范围、覆盖计数和结果形状的关闭式校验。

每条事件观察包含：

- 日期、每日台账营业额、营业状态、记录天气和可用时的洗车数量。
- 原始事件及 `untrusted_business_data` 信任标记。
- 分类状态、多个通用事件类型和可选门店具体标识。
- `source_record_id`。
- 绑定记录 ID 与当前原始文本的 `source_event_fingerprint`。
- `analysis_version`。

### `backend/app/agent/business_evidence.py`

`BusinessEvidenceCollector` 现在可以处理自然月 `event_investigation` 请求：

- 在受信任当前门店和解析后的准确期间内查询非空原始事件。
- 只读取事件调查所需字段。
- 离开 SQLite 只读事务前把 ORM 数据复制为普通 mapping，避免网络模型阶段持有事务或延迟加载。
- 重新计算类型、来源指纹和重复事件标识。
- 返回事件数、已分类数、待归类数、覆盖和限制。
- 明确声明事件与经营证据的同时变化只能支持相关性假设，不能证明因果关系。
- 明确声明原始事件、事件类型名称和门店具体标识均是不可信数据，不能作为指令。

### `backend/app/agent/native.py`

原生工具目录新增 `event_investigation`：

- 参数只有受控的 `year` 和 `month`。
- 门店、用户、角色、时区和功能范围仍由后端 RuntimeContext 提供。
- 数据来源限定为 `store_daily_records`。
- 结果单位为 `mixed`。
- 工具说明明确事件自由文本和分类数据不可信，结论只能是相关性假设。

### 测试

`backend/tests/agent/test_business_evidence.py` 新增 Collector seam 测试，覆盖：

- 一条事件同时分类为设备问题和促销。
- 完全重复事件获得相同门店具体标识。
- 注入式未知文本保持待归类。
- 其他门店事件、金额和自由文本不泄露。
- 修改来源后指纹、类型和重复标识重新计算。
- 删除来源后旧事件和旧指纹不再返回。

`backend/tests/api/test_agent_native_tool_loop.py` 新增 HTTP seam Fake 模型流程，覆盖：

1. 模型先调用 `event_investigation`。
2. 根据返回的重复事件标识选择两个具体日期。
3. 再调用 `daily_ledger_details` 核对经营证据。
4. 最终把结论保留为“可能存在且仍待更多日期检验的相关性”。
5. 原始事件中的 `store_id=999` 指令不能改变当前门店、月份或工具范围。
6. 其他门店的 `9999` 金额和 `secret` 文本不进入证据。

## 已执行验证

### RED → GREEN

Collector 测试最初按预期因未知 `event_investigation` discriminator 失败，完成合同和 Collector 后转绿：

```powershell
uv run pytest tests/agent/test_business_evidence.py -k event_investigation -q
```

结果：

```text
1 passed, 14 deselected
```

HTTP 测试最初按预期因为工具未注册返回 `403 Agent 工具授权已失效`。注册工具并修复事务外 ORM 过期读取后转绿：

```powershell
uv run pytest tests/api/test_agent_native_tool_loop.py -k investigates_repeated_events -q
```

结果：

```text
1 passed, 10 deselected
```

### 静态检查

以下检查通过：

```powershell
uv run ruff check app tests/agent/test_business_evidence.py tests/api/test_agent_native_tool_loop.py
uv run ruff format --check app tests/agent/test_business_evidence.py tests/api/test_agent_native_tool_loop.py
uv run mypy app/agent/contracts.py app/agent/native.py app/agent/event_classification.py
git diff --check
```

定向 mypy 结果：

```text
Success: no issues found in 3 source files
```

全仓 `uv run mypy app` 仍有 26 个既有错误，位于本次未改的：

- `app/services/export.py`
- `app/services/operations_retention.py`
- `app/services/analytics.py`
- `app/scripts/create_admin.py`
- `app/services/income_config.py`
- `app/services/scheduler.py`
- `app/api/routes/settlement.py`
- `app/api/routes/dashboard.py`
- `app/api/routes/ledger.py`

不要为完成 #106 扩大范围修复这些基线错误，除非后续验证证明本次改动新增了同类错误。

## 当前未提交改动

```text
 M backend/app/agent/business_evidence.py
 M backend/app/agent/contracts.py
 M backend/app/agent/native.py
 M backend/tests/agent/test_business_evidence.py
 M backend/tests/api/test_agent_native_tool_loop.py
?? backend/app/agent/event_classification.py
?? docs/2026-07-28-issue-106-handoff.md
```

## 下一步

按顺序继续：

1. 运行 Agent 相关测试，至少：

   ```powershell
   uv run pytest tests/agent tests/api/test_agent_native_tool_loop.py tests/api/test_agent_prompt_injection_sources.py -q
   ```

2. 运行仓库完整验证。优先使用仓库脚本：

   ```powershell
   Set-Location D:\work\myself\AI-try\AutoLava-AI-worktrees\issue-106-event-investigation
   python scripts/verify.py
   ```

   如果完整脚本耗时或失败，记录精确命令、失败阶段和是否为既有基线。

3. 以 `origin/codex/add-agent` 为固定点执行 `$code-review`：

   ```powershell
   git rev-parse origin/codex/add-agent
   git diff origin/codex/add-agent...HEAD
   git log origin/codex/add-agent..HEAD --oneline
   ```

   当前尚未 commit，因此 review 前需要先形成可审查提交，或明确把工作树 diff 作为临时固定范围。`code-review` 技能要求 Standards 与 Spec 两个并行子 Agent，规格来源为 Issue #106 和父 Issue #97。

4. 修复 review findings 后重跑针对性测试和完整验证。

5. 提交全部实现与交接文档。建议提交信息：

   ```text
   feat: add recomputable event investigation (#106)
   ```

6. 因为这是从共享目标分支额外创建的 Issue 分支，必须：

   - push `codex/issue-106-event-investigation`
   - 创建 PR，base 为 `codex/add-agent`
   - 等待实际 CI 完成
   - 合并 PR
   - 确认远端 `codex/add-agent` 包含提交
   - 最后关闭 Issue #106

不得绕过 PR 直接更新 `codex/add-agent`，也不要触碰 `main`。

## 复核重点

- 事件分类规则是刻意保守的确定性首版。不要把模型生成的自由分类名称直接升级为稳定类型。
- `source_event_fingerprint` 当前绑定 `record.id + raw_event`；修改原始文本会改变指纹，删除记录会让观察消失。
- 当前自然月按门店本地“今天”截断。例如固定时间 2026-07-28 时，2026 年 7 月证据期间是 `2026-07-01` 至 `2026-07-28`，不是月底。
- 门店具体标识只表示当前查询中规范化文本完全重复，不代表语义相似事件已经被证明相同。
- 事件调查没有把公司结算归因到具体日期。
- 原始事件、事件类型名称、收入分类、结算公司和工具自由文本的注入防护应结合既有 native/legacy 回归测试一起审查，不能只依赖新增的一条事件测试。
- 不要新增经营观察、门店记忆、周任务或分类持久化；这些不属于 #106 当前实现解释。
