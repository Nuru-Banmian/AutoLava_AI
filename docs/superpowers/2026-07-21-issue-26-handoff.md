# Issue #26 交接：把公司结算收入纳入经营分析

> 2026-07-22 更新：本文记录的“仅完整自然月纳入”规则已被后续产品决定取代。当前规则是查询区间只要与开票月份有重叠，就纳入该月全部已确认公司结算。

## 当前状态

- 分支：`codex/company-settlement`
- 已提交实现：`e41a3f1 feat: include settlement income in monthly analytics (#26)`
- 实现起点：`cacedc9 feat: add settlement payment confirmation (#25)`
- 代码审查后的修正与本文一起提交为 `fix: preserve daily analytics contracts (#26)`；用 `git log -2 --oneline` 获取实际 SHA。
- GitHub #26 仍显示被 #25 阻塞，但本分支的 `cacedc9` 已实现 #25。GitHub 工单本身尚未关闭。

## 已实现内容

1. 后端经营分析按与查询区间重叠的自然月聚合已确认公司结算收入；不依赖功能开关，因此关闭公司结算后历史金额仍保留。
2. 单月、多月和部分月份区间均返回每日台账、重叠月份的已确认公司结算与区间总收入；每个月的趋势行包含月度总收入。
3. 部分月份区间中的每日台账只统计所选日期，公司结算则按重叠月份整笔纳入；公司结算仍不分配到具体日期。
4. 既有 `kpis.total_revenue`、`comparison_kpis.total_revenue`、每日趋势、分类构成、营业日均和客单价继续保持每日台账语义。
5. 营业记录中的完整月汇总展示“日常营业额 / 公司结算收入 / 月度总收入”；多月时使用“月度总收入汇总”。汇总容器是有可访问名称的 `region`。
6. 新增 Playwright 回归，覆盖创建结算公司、登记/修正开票记录、到账确认、撤销到账确认、月份/门店切换、月度总收入等式，以及 320px 下公司结算页和营业记录汇总无水平滚动。
7. 管理端 E2E 增加按门店启用公司结算；旧 daily-flow 夹具同步新建空金额规则。
8. `frontend/src/test/setup.ts` 增加 Node 环境守卫，使 `global-setup.test.ts` 能进入全量 Vitest。

## 代码审查结果与已做修正

`code-review` 技能以 `cacedc9` 为固定点并行完成 Standards / Spec 审查。

审查指出：

- 顶层 `monthly_total_income` 会同时代表多月区间，违反 `CONTEXT.md` 对“月度总收入”的单月定义。
- 不应覆盖既有 `kpis.total_revenue` 和比较 KPI 的每日台账语义。
- 不完整日期区间不应返回看似完整月份的 `monthly_total_income`。
- 新三卡汇总需要在 320px 的营业记录页面直接验证。
- 另有 Data Clumps / 重复计算的判断性建议。

交接提交已处理以上问题：

- 顶层改为 `income_summary.total_income`；单月 UI 才称“月度总收入”，多月称“月度总收入汇总”。
- 恢复既有 KPI 字段语义。
- 后续产品决定已把部分区间改为纳入所有重叠月份的整笔公司结算；当前实现与 `CONTEXT.md` 保持一致。
- 月度趋势按 `monthly_total_income ?? revenue` 选择正确值。
- 新增 `IncomeSummary` / `MonthlyRevenue` TypeScript 类型，并抽取后端月度行构造函数。
- E2E 在 320px 下进入 `/database` 验证三项汇总和无溢出。

## 已通过验证

审查前的完整门禁：

- 后端：`347 passed`，Ruff 全通过。
- 前端 Vitest：`273 passed`。
- 前端生产构建：通过。
- Playwright：`11 passed`。

审查修正后的定向验证：

- `backend/tests/api/test_charts.py` + `backend/tests/services/test_analytics.py`：`22 passed`。
- Ruff：通过。
- `BusinessAnalysisCard.test.tsx`：`5 passed`。
- 前端生产构建：通过。
- `settlement-analysis-flow.spec.ts`：`1 passed`。

## 下一会话必须完成

1. 查看最近提交并确认工作树干净：

   ```powershell
   git status --short
   git diff --check
   git log -2 --oneline
   ```

2. 在审查修正后按 `README.md` 重新执行最终完整门禁。后端测试使用一次性数据库，并把临时目录放到仓库可写位置：

   ```powershell
   $testTemp = 'D:\work\myself\AI-try\AutoLava-AI\.scratch\pytest-final-26'
   New-Item -ItemType Directory -Force -Path $testTemp | Out-Null
   $env:TEMP = $testTemp
   $env:TMP = $testTemp
   $env:AUTOLAVA_DATABASE_PATH = Join-Path $testTemp 'autolava-test.sqlite3'
   Set-Location backend
   uv run --extra dev ruff check .
   uv run --extra dev pytest --cov=app --cov-report=term-missing
   ```

   ```powershell
   Set-Location frontend
   npm ci
   npm test
   npm run build
   npx playwright install chromium
   npx playwright test --reporter=line
   ```

3. 删除仅由测试生成的 `.scratch/pytest-final-26`，不要删除其他用户文件。
4. 复查 `git diff cacedc9...HEAD`，确认上述 Standards / Spec 问题已关闭。
5. 如果完整门禁暴露新问题，修复并另行提交；否则不需要再制造空提交。
6. 最终确认工作树干净。除非用户另行要求，不要推送、关闭 Issue 或修改 GitHub 标签。

## 关键文件

- `backend/app/services/analytics.py`
- `backend/app/schemas/charts.py`
- `backend/tests/api/test_charts.py`
- `backend/tests/services/test_analytics.py`
- `frontend/src/api/types.ts`
- `frontend/src/components/BusinessAnalysisCard.tsx`
- `frontend/src/components/BusinessAnalysisCard.test.tsx`
- `frontend/tests/settlement-analysis-flow.spec.ts`
- `frontend/tests/admin-flow.spec.ts`
- `frontend/tests/daily-flow.spec.ts`
- `frontend/tests/responsive.spec.ts`
