# Agent 2 GB 发布评估

## 当前结论

2026-07-29 的结论是 **不批准发布**。当前开发环境没有目标 Docker
运行环境，也没有安全注入的候选生产模型配置或 Secret，因此不能完成 2 GB
资源测量和真实 Adapter 验证。`AUTOLAVA_AGENT_RELEASE_REPORT_PATH` 必须保持为空，
生产环境中的 Agent 即使数据库开关曾经为开启，也会保持全局关闭。

这不是安全门禁失败后的人工豁免。只有下面的同一套测试在目标生产形态通过，并生成
与实际运行模型配置完全匹配的脱敏 JSON 报告后，最终管理员才能使用全局开关。

## 固定测试流程

- 单个 2 GB 应用容器、一个应用进程、一个应用 worker 和 SQLite，不把 API、Agent
  或模型调用拆成多个容器或进程来制造资源余量。
- 按家庭内部每天仅使用一两次的实际负载，不执行并发压力测试。每个样本只允许一个
  Agent 请求，并记录 `agent_request_concurrency: 1`；为验证短写不受阻塞，在该请求的
  取证阶段仅重叠一个普通短写事务。
- 串行重复 20 次日常流程：登录、读取门店、读取每日台账/经营分析、提交一次短写事务，
  然后发起一个 Agent 经营查询。除上述单次短写重叠外，不增加并行用户或 Agent 请求。
- 使用脱敏的代表性 SQLite 副本；问题只使用固定中文评估问法，不记录原始经营内容。
- 候选主模型和备用模型使用部署 Secret 注入。报告只记录供应商代号、模型 ID、
  聚合 Token/费用和失败类别，不记录密钥、提示词、回答或经营证据。
- 同一发布候选必须通过 `backend/tests/release/agent_release_cases.json` 中登记的十个
  高层 HTTP 场景，以及 1440×1000 桌面和 390×844 移动端 Playwright 场景；这套
  Fake-only 自动化验收不能替代真实 Adapter 与目标环境测量。

## 可复现步骤

1. 使用候选生产镜像启动一个限制为 2 GB、一个应用进程、一个应用 worker、SQLite
   的应用容器；保持
   `AUTOLAVA_AGENT_RELEASE_REPORT_PATH` 为空并确认管理员页面显示门禁未通过。
2. 配置主备供应商、模型、结构化输出方式、`30` 秒超时、`2000` 输出 Token
   以及调查的模型调用、工具调用、总 Token、费用和有限重试上限。业务代码不包含
   供应商、模型或固定调查顺序的硬编码。
3. 固定候选镜像并记录不可变摘要，然后导出逐样本 JSON Schema：

   ```sh
   docker image inspect --format '{{index .RepoDigests 0}}' autolava:candidate
   python -m app.scripts.evaluate_agent_release --sample-schema \
     > /data/release-evidence/agent-release-sample.schema.json
   ```

4. 先预热，再串行执行 20 个样本。每个空闲、普通业务和 Agent 阶段开始前启动连续
   `docker stats --format '{{json .}}' <container>` 采集，阶段结束后停止采集器；按
   `MemUsage` 每秒样本取该阶段最大值，不能用 `--no-stream` 单点值冒充峰值。用单调
   时钟记录完整请求、SQLite 快照和短写耗时；从
   Agent run statistics 记录模型阶段次数、工具调用次数、Agent 请求并发数、输入/输出
   Token、总 Token 与估算费用。先在无 Agent 时测一个短写基线，再启动一个 Agent
   请求，并只在其取证阶段重叠一个同样的短写。每轮写入一行脱敏 `samples.jsonl`；
   其中 `model_stage_count`、`tool_call_count`、`agent_request_concurrency`、
   `input_tokens`、`output_tokens`、`total_tokens` 和 `estimated_cost_eur` 必须来自
   实际运行统计，且总 Token 必须等于输入与输出之和。字段必须通过上一步 Schema；不得记录问题、回答、
   证据、账号或 Secret。

