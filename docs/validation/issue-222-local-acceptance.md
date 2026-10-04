# Issue #222：本地整体验收

验收日期：2026-10-04（Asia/Shanghai）。规格：[Issue #222](https://github.com/Nuru-Banmian/AutoLava_AI/issues/222)。本报告接续同日交接中的已完成工作，只补全中断的后端完整测试和普通浏览器完整复查；没有重新实现六个子工单、重新导入数据库或修改产品源码及测试。

## 验收范围与最终界面

本地产品版本：`40f6cd18f491e680100ea33a9265bd4f98a9e32e`；固定审查基线为 T1 前的 `6ac39abf6053f57a2735738da357b7fb2ad18746`。完整改版提交依次为 `917a8a3`、`07195cc`、`4f9436a`、`c85568c`、`b33c4e2`、`40f6cd1`，覆盖已完成的 #223–#228。

交接已核实本地 HEAD 与 T6 合并提交 `2c9d36c12d0e15069f3d34bf901e6e3a64c3fa13` 的内容树均为 `92d48c0b3b184a5d3e76ae867f54c9c091a04938`。本次没有重新同步远程分支；验收依据是上述本地版本。

最终界面遵循用户后续明确反馈和 [#227 验收记录](issue-227-grouped-performance.md) 的“最新交互调整”：保留精简布局、原主题蓝色，以及日历直接点击 / 触摸进入详情；不恢复独立读数下拉、常驻日期读数、额外“查看每日台账”按钮、趋势覆盖数字 / 有效范围说明、重复门店名及多余文字。较早父规格的相关描述不能覆盖这些后续决定。

## 验证结果

| 证据层次 | 结果 | 来源与限制 |
| --- | --- | --- |
| 前端单元 / 模拟接口 | 35 文件、365 passed | 交接前完整执行 `npm test`，exit 0；jsdom 的 `Window.scrollTo()` 未实现提示不能作为真实滚动证据 |
| 类型、构建与契约 | 通过 | 交接前 `npm run build`、`npm run generate:api-types`、后端 Ruff、OpenAPI / 天气枚举快照检查均 exit 0，生成后 tracked diff 为空；本次源码未变，无须重复执行 |
| 后端完整回归 | **463 passed，0 failed，0 skipped；87% 覆盖率** | 本次在 Windows / Python 3.12.10 上按 CI 的 4 worker / loadscope 完整运行，98.79 秒，exit 0；另外执行 85% 覆盖率门禁，exit 0 |
| 普通完整浏览器：首轮 | **94 passed / 17 skipped / 2 failed** | 交接前 12 workers，exit 1；两个失败和原始快照继续保留，见下方 |
| 首轮失败用例定向重复 | **6 passed** | 交接前两个原样用例单 worker 各重复三次，exit 0；无实现或测试修改，不能据此宣布原因已解决 |
| 普通完整浏览器：本次复查 | **96 passed / 17 skipped / 0 failed / 0 flaky** | 4 workers，2.4 分钟，exit 0；独立输出目录，失败时保留 trace；普通套件主要使用模拟接口 |
| 公开 HTTP + 真实迁移临时 SQLite | 通过 | 交接前运行 `scripts/verify-issue-228-live.py`：三个合成范围独立核算星期 / 天气金额与样本；额外核算收入构成、其他数据与公司结算，不使用生产数据库 |
| 真实本地 HTTP 服务 + 浏览器 | **17 passed / 0 skipped / 0 failed / 0 flaky** | 交接前同一脚本启动真实本地服务，完整结果文件已在本次核对；使用合成数据、独立临时数据库，天气为无数据替身 |

后端本次 4 条警告均为 `StarletteDeprecationWarning`：测试客户端使用 `httpx` 的路径已弃用。警告不是失败，也没有为消除警告修改依赖。Windows 专用启动器测试本次没有跳过。交接前后端首轮在约 51% 被用户要求停止，未完成、exit 1；本次 463 passed 是重新执行完整套件的结果，不将中断轮计为通过。

真实服务验收覆盖 320 / 390 / 768 / 1024 / 1280 五宽度、触摸日历、首页保存、记录分页、分析详情编辑返回、构成金额 / 比例、并排卡片对齐、天气固定顺序、失败重试和迟到响应隔离、草稿、导出、公司结算确认 / 撤销及权限。独立构成算例：每日台账 €999,900,220 加已确认公司结算 €325，合计 €999,900,545；其他数据 €900 与待到账 €800 不计入收入，关闭结算开关后已确认历史金额仍保留。

普通浏览器套件的 17 个跳过项是需要独立真实服务夹具的用例；交接前已经通过真实服务脚本全部执行。不能把普通套件的 skipped 计为通过，也不能将模拟浏览器结果当作真实服务证据。

## 首轮失败证据与解释边界

1. `frontend/tests/home-ledger-flow.spec.ts:160`，1024px 首页创建和修改分类记账用例：在第 201 行等待收入字段值 `120`，5 秒内找不到字段；原快照仍显示首页。
2. `frontend/tests/company-settlement-workbench.spec.ts:395`，1280px 变更记录复核用例：在第 425 行等待“保存开票记录修改”按钮，达到 30 秒用例超时。

原始快照及首轮 `.last-run.json` 保存在 `.autolava-test/issue-222/browser-first-run/`。定向重复材料保存在 `browser-focused/`；本次完整复查使用 `browser-full-rerun/`，没有覆盖首轮目录。没有确认首轮失败属于产品缺陷、测试时序或机器争用，也没有提交相关修复。定向通过和降低并发的完整通过只能说明相应运行结果；**首轮两个失败的原因仍未解决或确认**。

## 两轴审查

沿用交接中已经完成的 `git diff 6ac39ab...HEAD` 两轴审查。本次产品源码和测试没有新增差异，无须重新审查六个子工单。

- **Standards**：无文档规范硬性违规；保留 1 项 P3 非阻塞维护性判断，possible Duplicated Code。`backend/tests/api/test_charts_daily_migrated.py:28–79` 与 `backend/tests/api/test_charts_groups_migrated.py:29–80` 的迁移、SQLite 会话、认证和清理 fixture 近似重复，可在后续共享 helper 并保持各测试独立临时数据库；本次不扩展重构。
- **Spec**：0 项可确认发现。后续主动删除的控件和说明不算规格缺失；台账 / 结算口径隔离、舍入、日期范围、天气顺序、构成合计、返回上下文及失败状态已纳入既有审查。

## 复现与本地材料

后端在 `backend/` 执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -n 4 --dist loadscope --cov=app --cov-report=term --durations=10 -ra --junitxml=../.autolava-test/issue-222/backend-full.xml
.\.venv\Scripts\python.exe -m coverage report --fail-under=85
```

浏览器在 `frontend/` 执行：

```powershell
$env:PLAYWRIGHT_JSON_OUTPUT_NAME = '../.autolava-test/issue-222/browser-full-rerun.json'
npm run test:e2e -- --workers=4 --trace=retain-on-failure --reporter=line,json --output=../.autolava-test/issue-222/browser-full-rerun
```

本次完整输出为 `.autolava-test/issue-222/backend-full.log`、`backend-full.xml`、`backend-coverage-gate.log`、`browser-full-rerun.log`、`browser-full-rerun.json`。真实服务结果为 `.autolava-test/issue-228/playwright-results.json`（startTime `2026-10-04T14:45:43.887Z`）及 `fixture-and-http-evidence.json`；截图和几何材料在同目录。此目录沿用子工单的已有目录，应按产物时间识别，不将所有旧图都称为本次新产物。真实服务测试及截图没有在本次接续中重复运行。

原始日志、截图和失败快照留在忽略目录供本机复查；本报告保存可审阅的结论和失败摘要，不提交数据库、凭据或用户额外文件。

## 未验证项与交付边界

未验证实体手机系统软键盘、真实天气供应商、生产数据 / 生产环境、Docker 或候选镜像、代理与线上 HTTPS、服务器操作、负载及异机恢复。本次没有重新导入或替换数据库，也没有远程发布、推送、创建 PR、评论或关闭 Issue。#222 仍由后续独立授权决定远程交付。

本次只在当前 `main` 分支提交本验收报告；用户额外的 `docs/design/`、`docs/specs/`、`frontend/.playwright-cli/`、`frontend/output/` 保留，不进入提交。

本地完整复查通过，可作为当前版本的本地验收结果；首轮失败原因未确认，以及上述未验证项继续保留，不据此宣称生产验收或所有历史失败已修复。
