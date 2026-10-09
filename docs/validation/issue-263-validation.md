# Issue #263 验收记录

日期：2026-10-09（Asia/Shanghai）。以下失败演进及阶段结果按发生顺序保留；最终交付收据见文末。

- 权威工单：https://github.com/Nuru-Banmian/AutoLava_AI/issues/263；父规格#260。
- 永久审查基线：ab3ac9708f1bc8f500ea8dbe15c4e5a09636a9c9，含#261/#262及#271。
- 工作区：C:/Users/1/.codex/worktrees/issue-263-store-query/AutoLava-AI；分支codex/issue-263-store-query。
- 原D盘目录的既有改动、业务数据库与.env未触碰；没有生产部署或付费供应商调用。
- 验收边界：已认证HTTP/SSE、向前迁移到0029的临时SQLite、受控模型驱动真实工具；桌面/窄屏浏览器。

## 已执行及失败演进

1. 红用例：公开聊天“全部历史最高五天及完整事件”最初失败（旧计划不接受query路由），实现后通过。
2. 首批4项通过：完整事件/稳定排名、跨轮目录复用但重读历史边界、开关失效整批拒绝、字面关键词/空值/部分目标失败。
3. 新查询扩展首轮6通过/1失败：测试误用分类配置categories，现有接口使用items，修正参数。
4. 新查询25项运行24通过/1失败：依赖观测误将stores.company_settlement_enabled字段识别为结算表；改为FROM/JOIN company_域检测，隔离复验通过。
5. 旧Agent回归101项首轮100通过/1失败：工具清单断言仍期待store_overview。同步目录/查询后隔离复验通过。
6. 一次从根目录直接运行测试/契约脚本误读取共享d688环境的旧可编辑源码，2项失败及OpenAPI旧契约漂移；保留失败，不作功能结论。测试固定backend cwd，导出显式PYTHONPATH指向当前backend后通过，OpenAPI无差异，生成前端类型亦无差异。
7. 前端完整385项/37文件通过；类型检查与构建通过。jsdom scrollTo未实现警告保留，非真实浏览器证据。
8. 当时Windows完整后端仍在运行，不能记通过。历史日志在系统临时目录issue263-full-backend.log；最终结果见文末。
9. 浏览器临时服务使用向前迁移独立SQLite与受控模型；曾因Vite重载发生过期引用，重新snapshot继续，非功能通过。登录前401及favicon404保留。

## 交付范围

本票仅上线台账与历史分类完整明细目录/查询。#264指标/分组/比较/月度收入、#265分页及#266–#268图表未实施，目录不公布未上线能力。
参数失败按目标保留成功结果；配置失效整批不查询；授权失效仍走原整轮守卫。
每次结果预算预留2000字回答及1000字控制空间；完整批量12,000字符硬上限、200行上线前容量限制，不截断事件。

受控模型、浏览器与完整回归分别记录；真实供应商、Docker、生产、负载未验证。


## 审查与最终验收进展

- 初审：Standards 0硬性违规/1项P3字段元数据维护建议；Spec 3项（失败查询成为依据、默认规划可进入旧概览、硬容量误报上下文不足）。
- 三个公开红用例全部复现；修复后3项通过：失败/非法/目录失效不能成为业务正文依据，默认规划只公开general/clarify/query与空queries，硬容量和累计上下文容量分别报告。
- 仅旧已发布计划仍可由解析器识别business；主模型规划schema及提示不再推荐此路径，旧概览不在主模型工具schema。
- 完整后端首轮718通过/1失败/10警告，350.50秒：test_history_pagination_input_scope_and_context_budget在8000字符预算失败。新增空data_catalog字段挤占临界预算；无缓存时省略该字段，隔离复验通过，不提高预算门槛。
- 修改后查询27项通过；追加目录刷新重试、批量非法参数与更多日历边界用例，当时仍待最终全套。
- 桌面及390x844浏览器：真实登录与选择门店甲、首次目录提示、一次最高五天查询、第二轮不发现目录且仅1次查询（对公开run/events断言），完整事件起止与金额/排序显示，刷新恢复原答。
- 初始浏览器fixture事件为空，后通过临时服务HTTP补充完整事件后重查；前一回答保留原空值，第二回答显示完整事件，未冒称真实经营/供应商质量验证。
- 浏览器截图：frontend/output/playwright/issue263/desktop-full-events.png、mobile-full-events.png。独立验收源与日志位于OS临时目录；不提交运行输出、浏览器缓存或临时数据库。
- 本票成功浏览器路径前端未在审查后再变更；后端审查修复均在公开HTTP/SSE测试覆盖。当时最终完整回归与两轴复核仍待收据，最终结果见文末。

- 容量补充：预留全部目标失败回执后才读取业务，12,000上下文预算/六个64字id公开聊天用例通过（整批context_capacity，无目标SQL、无伪造999正文）。此补充当时要求最终审查及完整套件再核对。

- 后续完整回归735通过/8个SQLite ResourceWarning，372.09秒；此结果在最后容量预留补充之前，不当作最终HEAD收据。
- 补充Spec复核发现id控制字符JSON转义会增大失败回执。已按实际serialized_size预留，两种id公开低预算用例均通过。
- 736项运行启动后发现该静态缺口，已停止本票自有测试进程，保留issue263-complete-final.log中29%阶段记录；中止不是通过。当时计划冻结后跑737项，后续补充回归使实际数量成为738项。
- 自有浏览器session已关闭，8130/4183服务经PID/命令归属核对后停止；业务SQLite及原.env未触碰。

