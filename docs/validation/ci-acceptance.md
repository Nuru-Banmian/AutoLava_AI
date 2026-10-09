# PR CI 业务验收重写

## 目标与约束

根据用户要求重新设计默认 PR CI，提供短、稳定且观察核心业务结果的验收。新测试独立编写，不能用旧测试筛选、分片代替；保留旧文件作为历史回归材料，移除默认全量 pytest/Vitest/Playwright 和全局 85% 覆盖率门槛。保留锁定依赖、现有 action 版本、lint、迁移、OpenAPI/生成类型和生产构建。失败、取消、跳过、缺失结果均不能让 gate 通过。不得调用付费模型、操作生产数据或增加定时自动化。

## 新默认流程

| 必需任务 | 实际检查 |
| --- | --- |
| `api-contract` | 模块方式导出 OpenAPI 并 check；串行生成前端类型后检查 Git diff |
| `backend-acceptance` | Ruff、空库升级至 Alembic head、独立 HTTP/SSE 业务验收和 gate 结果反向验证 |
| `browser-acceptance` | 应用生产构建、验收代码类型检查、真实 API + 生产产物预览上的 Chromium 桌面/390px 窄屏验收 |
| `ci-gate` | always 执行，精确要求上述三个任务全部 success，其他状态/缺失/无效结果退出 1 |

每个任务有时间上限；不重试失败用例，不复用已有 API/Web 服务，不设置 paths 过滤跳过业务验收。Python 套件拒绝 skip/xfail/xpass 和服务端 ERROR/Traceback；Playwright reporter 拒绝 skip、expected failure、无用例、非通过状态和服务端 ERROR/Traceback。保留失败时 JUnit/server log、HTML report、截图和 trace。发布镜像及发布验收工作流未改动。

## 数据与服务边界

`backend/acceptance/server.py` 启动真实 Uvicorn 和应用 lifespan。启动前清除继承的 AUTOLAVA 环境配置并禁用 `.env`，在独立临时目录创建 SQLite，通过完整 Alembic 历史升级，不使用 `create_all` 或旧测试夹具。仅用正式初始化函数创建最终管理员；门店、普通用户、其他管理员、收入配置、每日台账和开票记录全部经公开 HTTP 创建。

外部模型由脚本协议替身提供调用参数，天气替身返回不可用；实际权限、工具注册、数据目录/查询、Decimal 计算、图表投影、SSE、事务和保存恢复均使用生产实现。替身只回显真实工具回执，不生成查询值或复写计算算法。数据库、聊天模型、记忆模型、embedding/vector、生产维护配置不继承真实凭据。浏览器验收使用独立用户和页面上的门店选择，避免管理员默认门店受其他测试数据影响。

## 覆盖行为

| 场景 | 从公开接口/页面观察的业务结果 |
| --- | --- |
| 登录与权限 | 未登录和错误密码拒绝；普通用户仅见授权门店，不能读其他门店金额、访问管理员/AI 功能；成员资格变更撤销旧会话，停用后拒绝访问，失败写入不改变金额 |
| 并发记账 | 两个真实 HTTP 客户端携带相同版本竞争写入，只有一个成功；另一方 409，回读金额与获胜版本一致 |
| 身份与配置版本 | 删除后重建产生新身份，旧版本不能覆盖；缺失预期版本 428，收入配置变更后的旧草稿 409；历史总额记账不改成分类记账，新记录只累加计入营业额的分类，其他数据保留而不计入总额 |
| 未统计/真实零/未录入 | 未统计为 null，真实零为 0，未录入计入缺失覆盖；经营日与日均收入分母正确；浏览器保存零、刷新回读、确认转未统计后金额清空且事件保留 |
| 公司结算 | 跨门店公司不能开票；待到账不计收入；确认后计入开票月份及重叠的局部区间，不能改已确认金额/用旧修订号确认；关闭后仍保留历史确认金额；撤销后扣除 |
| Agent 查询与计算 | 真正执行技能/目录/查询/计算/图表工具；工具回执为成功；0.1+0.2 返回精确 0.3；当前门店图值为未知、0、81、未知，另一个门店的 999 不泄漏 |
| SSE 与历史图 | 活跃运行流式读取，终态完成；cursor 重放仅返回剩余事件；重新登录回读历史消息/图表，后续台账修改不改历史快照；桌面/窄屏滚动触发懒加载并点选准确值 |
| reset 与失败 | 管理员之间/门店之间不共享消息或图；reset 只清空目标范围且拒绝旧 generation；模型失败产生 failed 而无助手成功消息；模型等待期间 reset 取消运行、不发布已准备图表；相同 request_id 重试复用运行 |
| CI gate | 各必需 lane 逐一注入 failure/cancelled/skipped/timed_out 均失败；全 success 才通过，缺失/错误 JSON 失败；skip/expected failure/ERROR 反向探针实际退出 1 |

