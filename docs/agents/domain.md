# 领域文档

本文件说明工程技能在探索代码库时应如何使用本仓库的领域文档。

## 探索前应读取

- 仓库根目录中的 **`CONTEXT.md`**；或者
- 如果仓库根目录中存在 **`CONTEXT-MAP.md`**，则读取该文件；它会指向各上下文对应的 `CONTEXT.md`，应读取与当前主题相关的每一份文档。
- **`docs/adr/`**：读取与即将处理区域相关的 ADR。在 multi-context 仓库中，还应检查 `src/<context>/docs/adr/` 中特定上下文的决策。

如果上述文件不存在，**直接继续，不作提示**。不要指出缺失，也不要预先建议创建。`/domain-modeling` 技能（可通过 `/grill-with-docs` 和 `/improve-codebase-architecture` 使用）会在术语或决策真正确定后按需创建这些文件。

## 文件结构

Single-context 仓库（适用于大多数仓库）：

```text
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-event-sourced-orders.md
│   └── 0002-postgres-for-write-model.md
└── src/
```

Multi-context 仓库（根目录中存在 `CONTEXT-MAP.md`）：

```text
/
├── CONTEXT-MAP.md
├── docs/adr/                          ← 系统级决策
└── src/
    ├── ordering/
    │   ├── CONTEXT.md
    │   └── docs/adr/                  ← 特定上下文的决策
    └── billing/
        ├── CONTEXT.md
        └── docs/adr/
```

## 使用术语表中的词汇

当输出中需要命名领域概念时（例如 Issue 标题、重构提案、假设或测试名称），使用 `CONTEXT.md` 中定义的术语。不要改用术语表明确避免的同义词。

如果术语表中尚未包含所需概念，这就是一个信号：要么你正在创造项目中并未使用的说法（应重新考虑），要么领域模型确实存在空缺（应记录下来，交由 `/domain-modeling` 处理）。

## 标明与 ADR 的冲突

如果输出与现有 ADR 冲突，应明确指出，而不是静默覆盖：

> _与 ADR-0007（事件溯源订单）冲突——但值得重新讨论，因为……_
