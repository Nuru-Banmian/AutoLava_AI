# 未录入营业记录详情卡片 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让桌面端营业记录表中的未录入日期可选中，并以与真实记录相同布局的详情卡片提供补录入口。

**Architecture:** 为表格行和详情卡片定义一个轻量的虚拟空记录联合类型，不向数据库新增或写入占位数据。页面以选中日期而不是选中真实记录 ID 驱动详情；真实记录继续使用原有详情和管理能力，空记录使用相同卡片布局、占位字段和既有每日记账链接。

**Tech Stack:** React 19、TypeScript、React Router、Vitest、Testing Library、date-fns。

## Global Constraints

- 空日期只在前端展示，不写入数据库，不参与统计。
- 空记录的“修改这天记录”链接必须是 `/ledger?date=YYYY-MM-DD`。
- 空记录卡片与已有记录卡片复用同一组件、同一操作区位置和按钮样式。
- 只有真实记录可显示管理员管理、删除、历史和回滚入口。
- 历史日历仅真实记录显示蓝点；移动端列表本次保持不变。

---

### Task 1: 让详情卡片支持虚拟空记录

**Files:**
- Modify: `frontend/src/components/RecordDetailPanel.tsx`
- Test: `frontend/src/components/RecordDetailPanel.test.tsx`

**Interfaces:**
- Consumes: `RecordSnapshot`，其中真实记录保留现有字段与行为。
- Produces: `RecordDetail` 联合类型，定义为 `RecordSnapshot | { id: null; date: string }`；`RecordDetailPanelProps.record` 改为该类型。

- [ ] **Step 1: 写出空记录详情的失败测试**

  在 `RecordDetailPanel.test.tsx` 新增测试，直接传入 `{ id: null, date: "2026-07-15" }`，断言卡片与真实记录一样显示日期、四个字段标题和“修改这天记录”链接，同时断言空记录值为“未录入”“—”，且没有“管理这天记录”按钮。

  ```tsx
  render(
    <MemoryRouter>
      <RecordDetailPanel
        record={{ id: null, date: "2026-07-15" }}
        canEdit
        canManage
        onManage={vi.fn()}
      />
    </MemoryRouter>,
  );
  expect(screen.getByText("未录入", { exact: true })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "修改这天记录" })).toHaveAttribute("href", "/ledger?date=2026-07-15");
  expect(screen.queryByRole("button", { name: "管理这天记录" })).not.toBeInTheDocument();
  ```

- [ ] **Step 2: 运行测试确认失败**

  Run: `npm test -- RecordDetailPanel.test.tsx`

  Expected: FAIL，因为现有 `RecordDetailPanelProps.record` 仅接受 `RecordSnapshot`。

- [ ] **Step 3: 实现联合类型与空记录卡片分支**

  在 `RecordDetailPanel.tsx` 导出 `RecordDetail`。通过 `record.id === null` 识别空记录；保留同一 `Card`、`CardHeader`、`CardContent`、四格信息区和按钮容器。空记录在信息区渲染“营业状态：未录入”“营业额：—”“洗车数量：—”“天气：—”，不渲染收入明细、活动、管理按钮；编辑按钮继续使用：

  ```tsx
  {canEdit && <Button asChild><Link to={`/ledger?date=${record.date}`}>修改这天记录</Link></Button>}
  {canManage && record.id !== null && <Button type="button" variant="outline" onClick={onManage}>管理这天记录</Button>}
  ```

- [ ] **Step 4: 运行组件测试确认通过**

  Run: `npm test -- RecordDetailPanel.test.tsx`

  Expected: PASS，包含已有真实记录测试与新空记录测试。

- [ ] **Step 5: 提交详情卡片改动**

  ```powershell
  git add frontend/src/components/RecordDetailPanel.tsx frontend/src/components/RecordDetailPanel.test.tsx
  git commit -m "feat: show unrecorded record details"
  ```

### Task 2: 让桌面表格中的空日期可选中

**Files:**
- Modify: `frontend/src/components/RecordTable.tsx`
- Test: `frontend/src/components/RecordTable.test.tsx`

**Interfaces:**
- Consumes: `RecordDetail` 的空记录形状与现有 `RecordSnapshot`。
- Produces: `RecordTableRow = RecordSnapshot | { id: null; date: string }`；`selectedDate: string | null` 和 `onSelect(record: RecordTableRow): void`。

- [ ] **Step 1: 写出空行可选中的失败测试**

  在 `RecordTable.test.tsx` 传入真实记录与 `{ id: null, date: "2026-07-15" }`，点击空行、再按 Enter，断言 `onSelect` 两次均收到该空行；断言空行具备 `tabIndex="0"` 和选中态。

  ```tsx
  const empty = { id: null, date: "2026-07-15" };
  render(<RecordTable records={[empty]} selectedDate={empty.date} loading={false} error={null} onSelect={onSelect} onRetry={onRetry} />);
  const row = screen.getByRole("row", { name: /2026年7月15日 未录入/ });
  fireEvent.click(row);
  fireEvent.keyDown(row, { key: "Enter" });
  expect(onSelect).toHaveBeenNthCalledWith(1, empty);
  expect(onSelect).toHaveBeenNthCalledWith(2, empty);
  ```