## 本地证据（2026-10-09）

- 首轮全新 HTTP 场景：5 failed / 16.78s，测试准备错误地把未录入当成 200；改为公开 404 + form-config 流程。后续校准了隐藏门店 404、成员变更撤销会话 401，以及历史总额记账保留原方式的契约。
- 初轮浏览器：4 passed / 2 failed / 约 1.4m，等待尚未进入可见区的 figure 超时；改为滚动已有图表容器来触发真实懒加载。之后 5 passed / 1 failed / 40.2s，暴露管理员默认选了其他验收门店；改为页面上明确选择本场景门店。
- 在上述修正后：HTTP/gate 17 passed / 19.05s；浏览器 6 passed / 33.4s，但观察到服务端 SSE 断连清理异常，未把此运行当最终通过证据。
- 增加服务端错误拒绝后，桌面 AI 单用例断言 passed / 14.8s，但进程 exit 1，捕获 SQLAlchemy `Exception terminating connection` / `no active connection`。终态事件后再次读取数据库，恰逢浏览器关闭 EventSource。修复为发出 completed/failed 后直接结束流；保留非终态分页及 cursor 重放。修复后同一用例 1 passed / 15.4s、exit 0，无该异常；新 HTTP/gate 17 passed / 18.55s。
- 进一步检查 HTTP server log，主动断开非终态 SSE 后 reset 的用例仍有同样清理异常；增加日志断言后该定向用例出现 teardown ERROR。对 SSE 的短数据库读取/会话清理使用现有 AnyIO cancellation shield，防止断连取消打断 SQLAlchemy 的 rollback/close；不屏蔽后续流取消、外部模型或整轮运行。修复后该用例 1 passed / 7.40s，无服务端异常。
- 生产构建在带空格的 Windows 工作区初次失败；Vite alias 从 URL pathname 改用 `fileURLToPath` 后构建通过（含 TypeScript）。OpenAPI check、生成类型零 diff、Ruff 通过。
- 临时反向探针：pytest skip（显示 1 skipped）仍 exit 1；Playwright skip、expected failure（runner 显示 passed）及模拟服务端 ERROR 分别 exit 1。探针文件已移除，正常套件不包含故意失败/跳过用例。
- 完整新套件（包含服务端日志拒绝）：HTTP/gate 17 passed / 18.75s，桌面/窄屏 6 passed / 34.6s，无服务端 ERROR/Traceback。
- 两轴复核：Standards 未发现问题；Spec 指出 reset 对照同时改变管理员和门店，不能分别证明单维隔离。已改为两个非空对照：当前管理员的其他门店、当前门店的其他管理员；reset 后均回读 conversation/generation 和图表快照，保持不变。随后定向重跑该场景。

GitHub Actions 耗时在 PR/交付记录中补充。以上秒数为本机单次实测，非性能 SLA；GitHub 总耗时还包含依赖安装、浏览器安装、构建和 runner 排队。

## 运行方式

```sh
# backend，独立于 tests/ 下的旧夹具
uv sync --locked --extra dev
uv run --frozen pytest acceptance -q --durations=10

# frontend；后端 uv 必须可用，或设置 ACCEPTANCE_PYTHON 为 Python 可执行路径
npm ci
npm run build
npm exec playwright install -- --with-deps chromium
npm run test:acceptance
```

## 未覆盖范围

少量验收不等于旧全量覆盖。默认 PR CI 未覆盖真实 LLM/Bailian 答案质量、记忆整理/vector 全协议、真实天气供应商、所有查询筛选/分页/图型边界、浏览器全品种、全部管理员表单、导出、完整备份恢复、旧生产数据的迁移兼容、HTTPS/Nginx/容器发布及压力负载。这里的恢复指新登录/刷新回读数据库持久状态，未验证服务进程重启恢复；迁移检查是空库升级到 head。上述范围由专项回归/保留的历史测试/发布验收另行验证。不会声称新套件达到 85% 覆盖率。
