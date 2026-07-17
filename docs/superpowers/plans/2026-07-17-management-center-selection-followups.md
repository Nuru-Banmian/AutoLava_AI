# Management Center Selection Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make both management pages select their first available record on entry, simplify their mobile selectors, and apply the approved card and action ordering.

**Architecture:** Keep selection owned by `StoreWorkspace` and `UsersPanel`. Each component records whether its first successful query result has been handled, commits the first ID only when the live selection is still `null`, and represents create mode with a hidden empty `<option>` rather than a selectable prompt. No API, query-key, editor contract, or backend behavior changes.

**Tech Stack:** React 19, TypeScript, TanStack Query, Tailwind CSS, Vitest, Testing Library, MSW, Vite

## Global Constraints

- Automatic selection runs once after the relevant query first succeeds and must not overwrite an existing ID or the `new` state.
- The mobile selectors must list existing records only; hidden empty options may represent create mode or an empty list but cannot be user-selectable.
- Preserve all existing unsaved-change guards, dirty-state handling, request lifecycle protections, authorization rules, create/save/delete behavior, and desktop sidebars.
- No backend or API changes are allowed.
- Do not stage or commit the user's unrelated modified or untracked files.

---

## File Map

- `frontend/src/admin/StoreWorkspace.tsx`: owns store selection, store mobile controls, and store/income card order.
- `frontend/src/admin/StoreWorkspace.test.tsx`: verifies default store selection, selector contents/create state, empty-list behavior, and card order.
- `frontend/src/admin/UsersPanel.tsx`: owns user selection and the responsive selector/create-button row.
- `frontend/src/admin/UsersPanel.test.tsx`: verifies default user selection, selector contents/create state, empty-list behavior, responsive control structure, and post-create selection.
- `frontend/src/admin/UserEditor.tsx`: owns the edit/create footer action ordering.

### Task 1: Store selection, selector, and card order

**Files:**
- Modify: `frontend/src/admin/StoreWorkspace.test.tsx`
- Modify: `frontend/src/admin/StoreWorkspace.tsx`

**Interfaces:**
- Consumes: existing `StoreSelection = number | "new" | null`, `commitSelection(next)`, `stores.isSuccess`, and `stores.data`.
- Produces: one-time first-store initialization and a mobile `<select aria-label="门店">` whose value is the selected store ID or an internal empty value.

- [ ] **Step 1: Add failing behavior tests**

Add these focused tests near the first `StoreWorkspace` test. They intentionally avoid clicking the Roma rail item so they prove real automatic selection:

```tsx
it("selects the first store on initial load and renders income before details", async () => {
  mockStoreWorkspace({ stores: [roma, milano] });
  renderWorkspace();

  expect(await screen.findByLabelText("门店名称 Roma")).toBeInTheDocument();
  const income = screen.getByRole("region", { name: "收入项目" });
  const details = screen.getByRole("region", { name: "门店资料" });
  expect(income.compareDocumentPosition(details) & Node.DOCUMENT_POSITION_FOLLOWING)
    .toBeTruthy();

  const selector = screen.getByRole("combobox", { name: "门店" });
  expect(selector).toHaveValue("9");
  expect(within(selector).queryByRole("option", { name: "请选择门店" }))
    .not.toBeInTheDocument();
  expect(screen.queryByText("请选择门店")).not.toBeInTheDocument();
});

it("keeps the store selector blank in create mode without a selectable prompt", async () => {
  mockStoreWorkspace({ stores: [roma] });
  renderWorkspace();
  await screen.findByLabelText("门店名称 Roma");

  await userEvent.click(screen.getByRole("button", { name: "新建门店" }));

  expect(screen.getByRole("combobox", { name: "门店" })).toHaveValue("");
  expect(screen.queryByRole("option", { name: "请选择门店" })).not.toBeInTheDocument();
  expect(screen.getByLabelText("门店名称")).toBeInTheDocument();
});

it("does not invent a store selection for an empty list", async () => {
  mockStoreWorkspace({ stores: [] });
  renderWorkspace();

  const selector = await screen.findByRole("combobox", { name: "门店" });
  expect(selector).toHaveValue("");
  expect(screen.queryByText("请选择门店")).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "门店资料" })).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "收入项目" })).not.toBeInTheDocument();
});

it("selects a newly created store", async () => {
  let stores = [roma];
  mockStoreWorkspace();
  server.use(
    http.get("/api/admin/stores", () => HttpResponse.json(stores)),
    http.post("/api/admin/stores", () => {
      stores = [roma, milano];
      return HttpResponse.json(milano, { status: 201 });
    }),
  );
  renderWorkspace();
  await screen.findByLabelText("门店名称 Roma");
  await userEvent.click(screen.getByRole("button", { name: "新建门店" }));
  await userEvent.type(screen.getByLabelText("门店名称"), "Milano");
  await userEvent.click(screen.getByRole("button", { name: "打开地图选择" }));
  await userEvent.click(screen.getByRole("button", { name: "添加门店" }));

  expect(await screen.findByLabelText("门店名称 Milano")).toBeInTheDocument();
  expect(screen.getByRole("combobox", { name: "门店" })).toHaveValue("10");
});
```

