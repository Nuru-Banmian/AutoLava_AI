# Issue #239：门店描述编辑与冲突保护

验收日期：2026-10-05。范围：[Issue #239](https://github.com/Nuru-Banmian/AutoLava_AI/issues/239)，父规格 #238 中的门店资料维护部分。

## 交付行为

- 沿用门店创建和编辑表单，增加多行纯文本描述、字符计数、清空按钮及多行业提示。未保存的描述参与现有门店、页面和退出登录草稿保护。
- `StoreCreate.description` 默认空字符串；`StorePatch` 省略描述时保留原值，显式 `null` 返回 422，空字符串或仅空白保存为空描述。非空描述保留首尾空白和换行。前后端按 Unicode 字符计数，上限 3,000；超限空白也拒绝。
- 描述写入必须携带正整数 `expected_description_revision`。创建时版本为 1，每次描述写入递增；其他资料、收入配置操作不递增描述版本。描述写入也不修改收入配置版本。
- SQLite 短事务先获取写锁并重新验证登录身份和 `stores.manage`，再比较描述版本和提交。普通用户无论是否属于该门店均不能创建或写入描述；管理员沿用全门店资料管理权限。
- 409 的 `detail.code` 为 `store_description_revision_conflict`，`detail.latest` 返回最新描述及版本。冲突不部分提交其他资料。界面保留草稿，显示最新描述，并要求选择“已核对，保留草稿”或“采用最新描述”后再保存。
- 迁移 0022 只增加描述及独立版本列，旧门店默认空描述和版本 1，已有每日台账保留。

## 可重跑验证

在后端执行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/api/test_store_description.py tests/api/test_store_description_migration.py tests/api/test_admin_revocation.py -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe scripts/export_openapi.py --check
.\.venv\Scripts\python.exe -m pytest -n 4 --dist loadscope --cov=app --cov-report= -q
.\.venv\Scripts\python.exe -m coverage report --fail-under=85
```

在前端执行 `npm test`、`npm run build`、`npm run test:e2e`。真实服务浏览器验收从仓库根目录执行：

```powershell
.\backend\.venv\Scripts\python.exe scripts/verify-issue-239-live.py
```

该脚本创建临时 SQLite，执行真实 Alembic 迁移并创建一次性管理员，启动真实 HTTP 后端和 Vite；退出后关闭其服务并清理临时数据库，不访问开发数据库。浏览器用例单独通过 `AUTOLAVA_DESCRIPTION_LIVE` 启用，普通模拟接口套件不会将跳过的真实服务用例报告为通过。

## 证据与边界

| 验证类别 | 结果与范围 |
| --- | --- |
| 公开 HTTP / 真实临时 SQLite | 创建、列表回读、保存、清空、空白、3000 字符及 emoji、超限、null、省略字段、缺失/非法版本、普通用户跨门店写入拒绝、权限撤销后写入拒绝 |
| 真实迁移 / 重启 / 并发 | 从 0021 升级，旧门店空描述、台账金额 940 保留；重建引擎和应用后描述回读；两份相同版本的并发 HTTP 保存仅一份成功，另一份 409 返回已保存的新版本 |
| 前端表单 | 描述冲突保留草稿、明确核对新版本、现有切换和迟到响应测试；退出登录前可继续编辑或明确放弃 |
| 真实浏览器 / 真实后端 | 3 个用例通过：390px、1280px 创建/编辑/清空/冲突/切店保护，以及账号切换草稿保护与迟到响应隔离。页面无水平溢出；截图已检查 |
| 故障注入 | 保存失败通过浏览器拦截注入 503；正常保存、版本冲突和列表回读使用真实后端及数据库 |
| 模型替身 / 真实向量存储 / 真实百炼调用 | 本任务不涉及，未执行；保存描述没有新增模型或向量服务调用 |
| 内容审阅 | 已检查多行业提示及界面截图；AI 回答行业适配未执行，由后续 Agent 接入任务验收 |
| 部署验证 | 未执行容器、生产部署或远程发布 |

本地浏览器报告和截图位于 `.autolava-test/issue-239/`，全量检查日志位于 `.autolava-test/issue-239-*-full.log`，不提交一次性数据库或凭证。验收使用当前工作区，工作区同时存在用户已有的品牌/说明文档等未提交修改；本提交仅包含 #239 的改动。

## 失败记录

- 后端首个红灯：创建响应缺少 `description`；实现后通过。
- 前端首个红灯：现有表单缺少“门店描述”输入；实现后通过。
- 新增描述用例最初匹配到两个“保存”按钮，已限定到门店资料区域；类型检查发现创建请求类型需排除默认描述字段，已修正。
- 旧成功响应不刷新列表的回归由现有测试捕获；恢复同账号列表刷新，同时保留新门店草稿，账号变化后不刷新旧请求。
- 长文本参数自动测试名称超出 Windows 环境变量长度限制，改为短参数标识。
- 旧库测试准备遗漏台账必填 identity，且列表排序使重启后的首行并非原门店，均修正为有效旧库数据并按门店 ID 核对。
- 首次真实浏览器账号切换用例因整页导航与拦截释放产生 `Route is already handled`；保留 `failed-run-1/playwright-results.json` 和失败 trace，改用应用内导航及确定性释放屏障后 3 个用例全部通过。
