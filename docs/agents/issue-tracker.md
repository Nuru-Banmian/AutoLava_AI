# 问题跟踪器：GitHub

本仓库的问题和 PRD 均以 GitHub Issue 的形式保存。所有操作均使用 `gh` CLI。

## 约定

- **创建问题**：`gh issue create --title "..." --body "..."`。多行正文使用 heredoc。
- **读取问题**：`gh issue view <number> --comments`，通过 `jq` 筛选评论，同时获取标签。
- **列出问题**：`gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'`，并按需添加 `--label` 和 `--state` 筛选条件。
- **评论问题**：`gh issue comment <number> --body "..."`
- **添加或移除标签**：`gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **关闭问题**：`gh issue close <number> --comment "..."`

通过 `git remote -v` 推断仓库；在仓库克隆目录中运行时，`gh` 会自动完成推断。

## 是否将 Pull Request 作为 triage 入口

**PRs as a request surface: no.（将 PR 作为请求入口：否。）** _如果本仓库将外部 PR 视为功能请求，可将 `no` 改为 `yes`；`/triage` 会读取此标记。_

设为“是”后，PR 将使用与 Issue 相同的标签和状态，并通过对应的 `gh pr` 命令操作：

- **读取 PR**：`gh pr view <number> --comments`，并使用 `gh pr diff <number>` 查看 diff。
- **列出待 triage 的外部 PR**：运行 `gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments`，仅保留 `authorAssociation` 为 `CONTRIBUTOR`、`FIRST_TIME_CONTRIBUTOR` 或 `NONE` 的 PR，排除 `OWNER`、`MEMBER` 和 `COLLABORATOR`。
- **评论、添加标签或关闭**：使用 `gh pr comment`、`gh pr edit --add-label` / `--remove-label` 和 `gh pr close`。

GitHub 的 Issue 和 PR 共用同一编号空间，因此单独的 `#42` 可能表示其中任意一种。先运行 `gh pr view 42`，失败后再运行 `gh issue view 42`。

## 当技能要求“发布到问题跟踪器”时

创建一个 GitHub Issue。

## 当技能要求“获取相关工单”时

运行 `gh issue view <number> --comments`。

## Wayfinding 操作

供 `/wayfinder` 使用。**地图（map）**是一个 Issue，**子项（child）**是关联的子 Issue。

- **地图**：一个带有 `wayfinder:map` 标签的 Issue，其正文包含 Notes、Decisions-so-far 和 Fog。使用 `gh issue create --label wayfinder:map` 创建。
- **子工单**：作为 GitHub 子 Issue 关联到地图的 Issue（通过 `gh api` 调用 sub-issues 端点）。如果未启用子 Issue，则将子工单加入地图正文的任务列表，并在子工单正文开头写入 `Part of #<map>`。标签为 `wayfinder:<type>`，其中类型可为 `research`、`prototype`、`grilling` 或 `task`。认领后，将工单指派给负责推进的开发者。
- **阻塞关系**：使用 GitHub 的**原生 Issue 依赖关系**作为规范且在 UI 中可见的表示。通过 `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>` 添加依赖边，其中 `<blocker-db-id>` 是阻塞项的数字型**数据库 ID**，可通过 `gh api repos/<owner>/<repo>/issues/<n> --jq .id` 获取，而不是 `#number` 或 `node_id`。GitHub 通过 `issue_dependencies_summary.blocked_by` 报告仍未关闭的阻塞项数量，作为实时放行条件。如果依赖关系不可用，则在子工单正文开头添加 `Blocked by: #<n>, #<n>`。当所有阻塞项均已关闭时，该工单解除阻塞。
- **前沿查询**：列出地图中所有未关闭的子项（使用 `gh issue list --state open`，范围限定为地图的子 Issue 或任务列表），排除存在未关闭阻塞项（`issue_dependencies_summary.blocked_by > 0`，或 `Blocked by` 行中包含未关闭 Issue）或已有负责人指派的工单；按地图中的顺序选择第一个符合条件的工单。
- **认领**：运行 `gh issue edit <n> --add-assignee @me`，这是会话中的首次写操作。
- **解决**：运行 `gh issue comment <n> --body "<answer>"`，然后运行 `gh issue close <n>`，最后在地图的 Decisions-so-far 中追加上下文指针（gist 和链接）。