5. 对每个候选真实供应商配置运行
   `docs/release/native-model-adapter-probe.md` 中的可丢弃探针，验证原生工具调用、
   同轮并行工具调用、带原调用 ID 的工具结果续接、自然结束回答，以及 Token、延迟和
   费用计量。再使用同一文档的 `--expect-error` 模式，让候选真实 Adapter 分别观察并
   映射超时、限流、5xx、鉴权、余额和无效输出；不得用 Fake 结果替代。把成功路径的
   五项、真实错误映射的六项、结构化输出、#74 安全门禁和两项脱敏结果合并为恰好
   15 项的 `adapter-cases.json`；任何一项缺失或失败都不批准发布。同时记录
   `transaction-trace.jsonl`：每个样本一行，保存取证阶段、每个模型调用、每个 SQLite
   快照和每次进程短写锁的单调开始/结束毫秒。模型调用区间数量必须等于该样本的模型
   阶段次数，且不得与任何快照或写锁区间重叠；至少一个短写锁区间必须与取证阶段重叠。
   对固定中文评估问法逐项检查语言是否自然、结论是否清楚、限制说明是否完整、是否
   泄露技术 JSON；20 个样本必须全部通过，语言质量通过率为 100%。

6. 将 `samples.jsonl`、`adapter-cases.json` 和 `transaction-trace.jsonl` 与最终报告
   放在同一目录。由仓库脚本按固定的 nearest-rank 方法计算 p95，并对三份原始脱敏
   证据生成摘要：

   ```sh
   python -m app.scripts.evaluate_agent_release \
     --summarize-samples /data/release-evidence/samples.jsonl \
     > /data/release-evidence/measurement-summary.json
   sha256sum /data/release-evidence/adapter-cases.json
   sha256sum /data/release-evidence/transaction-trace.jsonl
   ```

   报告必须使用 schema v2，保存一个容器、一个应用进程、一个应用 worker、SQLite
   的目标拓扑，保存候选镜像摘要、采集时间、`agent-release-v2` collector 版本和上述
   三个 SHA-256。运行时
   门禁会重新读取三份文件、核对散列、重算 measurements、从 Adapter cases 和事务
   轨迹重建 checks，并拒绝缺失文件、重复/缺失用例、样本序号不连续或任何不一致。

7. 用下列命令导出不含 Secret 或经营内容字段的报告 JSON Schema，并生成当前主备端点、
   结构化输出方式、thinking 参数、价格、超时、Token 和批量配置的 SHA-256 指纹。
   把聚合值和指纹写入对应字段，然后在目标容器中执行判定：

   ```sh
   python -m app.scripts.evaluate_agent_release --schema > /tmp/agent-release.schema.json
   python -m app.scripts.evaluate_agent_release --fingerprint
   python -m app.scripts.evaluate_agent_release --report /data/agent-release-report.json
   ```

8. 部署候选镜像时，把步骤 3 的不可变 `sha256:...` 摘要注入
   `AUTOLAVA_AGENT_RUNTIME_IMAGE_DIGEST`。命令退出码为 `0` 且输出 `approved: true`
   后，才把 `AUTOLAVA_AGENT_RELEASE_REPORT_PATH` 设置为该报告路径并重启。报告中的供应商、
   模型、主备 Adapter 完整非密钥配置、超时、Token 和批量上限必须与运行配置一致。
   运行镜像摘要也必须与报告一致；发布新镜像必须重新评估，不能复用旧报告。
   重启后 Agent 仍保持关闭；最终管理员必须在管理中心对这个已批准报告重新执行一次
   “启用”。报告内容或运行配置变化会使该启用绑定失效，必须重新评估并再次显式启用。

## 发布阈值

- 2 GB 限额下峰值内存至少保留 256 MB。
- 至少有 20 个串行日常样本，每个样本的 Agent 请求并发数必须为 1；不要求并发或
  压力测试。
- 固定中文评估问法的语言质量通过率必须为 100%。
- Agent 请求 p95 不超过 15 秒。
- 单次请求估算模型费用不超过 0.05 欧元。
- SQLite 只读快照 p95 不超过 500 ms。
- Agent 负载下普通短写 p95 不超过 200 ms，且不超过基线的 3 倍。
- 输出 Token、总 Token、模型调用数、工具调用数和估算费用均不超过相应运行配置上限。
- 十个高层 HTTP 场景、桌面和移动端响应式 Playwright 场景必须通过。
- 真实原生 Adapter 的五项探针能力、结构化输出、失败语义、事务边界、#74 安全否决
  门禁、Secret 脱敏和经营内容脱敏必须全部通过。

任一指标缺失、超过阈值、报告格式无效或运行配置与报告不一致，判定都会失败并保持
生产 Agent 全局关闭。
