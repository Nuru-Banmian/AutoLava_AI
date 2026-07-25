# Issue #40 实现交接

## 目标

继续完成 GitHub Issue [#40：完成“记账”高频录入体验](https://github.com/Nuru-Banmian/AutoLava_AI/issues/40)。

本次工作按用户指定的 `C:\Users\1\.agents\skills\implement\SKILL.md` 执行。该技能要求：

- 尽可能使用 TDD；
- 完成后使用 `code-review` 双轴审查；
- 运行聚焦测试、类型检查、完整测试；
- 将工作提交到当前分支。

仓库领域语言和 issue 流程见：

- `CONTEXT.md`
- `docs/agents/domain.md`
- `docs/agents/issue-tracker.md`
- `docs/agents/triage-labels.md`

## 当前 Git 状态

- 工作目录：`D:\work\myself\AI-try\AutoLava-AI`
- 当前分支：`codex/implement-issue-40`
- 当前 HEAD：`fbf9cb1193ca352f3356fa2dd38beaaa9fd5dee7`
- 当前 `origin/main`：`83952e0395953d4ea6d73893083e5a74df16c53a`
- 分支已合并最新主线，因此包含阻塞项 #37 的“提前休息”状态统一。

已提交：

```text
fbf9cb1 fix: address ledger entry review findings (#40)
23471b2 Merge remote-tracking branch 'origin/main' into codex/implement-issue-40
d9795f9 feat: complete high-frequency ledger entry (#40)
```

当前有两个未提交文件：

```text
M frontend/src/components/LedgerForm.test.tsx
?? docs/2026-07-25-issue-40-handoff.md
```

不要丢弃 `LedgerForm.test.tsx` 的改动；它是最后一个 TDD red 测试。

## 已完成的行为

相对 `83952e0...HEAD`，已完成：

- 桌面和移动导航统一使用“记账”。
- 页面标题改为“记账”，录入区域命名为“记账录入”，表单不再重复设置名称。
- 新总额记账金额、新分类收入项目、已启用门店的洗车数量均初始化为 `0`。
- 零初始化不产生未保存更改状态，也不会自动保存。
- 分类记账始终显示“合计金额”，从 `€0` 实时计算。
- 非法金额显示具体字段错误，并保留最近一次有效合计。
- 分类合计超过 JavaScript 安全整数范围时显示“合计金额超出可安全计算范围”、保留最近有效合计并阻止保存。
- 金额和洗车数量只接受非负安全整数。
- 洗车数量改为 `type="text"`、`inputMode="numeric"`，没有浏览器增减箭头。
- 洗车数量和事件始终可见；桌面并排，手机上下排列。
- 关闭洗车数量设置后，事件占满可用行宽。
- 事件使用固定提示：

  ```text
  记录可能影响经营的特殊情况，如当地活动、泥雨等（选填）
  ```

- 空白或仅空格事件保存为 `null`。
- 营业记录详情中的“活动：”改为“事件：”。
- “休息”继续把经营数值和已启用门店洗车数量规范化为 `0`。
- “提前休息”保留收入和洗车数量。
- 打开页面、填写但未点击保存时不会产生写请求；既有日期/门店切换未保存保护继续通过。
- 浏览器覆盖总额记账、分类记账、1280/390/320 响应式布局、可访问语义和保存行为。

## 已完成验证

合并 #37 后，后端完整验证：

```text
388 passed
ruff: All checks passed
```

审查修复提交前后的前端完整验证：

```text
36 test files passed
306 Vitest tests passed
28 Playwright tests passed
npm run build passed
```

Vite 仅报告既有的大 chunk 警告，不是失败。

最近的聚焦验证也通过：

```text
17 LedgerForm tests passed
10 daily-flow Playwright tests passed
TypeScript check passed
```

随后新增了下面的最后一个 red 测试，因此当前聚焦测试预期为 `1 failed, 17 passed`。

## Code review 结果

固定点使用最新主线：

```text
git diff 83952e0...HEAD
git log 83952e0..HEAD --oneline
```

### Standards

最终复核结果：

- 无仓库标准硬性违规；
- 最初发现的 `Duplicated Code` 已修复：提交时复用 `amountResults`，不再重新调用 `parseWholeAmount`；
- 无新增 smell；
- `git diff --check` 通过。

### Spec

前三个发现均已修复：

1. 历史 `休息` 记录的空洗车数量会保存为 `null`；
2. 分类合计安全整数溢出无错误且仍可保存；
3. 浏览器缺少总额记账和关闭洗车设置后事件占满宽度的覆盖。

最终 Spec 复核只剩一个边界：

> 未编辑的历史事件若含首尾空格，点击保存会被 `trim()` 静默改写，不满足“历史自由文本保持不变”。

## 当前 red 测试

`frontend/src/components/LedgerForm.test.tsx` 已新增：

```tsx
it("preserves unchanged historical event text exactly", () => {
  const onSave = vi.fn();
  render(<LedgerForm
    categories={[]}
    config={composedConfig}
    record={savedRecord({ activity: "  历史事件  " })}
    onSave={onSave}
  />);

  fireEvent.click(screen.getByRole("button", { name: "保存" }));

  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
    activity: "  历史事件  ",
  }));
});
```

当前失败原因：

```text
Expected activity: "  历史事件  "
Received activity: "历史事件"
```

## 建议的下一步

1. 在 `frontend/src/components/LedgerForm.tsx` 增加事件规范化逻辑：

   - `value.trim() === ""` 时返回 `null`；
   - 如果 `value` 与已加载的 `record.activity` 完全相等且非空，原样返回；
   - 对新输入或已编辑的非空事件继续返回 `value.trim()`，保留现有行为和既有测试。

   可在组件内定义类似：

   ```ts
   const normalizedActivity = (value: string) => {
     const trimmed = value.trim();
     if (!trimmed) return null;
     if (record?.activity != null && value === record.activity) return value;
     return trimmed;
   };
   ```

2. 同时在两个位置使用同一逻辑，避免 dirty 签名与提交数据不一致：

   - `semanticSignature` 中的 `activity`
   - `onSave` body 中的 `activity`

3. 运行聚焦验证：

   ```powershell
   cd frontend
   npm test -- src/components/LedgerForm.test.tsx src/pages/LedgerPage.test.tsx
   npx tsc -b --pretty false
   npx playwright test tests/daily-flow.spec.ts --reporter=line
   ```

4. 运行最终完整前端验证：

   ```powershell
   npm test
   npx playwright test --reporter=line
   npm run build
   ```

5. 检查并提交：

   ```powershell
   cd ..
   git diff --check
   git status --short --branch
   git add frontend/src/components/LedgerForm.tsx `
     frontend/src/components/LedgerForm.test.tsx `
     docs/2026-07-25-issue-40-handoff.md
   git commit -m "fix: preserve historical ledger event text (#40)"
   ```

6. 对最终 `git diff 83952e0...HEAD` 再做一次 Standards / Spec 复核。预期两轴均为 0 findings。

7. 确认工作树干净后向用户交付。不要擅自 push、创建 PR、评论或关闭 Issue，除非用户另行要求。