- [ ] **Step 2: 运行测试确认失败**

  Run: `npm test -- RecordTable.test.tsx`

  Expected: FAIL，因为当前空行没有交互事件且 `onSelect` 仅接受真实记录。

- [ ] **Step 3: 统一表格选择交互**

  将 `RecordTableProps.selectedId` 替换为 `selectedDate`，并将 `onSelect` 参数改为 `RecordTableRow`。真实行和空行均渲染为可聚焦、可点击、支持 Enter/空格的表格行；选中条件统一为 `record.date === selectedDate`。保留空行的“未录入 / — / —”展示，保留真实记录的实际字段展示。

- [ ] **Step 4: 运行表格测试确认通过**

  Run: `npm test -- RecordTable.test.tsx`

  Expected: PASS，包含真实行键盘选择和空行鼠标/键盘选择。

- [ ] **Step 5: 提交表格交互改动**

  ```powershell
  git add frontend/src/components/RecordTable.tsx frontend/src/components/RecordTable.test.tsx
  git commit -m "feat: make unrecorded table rows selectable"
  ```

### Task 3: 用选中日期驱动页面详情卡片

**Files:**
- Modify: `frontend/src/pages/BusinessRecordsPage.tsx`
- Test: `frontend/src/pages/BusinessRecordsPage.test.tsx`

**Interfaces:**
- Consumes: `RecordTable` 的 `selectedDate` / `onSelect(RecordTableRow)` 与 `RecordDetailPanel` 的 `RecordDetail`。
- Produces: 桌面端空日期点击后显示空记录详情卡片，并提供既有日期记账链接。

- [ ] **Step 1: 写出页面级失败测试**

  在 `BusinessRecordsPage.test.tsx` 使用一个未包含 `2026-07-17` 的接口响应，等待表格渲染后点击“2026年7月17日”空行，断言右侧出现“未录入”、编辑链接指向 `/ledger?date=2026-07-17`，且没有“管理这天记录”。

  ```tsx
  fireEvent.click(within(screen.getByRole("table")).getByText("2026年7月17日").closest("tr")!);
  expect(await screen.findByText("未录入", { exact: true })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "修改这天记录" })).toHaveAttribute("href", "/ledger?date=2026-07-17");
  expect(screen.queryByRole("button", { name: "管理这天记录" })).not.toBeInTheDocument();
  ```

- [ ] **Step 2: 运行页面测试确认失败**

  Run: `npm test -- BusinessRecordsPage.test.tsx`

  Expected: FAIL，因为页面目前只依据真实记录 ID 生成右侧详情。

- [ ] **Step 3: 替换为日期选择状态并接入详情卡片**

  将 `selectedRecordId` 替换为 `selectedDate: string | null`。在成功获取真实记录后，保持现有默认选择第一个真实记录的行为，改为设置其 `date`；表格选择回调设置 `nextRecord.date`。从当前 `tableRows` 按 `selectedDate` 找到 `selectedTableRow` 并传给 `RecordDetailPanel`。

  对管理操作保持真实记录保护：

  ```tsx
  const selectedRecord = selectedTableRow && selectedTableRow.id !== null ? selectedTableRow : null;
  {selectedTableRow ? (
    <RecordDetailPanel
      record={selectedTableRow}
      canEdit
      canManage={isAdmin && selectedTableRow.id !== null}
      onManage={() => {
        if (selectedTableRow.id === null) return;
        setManagementDate(selectedTableRow.date);
        setManagementOpen(true);
      }}
    />
  ) : null}
  ```

  门店、筛选范围与分页变更时清除 `selectedDate`、移动端选择和管理状态。移动端仍传递真实记录，不把空行加入移动端列表。

- [ ] **Step 4: 运行页面与组件回归测试**

  Run: `npm test -- BusinessRecordsPage.test.tsx RecordTable.test.tsx RecordDetailPanel.test.tsx`

  Expected: PASS，空行详情、真实记录详情、管理员管理入口和导出/分页回归均通过。

- [ ] **Step 5: 运行生产构建**

  Run: `npm run build`

  Expected: PASS，TypeScript 编译与 Vite 构建均完成。

- [ ] **Step 6: 提交页面状态改动**

  ```powershell
  git add frontend/src/pages/BusinessRecordsPage.tsx frontend/src/pages/BusinessRecordsPage.test.tsx
  git commit -m "feat: open unrecorded record details"
  ```

### Task 4: 最终验证

**Files:**
- Verify only: `frontend/src/components/RecordDetailPanel.tsx`
- Verify only: `frontend/src/components/RecordTable.tsx`
- Verify only: `frontend/src/pages/BusinessRecordsPage.tsx`

**Interfaces:**
- Consumes: 已完成的空记录选择与详情行为。
- Produces: 可交付的本地 phase 1 改动，不创建 PR。

- [ ] **Step 1: 检查提交范围与空白错误**

  Run: `git diff HEAD~3..HEAD --check` and `git status --short`

  Expected: 本功能提交不包含 README、进度文件、清理脚本或其他用户现有未提交改动。

- [ ] **Step 2: 运行完整前端测试**

  Run: `npm test`

  Expected: PASS。

- [ ] **Step 3: 记录验证结果，不创建 PR**

  交付时报告测试与构建命令结果、提交哈希和本地分支 `feature/phase-1-foundation`；不推送、不创建 PR。
