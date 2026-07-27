# Issue #74 交接：双轴审查已清零，等待最终提交

## 当前状态

- 仓库：`Nuru-Banmian/AutoLava_AI`
- Issue：[#74 建立 Agent 安全评估与发布否决门禁](https://github.com/Nuru-Banmian/AutoLava_AI/issues/74)
- 当前分支：`codex/add-agent`
- 审查固定点：`6eec1e7d81eadc2dd97d6d31e446f1c3e76b50bf`
- 当前 HEAD：`a5b41a7 fix: complete Agent safety release gate review`
- 分支相对 `origin/codex/add-agent`：ahead 3
- 当前实现修复仍未提交。
- Issue #74 仍为 open，评论数为 0。
- 没有 push，没有评论或关闭 Issue。
- 没有修改、删除或提交 `.scratch/`。

开始下一窗口时先运行：

```powershell
git status --short --branch
git log -5 --oneline --decorate
Get-Content -Raw docs/superpowers/2026-07-27-issue-74-handoff.md
```

当前工作树中的 Issue #74 相关修改：

```text
.github/workflows/ci.yml
backend/app/agent/business_evidence.py
backend/app/agent/workflow.py
backend/tests/agent/test_workflow.py
backend/tests/api/test_agent.py
backend/tests/api/test_agent_prompt_injection_sources.py
backend/tests/release/agent_release_cases.json
backend/tests/release/test_agent_release_manifest.py
docs/superpowers/2026-07-27-issue-74-handoff.md
frontend/package.json
frontend/scripts/validate-agent-release-manifest.mjs
```

## 本窗口完成的修复

### 1. direct_answer 改为后端固定能力说明

合法的一般能力/使用说明问法仍由后端 allowlist 控制，但不再返回模型提供的
`plan.answer`。后端固定返回：

```text
我可以说明能力范围，并基于当前门店的可验证证据回答经营问题。
```

因此即使模型在合法能力问法下返回“我可以告诉你本月利润翻倍”，最终响应也不会包含
模型自有经营声明。非 allowlist 问法继续关闭式 `safe_failure`。

已删除不再需要的：

- `SAFE_DIRECT_ANSWER_PREFIX`
- `DIRECT_ANSWER_BUSINESS_CLAIM`
- `NAVIGATION_TARGET`

新安全测试
`test_capability_direct_answer_never_returns_model_owned_claims`
已加入 release manifest。

### 2. session ownership 成为结构性约束

`BusinessEvidenceCollector.collect()` 的 outer retry loop 是普通经营指标证据的唯一
session owner：

- 每个 attempt 调用一次新的 `self._session_factory()`；
- 分类解析、主期间、比较期间、分组和每日台账极值读取必须接收同一个
  `AsyncSession`；
- 四个私有读取方法不再拥有可选的“自行创建 session”分支；
- `_borrow_session` 与重复 session adapter 逻辑已删除；
- 失败 attempt 的 session 和部分结果整批丢弃；
- 模型网络调用仍不进入 SQLite 事务。

这同时清除了初次 Standards 审查的 Duplicated Code，以及复审提出的
Speculative Generality 判断性 finding。

### 3. manifest 增加独立、机器可读金标准

所有声明 `gold_amount` 的 case 都有非空、纯数值 `gold` 对象。

`monthly-total-gold`：

```json
{
  "daily_ledger_revenue": 240,
  "confirmed_settlement_income": 160,
  "monthly_total_revenue": 400
}
```

`revenue-analysis`：

```json
{
  "current_daily_ledger_revenue": 160,
  "current_confirmed_settlement_income": 0,
  "current_total_revenue": 160,
  "comparison_daily_ledger_revenue": 100,
  "comparison_confirmed_settlement_income": 0,
  "comparison_total_revenue": 100,
  "total_revenue_change": 60,
  "daily_ledger_revenue_change": 60,
  "confirmed_settlement_income_change": 0
}
```

`test_agent_release_manifest.py` 使用独立固定值验证 manifest；经营分析 HTTP 测试也
直接断言同一组真实 fixture 结果。

### 4. Playwright manifest 绑定实际 collected tests

`frontend_cases` 现在绑定 4 个具体完整标题：

- `administrator restores, switches, and permanently resets per-store conversations`
- `desktop business records action is user-triggered, prefills months, and does not overflow`
- `mobile business records action is user-triggered, prefills months, and does not overflow`
- `ordinary users cannot see or invoke the Agent`

新增：

```text
frontend/scripts/validate-agent-release-manifest.mjs
npm run test:agent-release-manifest
```

脚本真实运行 Playwright `test --list`，按测试文件和完整标题核对 collection，不依赖
静态字符串搜索。CI 已加入该命令；后端 manifest 测试同时验证 manifest 结构、
package script 和 CI 接线。

### 5. 经营证据提示注入改为真实 SQLite 来源

已删除合成的 `EvidenceOutputAttackCollector`。

第五类攻击字符串现在真实写入 `StoreDailyRecord.weather`，再通过：

```text
SQLite
→ BusinessEvidenceCollector
→ daily_ledger_revenue / recorded_weather 分组
→ HTTP Agent interface
→ Fake Model Adapter
→ 后端校验摘要
```

测试断言：

- result row 的 `label` 和 `key` 保留攻击原文；
- `value` 为金标准 `240`；
- `current_store.id` 正确；
- 最终回答等于持久化的后端摘要；
- `action` 为 `null`；
- 另一门店金额 `7777` 不进入证据或回答。

## 双轴复审结果

固定点始终为：

```text
6eec1e7
```

### Standards

- documented-standard violations：0
- baseline smells：0
- P1/P2：0
- 初次 Duplicated Code 已修复。
- 第一次复审提出的可选 session ownership / Speculative Generality 已继续修复。
- 窄复审确认四个内部读取方法强制接收外层 session，且没有引入新 finding。

### Spec

- missing/partial requirements：0
- scope creep：0
- implemented-but-wrong：0
- P1/P2：0

Spec 复审明确确认以下四项已闭环：

1. 固定能力说明完全忽略模型夹带声明；
2. gold amounts 独立且机器可读；
3. Playwright manifest 绑定实际 collected titles；
4. business evidence 注入来自真实 SQLite 并走真实 collector/HTTP 路径。

## 已通过门禁

完整门禁：

```text
backend Ruff:                    passed
backend release gate:            57 passed, 504 deselected
backend full suite:              561 passed, coverage 86%
frontend unit:                   328 passed
frontend build:                  passed
frontend Playwright collection:  4 manifest tests validated
frontend Playwright:             36 passed
git diff --check:                passed
```

完整后端与前端门禁完成后，Standards 最后一项纯结构 refactor 又执行了：

```text
backend Ruff:                    passed
business evidence tests:         11 passed
backend release gate:            57 passed, 504 deselected
frontend Playwright collection:  4 manifest tests validated
git diff --check:                passed
Standards narrow re-review:      0 findings
```

唯一已知 warning 是既有的 Starlette/httpx deprecation warning，不是测试失败。
前端 build 仍有既有的大 chunk warning，不是构建失败。

## 下一窗口严格顺序

实现、门禁与双轴复审已经完成，没有已知红态或审查 finding。下一窗口只需做最终发布前
核对：

1. 重新读取本交接文档并检查 `git status`。
2. 确认 `.scratch/` 没有出现在待提交文件中。
3. 检查最终 diff，必要时运行：

   ```powershell
   git diff --check
   ```

4. 若无需继续改代码，可提交当前 Issue #74 相关工作树修改。
5. 不要 push。
6. 不要评论或关闭 Issue #74，除非用户后续明确授权。

## 提交、Issue 与 push 约束

- 当前窗口没有创建新提交。
- 可以在最终 diff 核对后提交。
- 不要修改、删除或提交 `.scratch/`。
- 不要 push。
- 不要评论或关闭 Issue #74。
- 不要使用真实模型密钥；所有测试继续只用 Fake Model Adapter。