- [ ] **Step 2: Run the focused tests and verify the expected failures**

Run:

```powershell
cd frontend
npm test -- src/admin/StoreWorkspace.test.tsx
```

Expected: the new tests fail because Roma is not selected automatically, `请选择门店` is still rendered, and `门店资料` currently precedes `收入项目`.

- [ ] **Step 3: Implement one-time store initialization and the approved rendering**

In `StoreWorkspace`, add an initialization ref alongside `selectionRef` and handle the first successful query without calling the guarded user-transition path:

```tsx
const [selection, setSelection] = useState<StoreSelection>(null);
const selectionRef = useRef<StoreSelection>(null);
const initializedSelectionRef = useRef(false);

useEffect(() => {
  if (!stores.isSuccess || initializedSelectionRef.current) return;
  initializedSelectionRef.current = true;
  if (selectionRef.current === null && list[0]) commitSelection(list[0].id);
}, [list, stores.isSuccess]);
```

Replace the prompt default with `null`, put `IncomeItemsPanel` before `StoreDetailsCard`, and keep the existing callbacks unchanged:

```tsx
let cards: React.ReactNode = null;
cards = <div className="space-y-4">
  <IncomeItemsPanel
    key={`income-${selection}`}
    onDirtyChange={updateIncomeDirty}
    storeId={selectedStore.id}
  />
  <StoreDetailsCard
    key={`details-${selection}`}
    mode="edit"
    onDeleted={(storeId) => {
      if (selectionRef.current === capturedStoreId) deleted(storeId);
    }}
    onDeleteRequested={(deleteStore) => {
      if (selectionRef.current !== capturedStoreId) return;
      requestTransition(() => {
        if (selectionRef.current === capturedStoreId) deleteStore();
      });
    }}
    onDeleteFailed={() => {
      if (selectionRef.current === capturedStoreId && (detailsDirtyRef.current || incomeDirtyRef.current)) markDirty(true);
    }}
    onDirtyChange={updateDetailsDirty}
    onSaved={() => {
      if (selectionRef.current === capturedStoreId) updateDetailsDirty(false);
    }}
    store={selectedStore}
  />
</div>;
```

Change the mobile selector to an internal hidden empty value and existing-store options only:

```tsx
<select
  aria-label="门店"
  className="h-9 min-w-0 flex-1 rounded-md border bg-background px-2 md:hidden"
  onChange={(event) => {
    if (event.target.value) select(Number(event.target.value));
  }}
  value={typeof selection === "number" ? selection : ""}
>
  <option hidden value="" />
  {list.map((store) => <option key={store.id} value={store.id}>{store.name}</option>)}
</select>
```

- [ ] **Step 4: Run the store component tests**

Run:

```powershell
cd frontend
npm test -- src/admin/StoreWorkspace.test.tsx
```

Expected: all `StoreWorkspace.test.tsx` tests pass, including the pre-existing stale-request, dirty-state, deletion, and independent-save tests.

- [ ] **Step 5: Commit the store task**

```powershell
git add -- frontend/src/admin/StoreWorkspace.tsx frontend/src/admin/StoreWorkspace.test.tsx
git commit -m "feat: initialize management store selection"
```

### Task 2: User selection, responsive controls, and footer order

**Files:**
- Modify: `frontend/src/admin/UsersPanel.test.tsx`
- Modify: `frontend/src/admin/UsersPanel.tsx`
- Modify: `frontend/src/admin/UserEditor.tsx`

