# Issue #265 本地验收记录

日期：2026-10-09（Asia/Shanghai）。权威要求：GitHub #265 与父 #260 第2/4/7/8/18节。

- 永久审查基线：`1cf0e5e0217b7cc762348563cc0c448e3b011d01`，已包含 #263、#264。
- 工作区：`D:/work/myself/AI-try/AutoLava-AI-265`，分支 `codex/issue-265-result-pagination`。
- 用户指定本次专门新增/修改功能测试，不运行全量测试。沿用已认证 HTTP/SSE、迁移临时 SQLite、受控模型驱动真实工具和适用浏览器边界。
- 原 `D:/work/myself/AI-try/AutoLava-AI` 的脏文件、业务数据库与 `.env` 未写入。本次只提交本票文件，不推送、创建 PR、合并或关闭 Issue。
- 初建的 C 盘 managed checkout 及先前共享测试环境在执行中被外部移除；恢复同分支/同基线到 D 盘独立 git worktree，未重置原目录。新隔离 `.venv` 通过 `uv sync --locked --extra dev` 安装，锁文件不变。

## 实现与契约

每个查询目标完整物化所选字段或分组、比较结果，并使用同一短 SQLite 只读事务读取统计、计数和有稳定兜底顺序的行。随机 `result_ref` 指向按 UTF-8 字节计费的不可变 JSON 副本，每 run 合计最多4 MiB。HMAC 游标绑定 scope（管理员、门店、登录身份）、run、generation、完整查询/数据摘要及位置；续页复验权限，不重新读取业务表或检查新目录版本。

`store_query` 新查询仍使用 `catalog_version/targets`，目标增加 `page_size`（默认50、最多200）。续页使用互斥的 `continuations:[{result_ref,cursor,page_size}]`，至多6个唯一引用，不接受重新选择范围/字段。返回 `matched_count/selected_count`、`row_count`、实际范围/时间/口径、`page_range`、`read_ranges/unread_ranges`、`has_more/next_cursor/result_ref`。比较两侧按相同位置的完整行对分页，独立统计均来自全匹配，图表后续可直接读取完整快照。

单次整个批量正文不超过12000字符，另按模型请求的嵌套 JSON 转义、全部工具 schema、已有工具页和后续提示计算累计余量，保留回答2000与控制/错误1000字符。不修改已读页；只在首查询前裁掉较旧对话。容量不足返回小回执，保留引用、总量、已读/未读和续页状态；最终文本/history/SSE明确部分完成。单行硬超量返回 `row_too_large/required_chars`；完整物化或累计快照超量返回 `result_capacity_exceeded`，保留其他成功目标。

结束、失败、停止、重置或授权失效后的 worker 失败清理临时引用；进程重启不持久化这些快照，沿用已有中断处理且不自动重查/调模型。撤权先立即禁止读取/发布，清理由失败、finally或既有运行超时完成；没有宣称撤权API同步释放全部等待中的worker。

工具 schema、提示词、经营分析技能、README同步更新。未新增 HTTP 工具执行接口或 HTTP 数据模型；OpenAPI检查和生成前端类型无差异。

## 定向证据与失败记录

原始日志位于 `C:/Users/1/AppData/Local/Temp/`，保留红测试及修复前日志，不将历史结果冒称最终结果。

- `issue265-pagination-red.log`：首个公开多目标不可变分页失败（page_size/continuations尚未支持）；首轮实现后1项通过。
- `issue265-query-regression.log`：相关查询/指标55项中50通过、5失败。4项为旧“分页未上线即拒绝”及 page_size不允许的契约；1项为转义参数收到容量回执后仍触发 context_budget，已修复。
- `issue265-pagination-contract-green.log`：合同更新后6通过/1失败，暴露大目标消耗小邻居空间；修复返回空间预留后 `issue265-neighbor-green.log` 为3通过、44未选择。
- `issue265-pagination-two-green.log`：分组top_n测试误把全部历史截止当地今天的缺失日当成仅6行；改为明确6日范围后验证全匹配合计210、选中3行、两页完整排名。
- `issue265-snapshots-capacity-final.log`：分页/排名/比较及容量6项通过。包括并发修改/删除/插入不改变续页、多目标完整事件、单行控制字符超限、单及累计4 MiB、默认50/max200行。
- `autolava-265-pagination-security-20261009.log`：5通过/2测试口径错误（默认24k容量影响安全重试及把逐目标错误误当SSE直接字段）；修正后 `autolava-265-pagination-security-20261009-rerun.log` 为7通过。覆盖伪造/篡改/交换/Unicode游标、输入互斥、跨run/管理员/门店/generation、stop/reset/logout/停用后的迟到续页。
- 累计上下文、首查询前历史裁剪、最终部分说明和输出上限的最终收据见后续最终检查。
- 前端定向组件2项及 Chromium 390/1280px共2项通过；真实渲染/原生EventSource、受控API响应，刷新不重提或重开流。详见 `issue-265-browser.md`；不冒称连接了真实后端/供应商。
- 受影响 Python Ruff、OpenAPI `--check`、前端类型生成无漂移、`tsc -b` 和 diff检查通过；最终检查及两轴审查收据将在提交前补齐。

未运行后端/前端全量套件，未调用真实付费供应商，未执行Docker、生产或负载验收。
