# SQLite 最终修复发布前证据

日期：2026-07-19

分支：`codex/sqlite-runtime-simplification`

已测试提交：`43db29b`（包含 #7–#11 的当前分支实现与回归覆盖）

## 静态检查

工作目录：`backend`

```powershell
.\.venv\Scripts\python.exe -m ruff check app tests
```

结果：退出码 0，`All checks passed!`。

## 后端全量测试与 SQLite ResourceWarning

工作目录：`backend`

```powershell
.\.venv\Scripts\python.exe -m pytest -W error::ResourceWarning -q
```

结果：退出码 0，`302 passed`，耗时 88.47 秒。将 `ResourceWarning` 升级为错误后仍通过，因此本次运行没有 SQLite `ResourceWarning`。

唯一警告来自安装环境中的 `fastapi/testclient.py`：Starlette 提示其 `httpx` 兼容入口未来将改用 `httpx2`。该警告不是 SQLite 资源泄漏，也不由本分支源码产生。

## 历史 Excel 导出

工作目录：`backend`

```powershell
.\.venv\Scripts\python.exe -m pytest tests/api/test_database.py -q
```

结果：退出码 0，`6 passed`，耗时 3.18 秒。其中 `test_export_uses_saved_income_item_snapshots_after_current_category_changes` 使用 `openpyxl` 验证当前分类改名、排序和计入总额标志变化后，导出仍使用历史 `DailyIncomeItem` 快照。

## 已删除子系统扫描

工作目录：仓库根目录。

```powershell
rg -n -i "mysql|audit(_|\s|-)?log|rollback|config(uration)?[_ -]?version|token[_ -]?state|refresh[_ -]?token" backend/app
```

结果：只命中 `backend/app/core/database.py` 中两个 `session.rollback()`。它们分别用于结束旧读事务以及短写事务异常回滚，是当前 SQLite 事务协议的一部分；没有 MySQL、审计历史/回退端点、配置版本或令牌状态实现。

## 前端门禁范围

```powershell
git diff --name-only e526ca3^..HEAD -- frontend
```

结果：无输出。本轮 SQLite 最终审查修复没有改变前端 JSON 契约或页面代码，因此未因 Excel 二进制布局变化重复运行无关前端门禁。

## 管理员与交错行为证据

- 收入配置与撤权：`19 passed`，覆盖配置替换、分类生命周期、共享写锁以及 actor 停用/降权后的 401/403 和数据不变。
- 管理员当前态：`79 passed`，覆盖 owner/最后活动管理员保护、输入验证、用户/门店引用保护、门店归档、成员替换原子性，以及用户、门店和成员写入等待期间的重新授权。
- 记账与 SQLite 聚焦套件：`32 passed`，覆盖天气阶段无事务、actor/成员/门店撤权、配置切换和历史记录快照保持。

上述测试均通过公共 FastAPI HTTP 接口验证状态码和业务结果；数据库复查只用于确认被拒绝写入的原子性与历史数据不变。

## 明确保留的后续发布条件

本证据不声称以下条件已完成：

- Docker-enabled CI；
- 生产环境烟测；
- 生产或等价负载下的内存快照。

这些项目仍是后续发布条件，需要具备相应 Docker/生产环境后单独执行和记录。