**Interfaces:**
- Consumes: existing `UserSelection = number | "new" | null`, `commitSelection(next)`, `select(next)`, `users.isSuccess`, and the `UserEditor` props.
- Produces: one-time first-user initialization, `data-testid="user-panel-controls"` for the mobile control row, an existing-users-only selector, and edit actions ordered destructive-first/save-second.

- [ ] **Step 1: Add and update failing user tests**

Add these tests after `renderPanel()` helpers:

```tsx
it("selects the first user and exposes only existing users in the selector", async () => {
  mockUsers([maria, operator]);
  renderPanel();

  expect(await screen.findByRole("heading", { name: "编辑 maria" })).toBeInTheDocument();
  const selector = screen.getByRole("combobox", { name: "用户" });
  expect(selector).toHaveValue("2");
  expect(within(selector).getAllByRole("option").map((option) => option.textContent))
    .toEqual(["maria", "operator"]);
  expect(screen.queryByText("请选择用户", { selector: "p" })).not.toBeInTheDocument();
});

it("keeps user controls on one row and leaves the selector blank in create mode", async () => {
  mockUsers([maria]);
  renderPanel();
  await screen.findByRole("heading", { name: "编辑 maria" });

  const controls = screen.getByTestId("user-panel-controls");
  expect(controls).toHaveClass("flex", "items-center");
  expect(within(controls).getByRole("combobox", { name: "用户" })).toBeInTheDocument();
  await userEvent.click(within(controls).getByRole("button", { name: "新建用户" }));

  const selector = within(controls).getByRole("combobox", { name: "用户" });
  expect(selector).toHaveValue("");
  expect(within(selector).queryByRole("option", { name: "新建用户" }))
    .not.toBeInTheDocument();
  expect(within(selector).queryByRole("option", { name: "请选择用户" }))
    .not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "添加用户" })).toBeInTheDocument();
});

it("does not invent a user selection for an empty list", async () => {
  mockUsers([]);
  renderPanel();

  const selector = await screen.findByRole("combobox", { name: "用户" });
  expect(selector).toHaveValue("");
  expect(screen.queryByText("请选择用户", { selector: "p" })).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: /^编辑 / })).not.toBeInTheDocument();
});

it("selects a newly created user", async () => {
  const created = { id: 10, username: "new-operator", role: "user" as const,
    is_active: true, store_ids: [9] };
  let users = [maria];
  server.use(
    http.get("/api/admin/users", () => HttpResponse.json(users)),
    http.get("/api/admin/stores", () => HttpResponse.json([roma])),
    http.post("/api/admin/users", () => {
      users = [maria, created];
      return HttpResponse.json(created, { status: 201 });
    }),
  );
  renderPanel();
  await screen.findByRole("heading", { name: "编辑 maria" });
  await userEvent.click(screen.getByRole("button", { name: "新建用户" }));
  await userEvent.type(screen.getByLabelText("用户名"), "new-operator");
  await userEvent.type(screen.getByLabelText("初始密码"), "operator123");
  await userEvent.click(screen.getByRole("checkbox", { name: "Roma" }));
  await userEvent.click(screen.getByRole("button", { name: "添加用户" }));

  expect(await screen.findByRole("heading", { name: "编辑 new-operator" })).toBeInTheDocument();
  expect(screen.getByRole("combobox", { name: "用户" })).toHaveValue("10");
});
```

Update the existing owner-edit footer assertion from:

```tsx
.toEqual(["保存用户", "永久删除"]);
```

to:

```tsx
.toEqual(["永久删除", "保存用户"]);
```

Update `clears a dirty selection when the authoritative refetch removes it` so its post-refetch assertion matches the removed prompt:

```tsx
await waitFor(() => {
  expect(screen.queryByRole("heading", { name: "编辑 maria" })).not.toBeInTheDocument();
});
expect(screen.queryByText("请选择用户", { selector: "p" })).not.toBeInTheDocument();
```

- [ ] **Step 2: Run the focused tests and verify the expected failures**

Run:

```powershell
cd frontend
npm test -- src/admin/UsersPanel.test.tsx
```

Expected: failures show that there is no automatic user selection, the two old selector entries and prompt remain, the controls are split across rows, and footer actions are reversed from the approved order.

- [ ] **Step 3: Implement user initialization and the unified control row**

In `UsersPanel`, add a one-time initialization ref and effect. Keep the existing authoritative-removal effect separate so later refetches cannot restart initialization:

```tsx
const [selection, setSelection] = useState<UserSelection>(null);
const selectionRef = useRef<UserSelection>(selection);
const initializedSelectionRef = useRef(false);

useEffect(() => {
  if (!users.isSuccess || initializedSelectionRef.current) return;
  initializedSelectionRef.current = true;
  if (selectionRef.current === null && users.data[0]) commitSelection(users.data[0].id);
}, [users.data, users.isSuccess]);
```

Replace the `请选择用户` editor fallback with no rendered prompt:

```tsx
} else if (!selectedUser) {
  editor = null;
```

Replace the separate button row and mobile label with this single control row:

```tsx
<div className="flex items-center gap-2" data-testid="user-panel-controls">
  <label className="min-w-0 flex-1 md:hidden">
    <span className="sr-only">用户</span>
    <select
      aria-label="用户"
      className="h-9 w-full rounded-md border bg-background px-2"
      onChange={(event) => {
        if (event.target.value) select(Number(event.target.value));
      }}
      value={typeof selection === "number" ? selection : ""}
    >
      <option hidden value="" />
      {list.map((user) => <option key={user.id} value={user.id}>{user.username}</option>)}
    </select>
  </label>
  <Button className="ml-auto" onClick={() => select("new")} type="button">
    新建用户
  </Button>
</div>
```

Do not change `createUser.onSuccess`: its existing `commitSelection(created.id)` is the required post-create selection and must remain protected by its current request identity and mounted-target checks.

- [ ] **Step 4: Swap the edit footer actions without changing their behavior**

In `UserEditor`, move the complete existing `AlertDialog` block before the submit button. The resulting footer structure is:

```tsx
<div className="flex items-center justify-between gap-3" data-testid="user-editor-actions">
  {mode === "edit" && onDelete && <AlertDialog>
    <AlertDialogTrigger asChild>
      <Button disabled={pending} type="button" variant="destructive">永久删除</Button>
    </AlertDialogTrigger>
    <AlertDialogContent>
      <AlertDialogHeader>
        <AlertDialogTitle>永久删除用户？</AlertDialogTitle>
        <AlertDialogDescription>此操作不可恢复。确定要永久删除“{user?.username}”吗？</AlertDialogDescription>
      </AlertDialogHeader>
      <AlertDialogFooter>
        <AlertDialogCancel>取消</AlertDialogCancel>
        <AlertDialogAction onClick={() => { if (!pending) onDelete(); }}>
          确认永久删除
        </AlertDialogAction>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>}
  <Button disabled={pending} type="submit">
    {mode === "create" ? "添加用户" : "保存用户"}
  </Button>
</div>
```

This keeps create mode to one `添加用户` button while edit mode renders `永久删除` left and `保存用户` right.

- [ ] **Step 5: Run the user component tests**

Run:

```powershell
cd frontend
npm test -- src/admin/UsersPanel.test.tsx
```

Expected: all `UsersPanel.test.tsx` tests pass, including authorization, dirty navigation, stale request, unmount, save, and delete-confirmation coverage.

- [ ] **Step 6: Commit the user task**

```powershell
git add -- frontend/src/admin/UsersPanel.tsx frontend/src/admin/UsersPanel.test.tsx frontend/src/admin/UserEditor.tsx
git commit -m "feat: initialize management user selection"
```

### Task 3: Frontend regression verification

**Files:**
- Verify only; no source files should change.

**Interfaces:**
- Consumes: the completed store and user component behavior from Tasks 1 and 2.
- Produces: test and production-build evidence for completion.

- [ ] **Step 1: Run both focused suites together**

```powershell
cd frontend
npm test -- src/admin/StoreWorkspace.test.tsx src/admin/UsersPanel.test.tsx
```

Expected: both files pass with zero failed tests.

- [ ] **Step 2: Run the entire frontend unit suite**

```powershell
cd frontend
npm test
```

Expected: every Vitest file passes with zero failed tests.

- [ ] **Step 3: Build the production frontend**

```powershell
cd frontend
npm run build
```

Expected: TypeScript compilation and Vite production build exit successfully. The existing Vite large-chunk advisory is acceptable; new errors are not.

- [ ] **Step 4: Confirm the branch contains only intended commits and preserved user changes**

```powershell
git status --short
git log --oneline -5
```

Expected: the two implementation commits are present; the user's pre-existing modified/untracked files remain unstaged and unchanged; no implementation files remain modified.
