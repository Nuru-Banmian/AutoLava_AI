## Agent skills

### Issue tracker

本仓库的问题通过 `Nuru-Banmian/AutoLava_AI` 的 GitHub Issues 跟踪。详见 `docs/agents/issue-tracker.md`。

### Triage labels

本仓库使用五个默认的 triage 标签。详见 `docs/agents/triage-labels.md`。

### Domain docs

领域文档采用 single-context 布局。详见 `docs/agents/domain.md`。

### Implement completion

执行 `$implement` 且改动准备进入共享目标分支时，本地实现、测试、code review 和提交不是完成状态。除非用户明确要求仅保留本地、禁止远程写操作，或任务属于不会进入生产分支的一次性实验/原型，完成实现后必须自动：

1. push 当前 Issue 的独立分支；
2. 创建目标分支正确的 Pull Request；
3. 等待必需 CI 全部完成并通过；
4. 合并 Pull Request；
5. 确认合并提交已进入目标分支后关闭对应 Issue。

存在未合并依赖时，可以先创建以依赖分支为 base 的堆叠 Pull Request，但不得提前合并或关闭 Issue；依赖合并后必须把 PR 重新对准最终目标分支、重新验证 CI，再完成合并与关单。不得因为 Issue 已被提前关闭而把未合并依赖视为完成。
