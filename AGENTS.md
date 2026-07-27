## Agent skills

### Issue tracker

本仓库的问题通过 `Nuru-Banmian/AutoLava_AI` 的 GitHub Issues 跟踪。详见 `docs/agents/issue-tracker.md`。

### Triage labels

本仓库使用五个默认的 triage 标签。详见 `docs/agents/triage-labels.md`。

### Domain docs

领域文档采用 single-context 布局。详见 `docs/agents/domain.md`。

### Implement completion

执行 `$implement` 且改动准备进入共享目标分支时，本地实现、测试、code review 和提交不是完成状态。除非用户明确要求仅保留本地、禁止远程写操作，或任务属于不会进入生产分支的一次性实验/原型，完成实现后必须自动：

1. 将当前 Issue 的已验证提交集成到项目指定的共享目标分支；
2. 直接 push 该共享目标分支；
3. 确认远端目标分支已经包含这些提交；
4. 关闭对应 Issue。

默认不创建 Pull Request；只有用户明确要求时才创建。存在未完成依赖时不得把改动推入共享目标分支，也不得提前关闭 Issue。不得因为 Issue 已被提前关闭而把未合并依赖视为完成。
