# Issue #41 交接：压缩营业记录详情并正确呈现洗车数量

## 当前状态

- GitHub Issue：`#41`，标题“压缩营业记录详情并正确呈现洗车数量”。
- 专属分支：`codex/issue-41-business-record-detail`。
- 独立 worktree：`D:\work\myself\AI-try\AutoLava-AI-worktrees\issue-41`。
- 当前起点：`83952e0`（当时的 `origin/main`，已经包含阻塞项 #37、#38）。
- #41 的原生阻塞项 #37、#38 均已关闭；开始实现时 `issue_dependencies_summary.blocked_by` 为 `0`。
- 实现与测试已经完成，等待提交；工作树包含本次前端修改和本交接文档。
- 已按 `/implement` 要求执行双轴 `/code-review`，最终 Standards 与 Spec 均为 `0 findings`。
- 不要在仓库根 worktree 或其他 Issue 分支继续修改；进入上述 #41 worktree 后继续。

## Issue 验收范围

1. 日期与带文字的营业状态徽标在同一行，状态不能只靠颜色表达。
2. 营业额和记录天气保留为主要紧凑摘要，洗车数量不再占独立摘要卡。
3. 仅当门店启用“记录洗车数量”且值大于零时，显示“洗车 N 辆”；零、空值、设置关闭都不占空间。
4. 自由文本统一标为“事件”，历史内容不改写。
5. 桌面和手机保持清楚层级、键盘可达、无横向滚动。
6. 组件/浏览器测试覆盖三种营业状态、洗车正数/零/空/关闭设置及响应式详情。

## 已完成实现

### `frontend/src/components/RecordDetailPanel.tsx`

- `RecordDetailPanelProps` 新增必填的 `washCountEnabled`。
- 日期标题旁新增带文字的状态胶囊：
  - 营业
  - 休息
  - 提前休息
  - 未录入日期显示“未录入”
- 状态文字始终可见，颜色只是辅助。
- 主要摘要压缩为有可访问名称的 `region`（`营业摘要`），只包含营业额和天气。
- 洗车数量移出摘要卡；仅在设置开启且 `wash_count` 为正数时显示紧凑文本“洗车 N 辆”。
- 自由文本标签从“活动”改为领域术语“事件”。
- 事件内容使用 `whitespace-pre-wrap`、`break-words` 和 `overflow-wrap:anywhere`，保留历史文本/换行并防止长文本产生横向滚动。

### 数据流接线

- `frontend/src/pages/BusinessRecordsPage.tsx`
  - 桌面详情和移动详情均传入 `selected.wash_count_enabled ?? true`。
- `frontend/src/components/MobileRecordSheet.tsx`
  - 解构并向 `RecordDetailPanel` 转发 `washCountEnabled`。

### 测试变更

- `frontend/src/components/RecordDetailPanel.test.tsx`
  - 覆盖日期旁文字状态。
  - 覆盖营业、休息、提前休息三种状态。
  - 覆盖洗车正数、零、`null`、关闭设置。
  - 覆盖营业额/天气主摘要和“事件”标签。
- `frontend/src/components/MobileRecordSheet.test.tsx`
  - 更新为紧凑状态/洗车文本，同时保留焦点恢复断言。
- `frontend/src/pages/BusinessRecordsPage.test.tsx`
  - 更新旧文案断言为“洗车 8 辆”。
- `frontend/tests/responsive.spec.ts`
  - 门店夹具显式启用 `wash_count_enabled`。
  - 320px 详情验证日期旁状态、具名营业摘要、正数洗车、事件、无旧“洗车数量”卡片、抽屉无横向溢出。
  - 320px 详情继续覆盖休息/零值和提前休息/空值；桌面详情覆盖主要摘要、正数洗车和无横向溢出。
  - 独立浏览器用例验证关闭门店设置后不显示历史正数洗车数量。
  - 既有关闭抽屉后的焦点恢复验证继续保留。

## TDD 记录

Issue 已明确预先约定两个测试 seam：`RecordDetailPanel` 组件公开渲染行为和浏览器营业记录详情流程。

1. 先修改组件测试，真实得到红灯：11 项中 7 项失败。
2. 完成最小组件实现后，相关 12 项组件/移动抽屉测试转绿，生产构建通过。
3. 浏览器测试先要求具名 `营业摘要` region，真实红灯（元素不存在）。
4. 添加最小语义实现后，320px 浏览器流程转绿。

## 已通过验证

前端最终完整门禁：

- `npm test`：`36` 个测试文件、`306 passed`。
- `npm run build`：通过。
- `npm run test:e2e`：`28 passed`。
- 构建仍有仓库既有的大 chunk 警告；不是本 Issue 新失败。
- `git diff --check`：通过（写交接文档之前执行）。

后端：

- 在 `backend/.venv` 通过 `uv pip install --python .venv\Scripts\python.exe -e ".[dev]"` 安装了测试依赖；该目录应保持未跟踪/忽略。
- `.\.venv\Scripts\python.exe -m ruff check .`：通过。
- 后端没有代码变更。

## 后端主线门禁异常

后端全套 pytest 未能作为“全绿”完成，已确认是当前 `origin/main` 的既有问题，与本次纯前端 diff 无关：

1. `tests/api/test_admin.py::test_store_creation_has_no_legacy_work_hours_payload`
   - 单独稳定复现。
   - 期望 `201`，实际 `422`。
2. `tests/api/test_admin_revocation.py::test_admin_mutation_revalidates_actor_after_lock_wait[store-create]`
   - 会无限等待 `while not SQLITE_WRITE_LOCK._waiters`。
   - `store-create` 请求在进入写锁等待之前已经结束，因此 `_waiters` 永远不会出现；测试循环没有检查 mutation task 是否已完成。
   - 两次命令超时曾留下并发 pytest 子进程，已经按核实的 PID 和命令行全部终止；交接时没有 #41 的 Python/Node 测试进程运行。

不要在 #41 中顺手修复上述后端主线问题，除非用户明确扩大范围。若需要记录最终后端其余结果，可在排除该悬挂 node id 后运行：

```powershell
Set-Location 'D:\work\myself\AI-try\AutoLava-AI-worktrees\issue-41\backend'
.\.venv\Scripts\python.exe -m pytest `
  --deselect 'tests/api/test_admin_revocation.py::test_admin_mutation_revalidates_actor_after_lock_wait[store-create]'
```

预计仍会报告上面的独立 `422` 失败；应作为主线基线异常记录，不要把它归因于 #41。

## Code review

- 固定审查点：`83952e0`。
- Standards 初审：`0 findings`。
- Spec 初审发现浏览器覆盖只验证手机端营业/正数洗车，未完整覆盖三种状态、零值、空值、关闭设置和桌面详情。
- 补齐浏览器覆盖后再次复核：`0 findings`。

## 当前修改文件

- `frontend/src/components/RecordDetailPanel.tsx`
- `frontend/src/components/RecordDetailPanel.test.tsx`
- `frontend/src/components/MobileRecordSheet.tsx`
- `frontend/src/components/MobileRecordSheet.test.tsx`
- `frontend/src/pages/BusinessRecordsPage.tsx`
- `frontend/src/pages/BusinessRecordsPage.test.tsx`
- `frontend/tests/responsive.spec.ts`
- `docs/superpowers/2026-07-25-issue-41-handoff.md`
