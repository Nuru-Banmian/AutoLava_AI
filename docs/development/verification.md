# 开发验证

仓库根目录的四个 `npm run verify:*` 命令是本地与 CI 共用的权威验证入口。
命令先从已提交的锁文件同步工具，强制使用 Fake 模型，并移除当前进程中的模型
API key 后再运行检查。任何子检查失败都会保留非零退出码。

| 变更 | 提交前最低层级 | 内容 |
| --- | --- | --- |
| 文档、开发脚本、小型合同 | `npm run verify:quick` | Python 格式、lint、作用域内 mypy 与关键合同 |
| Agent 运行时、经营工具、证据计算、Agent 前端 | `npm run verify:agent` | Agent HTTP/领域测试、前端 Agent 流程与发布清单 |
| 普通产品代码或跨模块变更 | `npm run verify:full` | 全部确定性后端、前端单元、构建与端到端测试 |
| Agent 发布候选 | `npm run verify:release` | 发布一票否决清单与高价值端到端场景 |

`quick` 的 Python 格式与 mypy 范围从 Agent 运行时和 HTTP seam 开始。首次全仓
机械格式化以及既有 mypy 基线应使用独立提交逐步收紧，不能与 Agent 行为修改混合。
前端 Biome 同样先覆盖 Agent seam；新增 Agent 文件必须加入 `frontend/biome.json`
的受检范围。

CI 将后端静态检查、Agent 后端、非 Agent 后端、前端单元与构建、前端端到端拆为
并行 lane。`CI summary` 是名称稳定的汇总检查：它要求全部 lane 成功，合并覆盖率
分片并执行 85% 总覆盖率门禁。Agent 发布一票否决集合在同一次 CI 中只运行一次。

CI 不配置真实模型 key，不调用付费供应商。Playwright 失败产物只允许包含测试桩
生成的脱敏数据；不得把问题正文、Agent 回答、经营事实、原始工具 payload、SQL、
密钥或直接个人联系与支付标识写入上传目录。

性能基线使用 GitHub Actions 最近十次成功的 `CI summary` 运行统计 p95。每个 job
及步骤的 Actions 时间是 lane 诊断来源；目标是常规 PR p95 不超过 120 秒、静态
错误通常在 30 秒内出现。本地可用 PowerShell `Measure-Command {
npm run verify:quick }` 和 `Measure-Command { npm run verify:agent }` 记录同一台
开发机热缓存耗时，目标分别为 15 秒与 30 秒。
