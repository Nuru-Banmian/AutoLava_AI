# Agent T10 真实服务与内容验收（#248）

日期：2026-10-08。工单：[Issue #248](https://github.com/Nuru-Banmian/AutoLava_AI/issues/248)，父规格：[Issue #238](https://github.com/Nuru-Banmian/AutoLava_AI/issues/238)。

**状态：部分成功，内容质量仍有失败，不能声明 T10 全部完成。资源和小规模真实调用授权已齐备。**

## 基线与安全边界

- 固定审查基线 `f331fa38cfd711d523297db3ef9fa3c41713fa60`，包含 T9；初步报告提交 `e0cd797`。
- 前轮实施工作树 `C:\Users\1\.codex\worktrees\issue-248-acceptance\AutoLava-AI`；续做发布工作树 `C:\Users\1\.codex\worktrees\issue-248-release\AutoLava-AI`，分支 `codex/issue-248-real-acceptance`。原工作区 `D:\work\myself\AI-try\AutoLava-AI` 的无关脏文件保留，不整体暂存。
- SQLite 迁移至 0028，使用隔离合成管理员、两门店及每日台账，不写实际业务数据库。
- 密钥仅从原项目根目录被忽略的 `.env` 读取到服务端。报告、提交和日志不包含密钥、登录密码或供应商认证头。
- 用户已授权小规模真实调用以及本票推送、创建 PR、等待 CI、合并并关闭 Issue。授权以验收达到完成门槛为前提；目前未达到，尚未推送、创建/合并 PR 或评论/关闭 Issue。未做 Docker 或生产部署。
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
| 模型替身 / 公开 HTTP 回归 | 前轮受影响范围 96 passed；续做最终定点4 passed；不能替代真实模型内容审阅 |
| 真实 Qdrant + Embedding | 保存、纠正、删除、重建后的实际召回已验证；仅本地模式 |
| 真实百炼 | 明确记忆、普通聊天整理、工具分析、召回均实际执行；失败保留 |
| 人工内容审阅 | 忠实保存/同义合并、引用拒绝、隔离及描述版本采用通过；历史篇幅与关闭指标措辞失败保留；续做篇幅样例改善，但内容评价及花店复验仍有缺口 |
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
5. 增加汇总不能推断稳定趋势、关闭指标不能推断无历史记录的主提示。前轮后一措辞和两点篇幅仍失败。续做将工具不可用原因拆分，并增加工具批次后的提醒及有限条目输出形态；没有增加模型重试或替换输出。末轮定点结果见下，历史失败不被覆盖。

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

## 前轮回归、用量与审查（历史快照）

- 早先53 passed / 214.57s只覆盖较早diff，不能替代最终回归；先前被交接中止的chat/tools运行未计入通过或失败。
- 新增冲突定点回归：4 passed / 21.54s。
- 最终受影响范围：`tests/api/test_agent_memory.py tests/api/test_memory_jobs.py tests/api/test_agent_chat.py tests/api/test_agent_tools.py tests/test_agent_resources.py -q --no-cov`，**96 passed / 455.28s，退出码0**。这是模型替身、真实临时SQLite的公开接口回归。
- Ruff检查四个改动Python文件通过；git diff --check通过。未变更前端产品代码、HTTP/schema或依赖，无全量前端构建/T9重跑。
- 用量观测快照：47次模型调用、91539 text tokens、21次Embedding，含早期失败调用；不包括三次preflight及一次直接模型比较。停止请求可能在供应商返回usage前取消；Embedding产品adapter不暴露完整token用量，不能宣称完整账单或总费用。控制上限为80次模型调用/150000 text tokens/150次Embedding。
- Standards 独立审查：0项发现；对照仓库标准和代码smell基线，没有硬违规或值得报告的smell。
- Spec 独立审查：部分通过，2项已记录的内容验收缺口（两点篇幅未落实、关闭指标被推断为无记录）；没有发现新增确定性代码错误或范围扩张。本轮跨范围迟到SSE组合未重新注入验证，保持未验证。固定点如上，审查包含本票全部已提交及未提交diff和两个证据文件。无远端写入。

## 2026-10-08 发布续做与定点复验

固定基线及远端 main 均核对为 `f331fa38cfd711d523297db3ef9fa3c41713fa60`；已继承提交 `56bb8e1`、`682938e`。原工作区和前轮工作树未修改；未重新执行需求讨论、资源预检、描述浏览器3项或T9全套。

继承的4文件diff区分“指标关闭”和“未记录/零”的工具原因，并要求召回篇幅约束覆盖整答。续做仅补充有限条目的明确输出形态（一个编号列表、每项连续段落，不加子清单），没有新增模型重试、后处理模型回答或手动替换内容。

| label | 实际结果与人工判定 |
| --- | --- |
| release_preference | 明确保存“欧元、最多两点”，新ID `490478089dea483aafbe6f70be7410fd` v1；没有恢复已删除旧ID |
| release_bakery | 工具数值225/2/113正确，关闭措辞改善；仍四个数据小点，篇幅失败。后台误提历史来源被 memory_invalid_proposal 拒绝，保留 |
| release_updated | 采用花店背景，但未重新查询，推断全部收入来自花艺销售/实际不涉及洗车，且超过两点；内容失败 |
| release_cleared | 真实 model_timeout，无输出；失败 |
| final_bakery | 召回欧元/两点v1及顺序v2，数值正确，未把指标关闭说成无历史；两项数据加两项结论/建议，总计四项，篇幅仍失败 |
| final_updated | 已更新花店revision8并发起call61，交接停止服务中断，未形成label JSON；不是通过，也不称供应商失败 |
| final_cleared | 前轮交接前未执行 |
| resume_bakery | completed；重置后召回同一有效偏好，整答严格两项、先数据后结论、欧元及225/2/113正确。但“正常的日常销售表现”属于工具无基准支持的评价，内容仅部分成功 |
| resume_updated | 花店revision10，真实 model_timeout、无输出；未通过，不重试 |
| resume_cleared | 清空revision11，真实 model_timeout、无输出；未通过，不重试 |

`final_bakery` 的 infer 候选 `3f09c90198d145c988d6f7105c45bfa5` 原话为“按我惯用的篇幅和顺序总结”，候选描述“有篇幅和顺序偏好但未明确细节”只保留为待确认，未升级为事实；它没有补充具体偏好信息，属于低价值候选，不能作为高质量提取通过。续做烘焙亦产生待确认候选，未自动确认或写成有效事实。

服务启动后通过公开HTTP回读交接中断会话，再重置；原始回读和描述修订见本地 `resume-flow.log`。合成JSON增量保留旧label、完整实际回答、SSE关键事件、来源和供应商工具提议；中止/未执行单独标注。原始日志继续追加，没有删除失败。

回归：交接中的39 passed发生在工具后提醒加入前；4 passed / 21.90s为上轮最终定点。续做最终diff定点 `test_agent_tools.py test_agent_chat.py -k 'disabled_metrics or skill_and_reference or repeated_tool or context_budget' -q --no-cov` 为 **4 passed、35 deselected / 22.15s、exit0**；Ruff及git diff --check通过。未重跑已通过96项或T9全套。

续做用量：**累计已发起70次模型调用、已观测138687 text tokens、30次Embedding**；本轮新增9次模型调用（62–70），没有重置累计计数。启动前将已发起但未落入旧usage.json的call61补入计数；观察器改为发起时即持久化计数。原始日志中call56、61、67、70均无usage事件（分别涉及前轮超时、交接中断及本轮两次超时），供应商实际用量未知，不视作零费用或完整账单。上述数字不包括3次preflight和1次直接对比；原控制上限仍80次/150000 text tokens/150次Embedding，停止继续尝试。

最终独立双轴审查均以固定基线 `f331fa38cfd711d523297db3ef9fa3c41713fa60` 覆盖全部已提交与未提交代码、最终报告及合成证据：

- **Standards：0项硬标准违规、0项值得报告的smell。** 对照AGENTS、领域文档及模块约束；权限、版本、短事务和预算边界保留。该结论不代表内容验收完成。
- **Spec：0项新增确定性代码缺陷、0项范围扩张，2项验收缺口。** ① 烘焙样例无基准的“正常销售”评价；② 花店/清空复验超时无输出。#248要求内容审阅及受影响流程复验，故完成门槛未达。25个label原始SHA、provider及resume日志SHA、三个续做回答与原件均核对一致，历史失败/中断/未执行没有被写成通过。

本票6个拟提交文件已与安全配置中的密钥值及临时登录密码作不输出值的扫描，无命中。旧17个turn及63条provider观察记录均完整保留。两个本票服务已退出，18858/18859无监听。仅本地提交；远端回读 #248仍OPEN，main仍为固定基线，未进入PR/CI/合并关单流程。

## 第一次续做停止时的缺口（历史快照）

#248保持部分成功：末轮花店及清空复验真实超时，烘焙仍含无基准评价，不能声明内容验收全部通过。普通后台整理仍可能误提取历史内容而被拒绝，低价值推断仅待确认，不能称模型可靠提取全部通过。跨范围SSE迟到事件本轮未重新注入，独立服务/部署项未验证；不以替身测试代替真实内容缺口。验收完成门槛未达到，不推送、创建PR、等待CI、合并或关闭Issue。


## 用户要求修复后的增量（当前结论）

用户随后要求继续修复，并明确将累计已观测文本token上限提高为 **170000**；累计模型调用上限保持 **80**，拒绝提高至84。计数及未知用量记录没有重置。

### 定位与改动

- 用保存的公开HTTP/SSE轨迹回放失败：`resume_updated`约59.03s、`resume_cleared`约59.81s结束，均在60s整轮时限处无输出；bakery为26.11s。回放脚本按既有内容缺口断言失败，没有额外真实调用。
- [百炼官方深度思考说明](https://www.alibabacloud.com/help/zh/model-studio/deep-thinking)确认qwen3.6-plus默认开启思考且支持`enable_thinking=false`。原adapter没有显式控制。额外思考可能耗尽工具回合总时限，但未抓取供应商原始reasoning包，不能将推测写为唯一已证实根因。
- 新增可选且独立的`AUTOLAVA_AGENT_CHAT_ENABLE_THINKING`、`AUTOLAVA_AGENT_MEMORY_ENABLE_THINKING`，默认None，不向供应商发送此字段；配置false/true时按布尔值发送。记忆transport明确映射MEMORY配置，不继承CHAT。只在隔离验收服务设置CHAT=false，qwen-plus整理仍沿用其默认；原项目`.env`未修改。整轮60s、步骤、重试、工具及输出预算均未放宽。
- 补充经营好坏/正常/达标需要工具提供比较基准的要求。当前背景快照移至历史后、当前用户前；提醒本轮重新读技能和查工具。真实样例证明这些提醒仍不足以约束当前模型，不能称已解决数据来源问题。
- 压缩重复提示以保留8000字符上下文最小配置对6000字符输入的既有支持。最初两轮定点测试仍失败，日志保留；最终压缩后原断言通过，没有提高预算或缩短测试输入。

### 增量真实样例

四个样例均为同一管理员/门店、同一会话的当前描述修订，真实聊天qwen3.6-plus（CHAT=false）、真实qwen-plus整理及Embedding；没有手写或替换回答。

| label | 结果与人工审阅 |
| --- | --- |
| repair_updated | 花店revision12，completed，约5.46s，严格两项、当前花店背景正确；只调用聊天1次，没有本轮经营工具，沿用历史225/2/113。未通过当前数据来源复验 |
| repair_cleared | 空描述revision13，completed，约6.03s，严格两项、不恢复旧行业；只调用聊天1次，仍复用历史金额。“因关闭，缺乏数据”可理解为本轮不可用，措辞不精确，但不直接判作断言无历史记录；数据来源仍失败 |
| grounded_cleared | 上下文顺序修正后，空描述revision14，completed，约4.39s；整答两项，但仍未重新查询，并照搬上一条清空回答。提醒没有达到实际内容门槛 |
| grounded_updated | 同会话更新花店revision15，completed，约5.49s；背景采用正确，整答两项，但仍无本轮工具、复用历史金额，未通过。建议“以稳定日常营收”为目标，不等同断言已稳定，不额外误判成稳定事实 |

四个后台整理任务均真实失败`memory_invalid_proposal`，未成为有效记忆；模型试图重提历史偏好来源的提议及服务端拒绝保留在证据，不能把拒绝写成模型提取质量通过。四条聊天completed只证明请求未超时，不证明内容正确，也不证明工具后的评价提醒生效。

新增原始`repair-flow.log`、`grounded-flow.log`及其SHA；合成证据现在保留29个实际label、旧观察记录和完整新增输出，另列交接中断及未执行项。当前门店为非空花店revision15。

### 回归与用量

- 思考配置wire三态和工作负载隔离先执行为**3 failed / 1 passed**；修复后连同旧provider错误、超时和流式回归为**11 passed / 66.08s**。
- 第一次聊天/工具范围回归：**41 passed / 2 failed / 220.35s**，保留失败。两项分别为新增提示使上下文预算超限、旧测试假设工具结果必须为最后一条消息。后者改为按`tool_call_id`查实际tool消息，保留角色、数值、函数和工具清单断言，适配工具后system提醒。
- 两次上下文定点回归均**2 passed / 1 failed**，未记通过；最终压缩后`latest_description / context_budget / skill_and_reference / fragmented_tool`为**4 passed / 39 deselected / 25.75s**。
- 最终聊天/工具完整受影响回归 **43 passed / 219.36s / exit0**（`tests/api/test_agent_chat.py tests/api/test_agent_tools.py -q --no-cov`）。Ruff及git diff --check通过；不重跑T9或描述浏览器检查。
- 当前累计**78次模型调用、154576已观测text tokens、34次Embedding**；本轮新增8次（71–78）。call56/61/67/70仍无usage，实际用量未知，不计作零，也不称完整账单；仍不含3次preflight和1次直接对比。仅剩2次模型额度不足以可靠完成完整工具查询及后台整理，停止调用，不将80上限当作必须耗尽的指标。

最终固定基线独立增量审查已完成：

- **Standards：0项硬标准违规、0项值得报告的smell。** 可选思考配置、独立映射、预算及低信任边界保留；工具测试按call_id验证实际响应，没有弱化数值断言。
- **Spec：0项新增确定性代码缺陷、0项范围扩张；验收仍未完成。** 四个新样例未重新查询经营工具、复用历史金额；四个后台错误提议被拒，不能视为高质量提取通过。29个label与provider/repair/grounded日志SHA核对一致。当前partial、不发布结论符合#248。

运行时缺口已明确：`assistant/graph.py`的generate在没有tool calls、但有非空文本时直接记录completed；提示要求本轮查询，并没有程序化门禁确保经营数据回答已取得当前工具证据。应用的门店背景读取、Embedding/Qdrant检索及SQLite有效记忆回查是上下文准备，不能替代`store_overview`经营查询。前轮超时样例确有store_overview，本轮四个样例确无经营查询；不得混写。

本轮真实调用已停止，两个验收服务退出、18858/18859无监听。11个拟提交文件通过实际密钥值和临时密码的不输出值扫描，旧25个turn及96条provider观察记录均完整保留。远端回读Issue仍OPEN、main仍固定基线；没有远端写入。

**当前结论仍为部分成功。** 可选思考模式控制和上下文预算回归已修复，四条请求未重现整轮超时；但当前模型仍绕过本轮工具并沿用历史数字，背景/篇幅成功不能替代经营数据来源验收。后台错误提议继续被拒绝。没有达到#248完成门槛，保持Issue OPEN，不推送、创建PR、合并或关单；不执行Docker或生产部署。

## 2026-10-08 本轮经营依据门禁与最终受影响回归

本节接续前述真实验收快照，不替换历史判定。续做起点仍为 `30e6170e29211c51b65172dbb8f66b4d7987609f`，固定审查基线仍为 `f331fa38cfd711d523297db3ef9fa3c41713fa60`。用户已批准本轮门禁实施；本次恢复没有重做需求、方案、资源预检、描述浏览器验收或 T9 全套。

### 已实施范围与保证边界

- 普通聊天先形成经服务端 Pydantic 校验的 `plan_response`，区分 `general`、`clarify`、`business`。经营计划须列出1至3个不重复日期期间，每期1至366天；其他路径查询为空。规划夹带正文不发布，无合法计划以 `grounding_plan` 失败。
- 进入 `business` 后，运行时经当前受限工具入口读取 `store-analysis` 技能并执行全部计划 `store_overview` 查询，不能重新启用禁用能力。只由本轮工具成功结果形成依据，核对来源、门店、请求期间及截至门店当地今天的实际期间，并绑定服务端身份范围、run_id、会话世代和工具调用。正文发布前及 completed 前均检查必要期间；缺依据以 `grounding_unavailable` 失败，不保存成功助手消息或创建普通后台整理任务。
- 规划、重试、自动技能读取和查询均消耗原有模型、工具、时长、上下文及输出预算，没有提高配置上限。经营路径通常至少两次主模型调用，后台记忆整理另计。通用问答、澄清、SSE、历史持续、停止、重置和撤权沿用原入口；前端增加两个门禁失败原因的可读提示。
- **保证仅限进入 business 路径后的计划查询必须取得本轮成功依据。** 语义路由及日期解释仍可能误判，general/clarify 路径不强制经营查询；计划是否覆盖自然语言问题、正文是否忠实采用数值及后台提取质量，仍须真实审阅。completed 不能等同内容通过。

### 离线结果、失败与修复

以下使用受控模型及百炼 HTTP 替身，经实际鉴权、公开 HTTP/SSE 和迁移后的临时 SQLite 验证；不是新增真实百炼或 Embedding 验收。所有日志位于发布工作树 `.autolava-test/`，未整体提交。

| 日志 | 实际结果 |
| --- | --- |
| `grounding-red.log` | 旧代码新增回归：9 failed / 2 passed / 52.79s，保留 |
| `grounding-green-first.log` | 第一版：53 passed / 1 failed / 275.56s，上下文预算失败，不能称最终版本全过 |
| `grounding-context-recheck.log` | 上下文修复定点：1 passed / 20 deselected / 7.05s / exit0 |
| `grounding-frontend.log` | 既有前端定点：9 passed / 4.75s / exit0；本次未重跑 |
| `grounding-frontend-build.log` / `grounding-ruff.log` | 既有生产构建及 Ruff 通过；本次核对原日志 |
| `grounding-regression-final.log` | 前次交接中止，仍0字节，无最终计数，不能记通过 |
| `grounding-regression-resume-20261008T092019204810Z.log` | 本次首次四组回归：95 passed / 6 failed / 492.75s / exit1，原样保留 |
| `grounding-memory-repro-20261008T092906969638Z.log` | 失败节点定点复现：1 failed / 7.66s / exit1，原样保留 |
| `grounding-memory-recheck-20261008T093100596420Z.log` | 六项修复定点：6 passed / 28 deselected / 32.45s / exit0 |
| `grounding-memory-ruff-20261008T0931.log` | 本次新增修改的记忆测试 Ruff 通过 / exit0 |
| `grounding-regression-postfix-20261008T093151345255Z.log` | 最终四组完整回归：**101 passed / 487.60s / exit0** |

本次六项失败均来自 `test_agent_memory.py` 三处固定索引取值（其中一处参数化为四项），将 `chat.calls[-1][2]` 当作背景 JSON。HEAD 已将当前快照放在历史之后，索引2实际为“历史问题”；并非快照缺失。仅修测试为按 user 角色及 `store_background` 字段定位唯一快照，保留原记忆、检索状态、门店描述、旧版本拒绝及新指令成功断言，另补聊天 completed 断言。**本次恢复未修改产品代码或门禁方案。**

最终完整受影响范围为 `tests/api/test_agent_grounding.py tests/api/test_agent_chat.py tests/api/test_agent_tools.py tests/api/test_agent_memory.py -q --no-cov`。每次本次测试另有同名 JSON，记录完整命令、起止时间、实际退出码及总耗时；表中秒数为 pytest 自报时间。

新增门禁用例覆盖无计划历史金额隔离、连续两轮重新查询、计划校验、未来空查询、通用/澄清、步骤与工具预算、错来源/门店/请求及实际期间、必要期间部分失败、禁用工具、规划与自动查询两阶段停止/重置/撤权，以及真实 adapter 的受控 wire、规划正文隔离和 usage 累加。替身 wire 只证明传输与运行时行为，不证明供应商实际语义或内容质量。

### Standards

沿用最新实施交接记载的固定基线独立审查，覆盖本轮门禁及两个当时未跟踪源码/测试：0项硬标准违规、0项值得报告的 smell。本次恢复没有产品代码变化。

在上述审查之后新增的记忆测试补丁已单独交由 Standards 子代理只读复核：**0项硬违规、0项判断性问题**。快照查找及唯一性断言符合既有测试做法，原业务断言保留。此增量复核不冒充重新完成全票审查。

### Spec

最新实施交接记载的固定基线独立审查为0项确定阻塞代码缺陷、0项未授权范围扩张，真实复验与语义路由风险仍为 partial；本次沿用该已完成记录，没有重做全范围审查。

记忆测试补丁由另一 Spec 子代理独立只读复核：**0项确定缺陷、0项范围扩张，未发现断言实质削弱**。新增 completed 断言加强了聊天成功检查；未改产品行为、预算或真实证据判定。两轴结论均不代替实际测试或真实内容验收。

### 真实证据、用量与未验证项

- 真实证据 JSON 原样保留29个 label、104条供应商观察。请求状态25 completed / 4 failed只是请求状态，不是25项内容通过；`final_updated`交接中断及 `final_cleared`当时未执行仍单列保留。四个最新真实 label 的无本轮经营查询、复用历史金额，以及四个后台 `memory_invalid_proposal` 失败判定均未更改。前轮两个 resume 超时样例确曾执行经营查询，不能混写为从未查工具。
- 本轮没有真实百炼模型或 Embedding 调用，未启动真实验收服务。累计仍为 **78次已发起模型调用 / 154576个已观测文本 tokens / 34次 Embedding**；严格上限 **80次 / 170000 tokens** 未变，计数未重置。call56/61/67/70用量未知，不视为零费用或完整账单；仍排除3次 preflight 和1次直接模型比较。
- 剩余两次模型额度不足以可靠完成通常两次主模型调用及后台整理的完整复验，没有为耗尽额度调用，没有绕过后台整理冒充完整验收。门禁后的语义路由、日期解释、当前依据及正文采用情况尚未真实复验；记忆错误提议、篇幅、关闭指标措辞及无基准评价的历史失败继续保留。
- 跨范围迟到 SSE 本轮未重新注入；独立 Qdrant 服务、Docker、生产部署、代理及异地恢复没有新增验证。本轮不执行 Docker 或生产部署。

### 交付检查与当前状态

最终拟交付的11个源码、测试、README和报告文件纳入实际密钥及合成临时登录值的内存扫描，无命中；不输出扫描值。`git diff --check`通过。原工作区、两处工作树受保护文件、历史失败/中止日志、真实证据 JSON、累计用量及本次测试修复等共244个文件的 SHA-256 复核无变化；旧报告正文逐字节保留，仅在末尾追加本节。`.playwright-cli/`及本地 harness 未暂存；没有遗留本次四组 pytest 进程。核查结果另存 `.autolava-test/grounding-preservation-final-20261008T0940.json` 和 `grounding-delivery-verification-20261008T0940.json`。

一次只读路径检索曾在工具输出中带出本票合成测试密码的局部字符，未输出完整密码或 `.env` 密钥；随后改为 AST 只取字段名，后续实际值比较仅在内存进行。该过程问题不改写为“从未输出任何敏感片段”，不在报告复制该片段。

**当前仍为 partial。** 真实受影响流程及内容审阅尚未达到 #248 完成门槛。远端只读回读 #248 为 OPEN、main 为固定基线；本次未推送、创建 PR、运行远端 CI、合并、评论或关单。本轮实现、测试修复与报告继续保留本地未提交状态。


## 2026-10-08 新预算工具验证与两条完整真实复验

本节只追加本次增量。保留前文全部失败、中止、未执行及离线判定；原 `issue-248-real-service.json` 的29个label和104条观察记录逐字节未变。新证据单独保存为 [issue-248-grounding-retest-20261008.json](evidence/issue-248-grounding-retest-20261008.json)，不运行旧导出器覆盖原证据。本次未修改产品门禁、产品测试或前端，不重做资源预检、描述浏览器验收或T9全套；既有最终101 passed /487.60s /exit0继续只表示离线回归。

### 预算授权、验证与边界

用户直接授权累计限额调整为90次模型调用、200000个已观测文本tokens；Embedding仍为150。先验证本地预算工具，再保存旧账本、授权增量和隔离SQLite/Qdrant快照，最后只修改两个limit字段。迁移时累计仍为78/154576/34，未重置或重写历史数值。旧未知usage调用56、61、67、70及排除3次preflight/1次直接比较的口径保持不变；已观测文本tokens不代表完整账单或实际费用。

本地工具的首次5项测试为5 passed /2.08s /exit0。独立审查补充互补partial usage、逐call字段高水位及重启去重、atomic fsync/replace失败、未知用量/取消后预留、chat/memory/Embedding共享串行锁、原始超预留usage留证，以及到达文本上限/违规后停止后续付费调用。最终为 **17 passed /1.80s，pytest/Ruff/语法检查均exit0**。首次Ruff样式失败日志、原脚本备份与后续通过日志均保留；这组检查使用替身，未产生真实调用。

预留使用可见输入JSON UTF-8字节、固定framing余量及完整输出上限，只是保守的操作估算，**不是已证明的供应商token精确上界**。新未知usage保留预留；完整usage按字段高水位结算一次，矛盾字段取较大值；观察到超估算会记录并阻止后续请求，不能把事后停止说成事前精确保证。启动器持有进程间独占锁，共享async lock只承担单服务实例内串行。缺失/损坏/旧限额账本拒绝启动，发起前计数和未知状态持久化；atomic写入失败保留旧有效账本和唯一命名临时材料并停止该实例。

本次工具及运行材料均在被忽略的 `.autolava-test/`：

- 预算最终日志：`issue248/budget-audit-final-20261008T183137384.log`；原文件备份：`issue248/budget-audit-backups/20261008T182818173/`。
- 本次独立目录：`issue248/retest90_20261008T103212805320Z/`，含旧账本、授权增量、SQLite/Qdrant快照、旧日志prefix摘要、新API/流程日志、两条完整SSE/JSON及退出证据。
- 新启动器指向 `live248_grounding_app:app`，仅启动API，未运行旧 `serve248.py`、迁移、建账号或造数。沿用隔离SQLite/Qdrant、qwen3.6-plus主对话、独立qwen-plus后台配置、text-embedding-v4/1024及CHAT=false；Weather为隔离替身。密钥仅从原项目根被忽略.env安全读取，认证值不输出、不写入交付证据。

### 两条真实结果与内容审阅

两条在同一会话generation6顺序执行；每条等后台job终态及索引无pending后才推进。以下是合成隔离数据上的真实百炼调用，不等同生产、独立Qdrant服务或全部自然语言通过。

| 新label后缀 | 当前描述版本 / run | 实际模型调用 | 前台结果 | 后台终态 |
| --- | --- | --- | --- | --- |
| `_updated` | 花店revision16；`3c133afa37c149a7819230799a38f506` | 79规划、80正文、81整理 | completed；本轮重点正文门槛通过 | job22 failed /memory_invalid_proposal |
| `_cleared` | 空描述revision17；`db53c5e8c8394164af6a2376ef31106d` | 82规划、83正文、84整理 | completed；本轮重点正文门槛通过 | job23 failed /memory_invalid_proposal |

完整label以 `retest90_20261008T103212805320Z` 为前缀，两条各有9条原始provider增量记录。PATCH/GET/context实际revision一致；花店采用当前鲜切花与婚礼花艺背景，清空后没有恢复烘焙或花店旧行业。两次plan均为business、查询2026-10-01..02；程序先执行read_skill(store-analysis)及全部计划store_overview，成功grounding绑定本轮run/store1/generation6并先于首delta，最后completed。真实供应商接受了本次计划schema并返回有效计划；这只证明本次两条路由，不扩大成语义路由普遍正确。

两次本轮工具均返回AnalyticsService来源、请求/实际期间10-01..02、225欧元台账营业额、0欧元已确认公司结算、225欧元总收入、2经营日、四舍五入113欧元经营日均台账营业额；record_days/interval_days为2/2，missing_record_days为0。关闭的洗车指标为null，工具明确说明不使用历史数量，不能判断历史记录是否存在。本轮数值即使与旧回答相同，也是重新查询后取得，不能记成沿用历史金额。

实际retrieval回读有效偏好为 `490478089dea483aafbe6f70be7410fd` v1（欧元、最多两点）和 `faea8e26fbd24a18a13f0da10428e07f` v2（先数据、最后结论），未把pending候选用于前台检索。两答各一个两项编号列表，没有额外子列表/结语；数值、舍入、期间、顺序及关闭原因正确。花店回答的“以稳定日常营收”是建议目标，没有断言营收已经稳定；没有无比较基准的正常/增长/达标评价或把全部收入归因花艺销售。清空回答说明无法确定主营业务，没有从旧历史恢复行业。正文未逐项重述工具的2/2覆盖及缺失0，保留为表达局限，未错误外推或宣称查遍全部资料。

**后台提取仍未通过。** call81和84都提出duplicate，目标为 `ff69ee02308a4da798ef15d7a5bd3085` v1“用户偏好经营数据总结的篇幅和顺序”，实际状态是pending_confirmation，不能作为duplicate的active目标。两次evidence各自逐字等于本轮完整input；本次确定问题不是误引历史evidence，而是把待确认候选当有效合并目标，且提问未新增明确长期细节，本应reject/not_saved。应用以memory_invalid_proposal安全拒绝，job22/23均failed，不把安全拒绝冒充高质量提取。两条记忆before/after逐字相同；索引available、pending0、failed0。最终全库memory jobs为completed14/failed9，无pending/running；index ready5，无待处理索引。

### 累计、保护与发布结论

本次增量为 **6次模型调用 /15100个已观测文本tokens /2次Embedding**，最终累计 **84 /169676 /36**；调用79至84都有完整usage，新未知列表为空，旧未知56/61/67/70不变；新token预留均已结算，没有reservation_violation。90/200000/150限额继续保留，未耗尽剩余额度，未无理由重复相同流程。后续无修正的重试、PR/远端CI/合并/关单、Docker与生产部署均未执行。

新流程完成后已停止本票API与启动器。旧29-label证据JSON、原provider前缀、历史失败/中止日志及两处.playwright-cli受保护材料保持原样；新真实增量、测试初始失败、导出脚本首轮语法失败及修正后成功日志分别留存。原工作区无关改动未触碰，未暂存或提交本地harness及认证材料。独立只读内容复核与主代理审阅一致：两条前台重点样例通过，后台两条提取均失败。

**当前仍为partial，Issue #248保持OPEN。** 已验证business门禁后的真实路由、当前工具依据与本次正文改善，但完整后台提取质量未达到验收门槛，未执行发布授权序列。下一步应针对后台误选pending目标建立窄诊断与明确修正，再决定有限复验；本次没有改变或放松提取门禁，没有为关单绕过后台整理。


## 2026-10-08 后台候选目标修复与有限真实复验

本节仅追加本轮结果，原报告正文、29个label／104条观察及上轮两条增量证据均保留。恢复时工作树为 `codex/issue-248-real-acceptance`，HEAD 为 `30e6170e29211c51b65172dbb8f66b4d7987609f`，固定审查基线仍为 `f331fa38cfd711d523297db3ef9fa3c41713fa60`。先核对9个已跟踪修改、3个本票未跟踪文件、空暂存区及实际账本84／169676／36；保留既有经营依据门禁、测试修复和所有失败、中止、未执行记录，没有重做资源预检、描述浏览器验收、T9全套或已完成全票审查。

### 确定性反馈与最小修复

- 先新增 `tests/agents/test_memory_curator_contract.py`，在实际 `create_memory_graph → model.stream_tools` 边界回放call81/84的完整当前输入、描述版本及记忆集合。旧代码6 failed／2.66s／exit1：pending候选混在有效记忆数组中，target ID／version未收窄。该观察器检查实际消息和schema后停止，不返回脚本化reject，不提交提议，也没有供应商调用。首红日志 `issue248/curator-contract-red-20261008T185124302.log` 保留。
- 对另一处 repeated 来源风险另建公开HTTP/SSE、迁移临时SQLite与实际提交服务回放，旧代码1 failed／7.76s／exit1：模型替身给出active的准确ID／版本／内容后，仅“沿用惯用篇幅和顺序”的本轮输入也被追加成有效来源。自此可以称为**离线确定性复现**，不能扩大为另一次真实模型误存证据。
- 后台模型输入将active `memories`与`pending_candidates`分开；原完整权威snapshot仍用于提交时等值检查。按active快照收窄目标ID／版本schema，无active时不提供duplicate／update动作。独立枚举不保证ID／版本一一配对，服务仍核对范围、active状态、类别和目标自身版本；schema不是强制模型服从的保证。
- 提示词明确：未表达具体新长期细节、仅要求沿用已有格式时应reject，不能从旧记忆或候选补出本轮来源。duplicate也必须满足明确长期表达，repeated匹配补齐状态／版本／类别。该处收紧是修复已复现来源绕过，未放松门禁；非法提议仍为`memory_invalid_proposal`，不转成成功。没有把pending升级active、删除候选或跳过后台整理；明确保存、有效合并、候选确认、纠正及失效机制保留。

### 离线验证与独立增量审查

本轮原始日志和材料目录为 `.autolava-test/issue248/memoryfix_20261008T1050202478615Z/`，未整体提交。

| 日志 | 结果与口径 |
| --- | --- |
| `repeated-source-red-20261008T185159465.log` | 1 failed／7.76s／exit1，旧来源绕过回放 |
| `contract-green-first.log` | 4 failed／3 passed／8.07s／exit1，首次schema读取器结构假设与enum-only形态不匹配；后改为兼容nullable anyOf形态，原失败保留 |
| `curator-contract-green-20261008T185345326.log` | 10 passed／13.71s／exit0；实际边界、空／仅pending能力、共享schema不变、非法目标／版本／类别／历史来源、安全失败及有效同义合并 |
| `affected-regression-first.log` | 49 passed／8 failed／301.16s／exit1，旧后台／向量测试固定读取第3条消息而误读“历史问题”，日志保留 |
| `snapshot-test-fix-targeted.log` | 11 passed／70.81s／exit0；只复用既有唯一背景快照定位方法，原业务断言保留 |
| `packaged-resources.log` | 10 passed／1.09s／exit0 |

最终完整受影响范围为 `tests/api/test_memory_jobs.py tests/api/test_agent_memory.py tests/api/test_agent_vectors.py tests/agents/test_memory_curator_contract.py -q --no-cov -n 4 --dist loadscope`；`affected-regression-final.log` 为 **67 passed／175.05s／exit0**。包含后台保存／合并／更正、候选确认／修改／拒绝、范围隔离、人工变更／描述／重置失效、有限失败／重启恢复，以及真实本地Qdrant配可控Embedding的索引、旧版本拒绝与重新召回。没有重跑T9全套；此前101项结果仍只作其对应版本的历史证据。

Ruff与`git diff --check`通过。Standards与未参与产品或测试实现的Spec代理分别独立审查本轮产品增量，均为0项阻断实现发现、0项范围扩张；两处后续测试定位修复也分别独立窄审，未发现断言削弱。额外测试作者复核单独注明其独立性局限，未用它代替独立Spec结论。所有离线结果均不替代真实供应商与内容质量审阅。

### 新真实流程、后台结果与内容缺口

新独立证据为 [issue-248-memory-fix-retest-20261008.json](evidence/issue-248-memory-fix-retest-20261008.json)。新目录、新label、新服务／流程日志与独立导出器均未覆盖上轮已完成材料，旧一次性setup未重跑。密钥仅安全读取原项目根被忽略的.env，harness通过AST／内存检查，未打印临时密码或片段。

沿用隔离SQLite、本地持久Qdrant、qwen3.6-plus（CHAT=false）、独立qwen-plus记忆配置与text-embedding-v4／1024；Weather仍为替身。为降低旧聊天上下文造成的调用前保守预留，先通过公开reset递增generation6→7，保存旧聊天及前后回读，严格核对长期记忆和账本均不变；两条之间不重置。仅将本次验收服务主模型及后台单次输出上限降至1024，预算估算算法和90／200000／150累计硬限不变。预留仍是操作估算，不能声称已证明精确token上界。

| 新label后缀 | 当前描述／run | 实际调用 | 前台内容 | 后台／索引 |
| --- | --- | --- | --- | --- |
| `_updated` | 花店revision18；`b1a2759270a24ae3852abc65c051f93a` | 85规划／86正文／87整理 | 数值、篇幅、顺序通过；行业适配建议partial | job24 completed／not_saved；available，pending0／failed0 |
| `_cleared` | 空描述revision19；`a2c0c2c1c80f45d09b76d6c8a7b6268c` | 88规划／89正文／90整理 | 当前空背景、数值、篇幅、顺序通过；行业适配建议partial | job25 completed／not_saved；available，pending0／failed0 |

完整label以 `memoryfix_20261008T1050202478615Z` 为前缀。每条先等回答、后台及索引终态再推进；机器检查通过不等同内容通过。两条实际plan均为business、期间2026-10-01..02，重新读取store-analysis并执行store_overview，成功grounding绑定各自run／store1／generation7，先于首delta。工具实际来源AnalyticsService，225欧元台账、0欧元已确认公司结算、225欧元总收入、2经营日、日均整数113，覆盖2／2、缺失0；关闭洗车指标为null且原因不推断历史记录不存在。实际召回active偏好仍为欧元／最多两点v1与先数据／后结论v2，候选未参与前台有效记忆。

**后台本轮两条重点真实修复通过。** call87／90均提出reject，分别引用当前“沿用惯用篇幅和顺序”片段，无target；不再duplicate pending，也未改选active追加模糊来源或创建低价值候选。两个任务均一次attempt／一次call、无失败记录，结果not_saved；before／after记忆完整相同，候选仍待确认，索引无待处理或失败。本次是模型实际提出合法reject后的完成，不是应用把非法提议自动改成成功。

**整条内容验收仍为partial。** 两答各一个两项编号列表、数据先于结论、数值和覆盖正确，均明确无历史／目标／比较基准不能评价好坏；清空答明确主营未知，未恢复旧行业。但花店答没有体现鲜切花／婚礼花艺背景，两答都建议“核对是否需重新启用该指标以支持后续单车产值分析”。花店或主营未知时，缺少该经营指标是否适用的依据；用户询问平均每车收入支持解释不可用，不足以支撑行业相关建议。该缺口是**建议适配不足**，不能写成模型断言花店实际经营洗车、开关被越权修改或旧背景复活。主审与独立内容审阅一致，两个manual-review均不标full_flow_passed。

### 账本、保护与发布状态

本轮真实增量为 **6次模型调用／11468个已观测文本tokens／2次Embedding**；最终累计 **90／181144／38**。85至90均有完整usage，无新unknown、未结预留或reservation_violation；旧56／61／67／70未知usage与排除3次preflight／1次直接比较口径保持不变。已观测文本tokens不代表完整账单，未知usage不是零费用。到90次模型调用硬限后停止，没有额外重试、提高限额或为耗尽预算而调用。

两条结束后已停止本票API和启动器；18858／18859无监听，最终数据库任务为completed16／failed9、无pending／running，索引ready5、无待处理。旧9次失败仍保留。保护核对确认原29／104证据、上轮两条增量、原provider前缀及旧材料原样；只有本轮实际运行应改变的SQLite／Qdrant／账本／追加provider发生变化。原工作区git状态、发布树及原项目两处.playwright-cli的文件哈希均不变，暂存区为空。20个本票交付文件与实际密钥／临时认证值的内存扫描无命中；不输出值。报告追加后的最终核对为本轮目录 `final-preservation-verification-v2.json`，初次保护结果及所有初始测试／本地工具失败另留原日志和 `local-tooling-notes.json`／`snapshot-tooling-note.txt`。最终回读Issue仍OPEN、远端main仍为固定基线；所有产品改动保持本地未提交。

**当前仍为partial，Issue #248保持OPEN。** 后台候选误选与模糊来源绕过已完成离线修复及两条有限真实验证，前台行业适配建议仍未达到本轮完整内容门槛。既有发布授权保留，但本次未提交／推送、创建PR、运行远端CI、合并、评论或关单；没有执行Docker或生产部署。不能把历史失败label改写为通过，也不能以后台通过代替整条内容通过。

## 2026-10-08 用户确认后的交付决定

用户审阅上述遗留问题后，确认行业建议不值得阻塞本次发布，并明确要求整理全部问题与解决方案为Markdown、上传PR、合并及关闭#248。当前交付判定调整为：**小规模限定验收完成，行业建议适配作为已接受的非阻断局限，进入必要CI及受保护合并流程。** 本节是最新发布判定；前文partial／OPEN／未发布均保留为各轮当时的事实。

两条新流程的完整内容审阅仍为partial，原始JSON、`full_flow_passed=false`和独立审阅结论不改写。其后台均真实正确reject／not_saved，本轮经营查询、金额、覆盖、篇幅和顺序通过；遗留的是行业相关建议的适用性，未发现错误金额、越权写入或候选被提升为有效记忆。此前把这项低优先级建议作为整票发布阻塞偏严，本次按用户确认调整优先级，产品门禁和历史证据保持原有语义。

完整问题、定位证据、方案、修复结果与本地工具过程错误见 [#248 问题与解决方案复盘](issue-248-problems-and-solutions.md)。沿用最终67项受影响回归、10项资源检查及独立Standards／Spec增量审查，不重做资源预检、描述浏览器或T9全套。

累计仍为90次模型调用／181144个已观测文本tokens／38次Embedding，原未知usage和排除口径不变；本次只补文档与执行发布流程，无新增真实供应商调用，不提高或重置预算。发布仍须必要CI通过、确切HEAD保护合并及PR／Issue／远端main回读；Docker和生产部署不在此次执行范围内。
