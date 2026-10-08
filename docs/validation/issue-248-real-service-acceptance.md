# Agent T10 真实服务与内容验收（#248）

日期：2026-10-08。工单：[Issue #248](https://github.com/Nuru-Banmian/AutoLava_AI/issues/248)，父规格：[Issue #238](https://github.com/Nuru-Banmian/AutoLava_AI/issues/238)。

**状态：部分成功，内容质量仍有失败，不能声明 T10 全部完成。资源和小规模真实调用授权已齐备。**

## 基线与安全边界

- 固定审查基线 `f331fa38cfd711d523297db3ef9fa3c41713fa60`，包含 T9；初步报告提交 `e0cd797`。
- 实施工作树 `C:\Users\1\.codex\worktrees\issue-248-acceptance\AutoLava-AI`。原工作区 `D:\work\myself\AI-try\AutoLava-AI` 的无关脏文件保留，不整体暂存。
- SQLite 迁移至 0028，使用隔离合成管理员、两门店及每日台账，不写实际业务数据库。
- 密钥仅从原项目根目录被忽略的 `.env` 读取到服务端。报告、提交和日志不包含密钥、登录密码或供应商认证头。
- 仅授权本地提交；未推送、未创建/合并 PR、未评论/关闭 Issue，未做 Docker 或生产部署。
- [T9 报告](issue-247-agent-integration.md)属于历史证据；没有重跑 T9 全套或已通过的描述浏览器检查。

## 已选资源与真实预检

| 项目 | 配置及实际结果 |
| --- | --- |
| 聊天 | qwen3.6-plus；支持实际只读工具调用。早期 qwen-plus 聊天失败和模型对比保留 |
| 记忆整理 | qwen-plus；实际 propose_memory 工具提议和权威状态回读 |
| Embedding | text-embedding-v4，1024 维；实际请求返回 1024 维 |
| 地域与业务空间 | 北京 cn-beijing；沿用安全配置中用户指定的业务空间域名。报告不复制含空间标识的完整主机名，也不替换成默认空间 |
| 地址 | 该安全主机的 HTTPS compatible-mode/v1 地址；三个 workload 分别配置 |
| Qdrant | 真实本地持久存储 `.autolava-test/issue248/qdrant`；单进程访问，独立服务部署未验证 |
| 预检 | qwen-plus 聊天 200（15 tokens）、实际 ping 工具调用 200（176 tokens）、Embedding 200（12 tokens）；不重复 probe |

## 证据与分类

可提交的合成证据摘录：[真实流程、失败与模型依据](evidence/issue-248-real-service.json)。其中保留每轮输入、完整实际回答、HTTP 回读状态、SSE 关键事件、记忆来源/纠正历史、模型工具提议、当前背景及真实经营工具结果；原始单轮 JSON 和供应商日志有 SHA-256，摘录不包含完整历史对话或向量全文。

原始证据仍在隔离工作树 `.autolava-test/issue248/`：`provider.jsonl`、`flow.jsonl`、各 label JSON、SQLite/Qdrant 及日志。它们未整体提交，其他检出不能假定拥有这些本地文件。预检和直接模型对比位于 `.autolava-test/preflight248.json` 与 `.autolava-test/issue248/model_comparison.json`。

| 类别 | 本次结论 |
| --- | --- |
| 模型替身 / 公开 HTTP 回归 | 最终受影响范围 96 passed；不能替代真实模型内容审阅 |
| 真实 Qdrant + Embedding | 保存、纠正、删除、重建后的实际召回已验证；仅本地模式 |
| 真实百炼 | 明确记忆、普通聊天整理、工具分析、召回均实际执行；失败保留 |
| 人工内容审阅 | 忠实保存/同义合并、引用拒绝、隔离及描述版本采用通过；篇幅与关闭指标措辞部分失败 |
| 真实浏览器 | 描述独立检查 3 passed；本次补候选、纠正/删除、移动操作、聊天工具、停止/重置/刷新及切范围迟到记忆响应 |
| 部署 | Docker、代理、生产、独立 Qdrant 服务和异地恢复未执行，不属于本次声明 |

## 真实流程与人工审阅

| 证据 label | 结果与判定 |
| --- | --- |
| explicit / synonym | 通过。明确指令原话忠实保存；中文同义改写复用 `c37be74df43a4aad94e7eff707f45854`，两个原话来源均保留，不丢先结论/后数据含义 |
| automatic | 失败。早期 qwen-plus 主聊天复述旧保存回执；后台提议缺 evidence，服务端拒绝 memory_invalid_proposal，未假报保存 |
| automatic_fixed / automatic_context_fixed | 部分成功/失败。整理补 evidence 后能保存，但 qwen-plus 主聊天两次修复后仍复述旧回执；不是已解决证据 |
| model_comparison / selected_chat | 对比直接调用 qwen3.6-plus 后正常回应当前偏好；selected_chat 再经公开 HTTP/SSE 验证“不宣称已保存”，后台同义合并成功。直接对比不冒充 HTTP 流程 |
| quote_temporary | 通过。引述同事“每日五折”及一次英文要求均未成为有效记忆；reject。英文经营建议不当作实际经营证据 |
| conflict_confirm / conflict_fixed | 首次失败：显式 conflict 的目标字段被原规则拒绝。修复提示后产生无关联候选，仅待确认；不宣称它会自动替换旧项 |
| 浏览器修改确认 | 通过。将该旧无关联候选改为独立“以后分析使用简体中文。”再确认；保留原来源及人工变更记录。不以此证明冲突替换 |
| bakery_recall | 召回/偏好部分通过。重置后中文改写实际召回三个 ID/版本，欧元、三点、先结论遵循；225 欧元、2 经营日、整数日均 113 欧元与工具一致。但“经营稳定”无逐日依据，“关闭洗车数量”被说成“无相关记录”，内容失败。后台错误重提历史偏好，因不属于当前 input 被拒绝；失败未重试刷绿 |
| linked_conflict | 通过。修复后真实 qwen-plus 提议关联旧 ID/版本，形成 `faea8e26fbd24a18a13f0da10428e07f`；浏览器确认后旧“先结论”退出有效记录，新“先数据/后结论”以版本2生效 |
| corrected_recall | 部分成功。人工将欧元/三点改为欧元/两点，重置后只引用该 ID 版本2和新顺序版本2，未引用旧版本/旧顺序；实际先数据后结论，未再说经营稳定或无历史记录。但列了五个数据项，没有落实两点篇幅，仍失败。后台 infer “习惯按固定篇幅和顺序”仅为候选，未升级事实，浏览器已拒绝 |
| wash_isolation | 通过。另一门店无私人记忆命中，225 EUR、2经营日、洗车覆盖1/缺失1、平均每车收入50 EUR（仅覆盖日，不含结算，不外推全期）与工具一致；没有凭空分配缺失日期 |
| admin_isolation | 隔离通过。另一管理员的记忆及聊天初始为空，真实检索 references=[]；共享本店公共描述，正确说明面包/生日蛋糕业务。后台 reject；没有复制描述为私人记忆 |
| description_updated | 背景采用通过、措辞失败。同一管理员同一会话不重置，描述改为花店 revision2，下一轮实际采用花店而非烘焙，结构化指标仍关闭；但仍把关闭说成“系统未记录相关洗车数据” |
| description_cleared | 背景采用通过、措辞失败。revision3 空描述，模型明确无法确定主营业务，未恢复花店/烘焙/默认洗车行业；平均每车收入不可用正确，但“未记录相关数据”仍越界 |
| deleted_recall | 通过。删除欧元/篇幅记忆，重建索引并重置；回答“不知道”，只引用剩余顺序偏好，没有恢复已删除偏好、已拒绝候选或旧顺序。后台 reject |

本次不把“相关召回成功”当成“回答必然遵循全部偏好”，也不把服务端安全拒绝当成模型提议质量通过。

## 修复与剩余问题

1. 整理 Agent 根据服务端 job_id 区分后台和显式模式，明确 evidence/content/target 规则；后台来源、范围、版本校验保持严格。
2. 主聊天修正“普通聊天不会自动保存”的旧提示，在当前用户消息前增加有预算约束的提醒，避免复述历史保存回执。qwen-plus 的两次失败保留；qwen3.6-plus 通过样例不代表确定性防幻觉。
3. 显式冲突可以关联同范围、同类别、当前有效且版本一致的旧记忆；确认复用现有事务内替换与索引失效流程。无目标候选仍可独立确认，不根据语义猜测删除旧项；历史无目标候选不被自动补关系。相同原话但目标/版本不同的候选不误合并。
4. 新增公开 HTTP 回归验证正常替换、旧项已变的409、跨门店404、无效目标和历史无目标候选不吞掉关联候选。人工确认不绕过权限/版本校验。
5. 增加汇总不能推断稳定趋势、关闭指标不能推断无历史记录的主提示。后一措辞在新样例仍失败；两点篇幅仍未稳定遵循。本次停止继续试提示或换模型，保留为 T10 内容缺口。

## 浏览器补验

真实 API/Vite 为 18858/18859，真实 Chromium，合成数据；天气适配为无外部调用的替身，聊天/整理/Embedding 未替换输出。

- 1280px：旧候选修改后确认、关联冲突直接确认；刷新后恢复已保存聊天与工具结果。
- 390px：展开 AI 记忆，拒绝真实 infer 候选、纠正简体中文偏好至版本3、删除该记忆并确认；主要按钮可操作。截图 [移动记忆管理](evidence/issue-248-mobile-memory.png) 已人工查看，无横向溢出；截图当时为索引处理中，不能当作索引就绪证据。
- 移动端实际提交通用聊天并停止，界面出现“本次回答已停止”；重置后聊天为空。随后实际提交指定期间概览，渲染225/113/50欧元及部分覆盖说明；刷新后恢复该结果。
- 门店切换：将已由真实 API 取得的店1记忆响应延迟到店2后送达，店2仍显示暂无记忆。前两次驱动分别因提前 unroute 和遗漏展开导致 Route already handled / locator timeout；未计为产品通过，修正驱动后同一公开交互检查结束码0。
- 账号切换：真实退出/登录另一合成管理员，将原账号店1的已获取记忆响应延迟到登录后送达；结果 `late_response=delivered, other_admin_empty=true`，未带入旧私人记忆。
- 描述草稿保护、保存失败/冲突、清空和迟到描述响应沿用下方本票已完成的独立3项检查，不重复。流式 SSE 正在生成时的跨账号/门店迟到事件，本次没有重新注入验证，T9历史证据仍单列；不宣称所有异步组合完整覆盖。
- 控制台登录前401、无 favicon 404、首页当天无台账404和重启失效旧登录态401有记录；没有将它们误报为模型/记忆失败，也没有称控制台零错误。

## 已完成的独立描述浏览器检查（本轮未重跑）

复用现有 `scripts/verify-issue-239-live.py` 和 `frontend/tests/store-description-live.spec.ts`，没有新增测试或修改产品代码。临时 SQLite 从空库迁移到 `0028`，真实管理员登录，正常请求经过真实 HTTP；测试刻意注入的保存/退出失败及迟到响应属于受控故障。

首次启动未进入浏览器：共享 `node_modules` 缺少 Vite，日志保留在隔离工作树 `.autolava-test/description248.log` 及 `.autolava-test/issue-239/vite.err.log`。通过该工作树现有 lockfile 执行 `npm ci --no-audit --no-fund` 安装 302 个依赖，不改原工作区。

本地临时驱动 `.autolava-test/description_driver248.py` 仅将输出目录改为 `issue-248-description`，并覆盖 Windows Vite 的 `@` 绝对路径别名；正式脚本及产品代码未改。重跑命令：

```powershell
& backend/.venv/Scripts/python.exe .autolava-test/description_driver248.py
```

最终日志 `.autolava-test/description248-retry.log`：`3 passed (12.5s)`，退出码 0。截图及服务日志位于 `.autolava-test/issue-248-description/`。保留 Node 的 `NO_COLOR/FORCE_COLOR` 提示。这些本地证据文件未提交，不能假定其他检出拥有它们。

## 回归、用量与最终审查

- 早先53 passed / 214.57s只覆盖较早diff，不能替代最终回归；先前被交接中止的chat/tools运行未计入通过或失败。
- 新增冲突定点回归：4 passed / 21.54s。
- 最终受影响范围：`tests/api/test_agent_memory.py tests/api/test_memory_jobs.py tests/api/test_agent_chat.py tests/api/test_agent_tools.py tests/test_agent_resources.py -q --no-cov`，**96 passed / 455.28s，退出码0**。这是模型替身、真实临时SQLite的公开接口回归。
- Ruff检查四个改动Python文件通过；git diff --check通过。未变更前端产品代码、HTTP/schema或依赖，无全量前端构建/T9重跑。
- 用量观测快照：47次模型调用、91539 text tokens、21次Embedding，含早期失败调用；不包括三次preflight及一次直接模型比较。停止请求可能在供应商返回usage前取消；Embedding产品adapter不暴露完整token用量，不能宣称完整账单或总费用。控制上限为80次模型调用/150000 text tokens/150次Embedding。
- Standards 独立审查：0项发现；对照仓库标准和代码smell基线，没有硬违规或值得报告的smell。
- Spec 独立审查：部分通过，2项已记录的内容验收缺口（两点篇幅未落实、关闭指标被推断为无记录）；没有发现新增确定性代码错误或范围扩张。本轮跨范围迟到SSE组合未重新注入验证，保持未验证。固定点如上，审查包含本票全部已提交及未提交diff和两个证据文件。无远端写入。

## 尚未通过及未验证

关闭指标不等于无历史记录的内容质量、篇幅偏好实际遵循仍未通过，因此 #248 保持部分成功。普通后台整理仍可能误提取历史内容，由服务端拒绝，不能称模型可靠提取全部通过。跨范围SSE迟到事件的本轮组合覆盖及独立服务/部署项未验证；不以96项替身测试替代这些缺口。