- 后续目标也逐个预留JSON转义后的id及完整失败回执。已提取统一failure_receipt_capacity同时用于初始检查和逐目标分配；大首目标+四个转义id失败项+末尾成功目标的公开聊天用例通过，整批<=12,000字符且末尾成功保留。相关容量/日期4项复验通过。该阶段完整套件为738项。

## 交接后最终复核与容量修复

- 已核实交接指定日志 `C:/Users/1/AppData/Local/Temp/issue263-frozen-final.log` 完成摘要：738 passed、11 warnings、382.21秒。对应冻结源码为 `8ee8e3f5fa4c46e002514c794f1d498e3f77aab5`；原session_id无法续接，依据完整日志及对应pytest进程退出确认，未声称取得原执行退出码。
- 该738项覆盖率检查 `python -m coverage report --fail-under=85` 退出码0，TOTAL为5939条语句/693未覆盖，88%；查询日期89%、目录100%、查询85%。收据 `C:/Users/1/AppData/Local/Temp/issue263-frozen-coverage.log`。此结果仅对应修复前源码。
- 最终Spec复核新增1项P2：合法事件经两层JSON转义后占用大于工具正文容量。默认24,000字符预算下，公开台账接口写入三天、每天1700个反斜线，公开聊天完整事件查询先发布工具completed，随后整轮context_budget。复现日志 `C:/Users/1/AppData/Local/Temp/issue263-spec-outer-json-probe.log` 保留。
- 新增公开HTTP/SSE回归先红：`issue263-outer-json-red.log` 为1 failed/44 deselected，5.35秒；不删改该失败记录。修复分别检查12,000字符工具正文上限与嵌套消息实际占用，并按同样口径预留后续失败回执；不截断事件、不提高预算。该目标明确context_capacity，同批小目标保留，整轮可完成并发布partial提示。
- 修复后容量相关4项通过/41 deselected，16.54秒，日志 `C:/Users/1/AppData/Local/Temp/issue263-outer-json-green.log`；Ruff全后端、OpenAPI --check、git diff --check通过。OpenAPI及生成前端类型无变更。
- 首次消息容量修复提交：`349d51c8871690368c11e7c5ead969a32a0bb5e8`；该739项全套为738 passed/1 failed/11 warnings，351.45秒，退出码1，日志 `C:/Users/1/AppData/Local/Temp/issue263-outer-json-final.log`。失败是普通长事件同时超限时先报context_capacity，旧回归要求正文超量的result_capacity_exceeded；未当作通过。
- 错误分类定向复现1 failed/44 deselected，7.45秒，收据 `C:/Users/1/AppData/Local/Temp/issue263-capacity-priority-probe.log`。仅调整检查顺序：先检查正文容量，再检查嵌套消息占用；正文可容纳但转义后超限仍为context_capacity。原长事件、新转义事件及整批/逐目标失败回执的5项公开回归通过/40 deselected，19.26秒，收据 `C:/Users/1/AppData/Local/Temp/issue263-capacity-priority-green.log`。
- 最终源码冻结提交：`d800b1701256d316ce42188ed1b21ae9c7d7c377`；最终739项全套结果见下方交付收据。
- 两个独立子代理按永久基线复核累计源码及容量修复：Standards 0硬性违规/0新增需处理smell；Spec新增P2已解决，0未解决问题。初审P3紧凑字段元数据维护建议仍作为已接受取舍保留。最终收据文档已完成两轴复核。

## 最终本地交付收据

- 冻结源码 `d800b1701256d316ce42188ed1b21ae9c7d7c377` 下，backend cwd使用共享d688环境的Python运行 `python -m pytest -n 4 --dist loadscope --cov=app --cov-report= --durations=10`：**739 passed、11 warnings、349.38秒，退出码0**。最终日志 `C:/Users/1/AppData/Local/Temp/issue263-priority-frozen-final.log`。正文硬容量错误优先检查已纳入该全套；之后仅更新本文档。
- 警告为SQLite连接未关闭的ResourceWarning，日志含运行收尾额外打印；保留原始日志，不将警告称为已修复。
- 同一覆盖率数据执行 `python -m coverage report --fail-under=85`：**TOTAL 5951条语句、680未覆盖、89%，退出码0**。日期模块89%、目录100%、查询模块84%；85%为总覆盖率门槛，不宣称每个模块均达85%。日志 `C:/Users/1/AppData/Local/Temp/issue263-priority-frozen-coverage.log`。
- 最新源码的Ruff全后端与git diff --check通过；消息容量修复后的OpenAPI --check通过，本票无HTTP模型变化，OpenAPI和生成前端类型无变化。前端385项/37文件、类型检查、构建沿用已完成收据，后续未修改前端；不为文档收尾重复全套。
- 受控模型：公开已认证HTTP/SSE、迁移到0029的临时SQLite证明目录复用/失效、投影与历史分类、日历边界、完整事件、错误分类、失败目标及容量回执；不等同于真实供应商内容质量。
- 浏览器：沿用交接前实际桌面1280x900与窄屏390x844证据，已确认最高五天完整事件、第二轮目录复用/一次查询、刷新恢复。此次容量修复仅补公开HTTP/SSE回归，未重跑浏览器；截图保留为未跟踪输出，不提交。
- 未验证：真实供应商、Docker、生产、负载；#264汇总/分组/比较/月度收入、#265分页及后续图表均不作为#263已交付能力。
- 清理与范围：最终pytest进程已退出；核查未发现本票残留Python/Node服务，8130/4183未监听。临时数据库保留作证据，不宣称Windows锁文件清理成功。原D盘工作区、业务SQLite与.env未写入；仅精确暂存本票改动及本文档。
- 交付仅限本地分支 `codex/issue-263-store-query`；未推送、未创建或合并PR、未关闭Issue、未开始#264。
