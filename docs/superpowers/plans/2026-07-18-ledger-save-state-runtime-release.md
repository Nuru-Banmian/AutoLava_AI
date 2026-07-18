# Ledger Save State and Runtime Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make successful ledger saves stop stale unsaved-change prompts, preserve edits made during an in-flight save, render blue markers for every non-selected recorded date, and deploy a verifiably rebuilt runtime.

**Architecture:** Keep form-value ownership and signature comparison inside `LedgerForm`, but make acceptance of a saved submission an explicit callback that the page can use as the user-visible save-complete boundary. Keep month markers driven by the existing store/month query and limit the visual dot to recorded dates that are not selected. Embed the Git revision in the Docker image and a static `version.json` so deployment verifies the running artifact rather than only server-side source files.

**Tech Stack:** React 19, TypeScript, TanStack Query, React Router, Vitest, Testing Library, FastAPI deployment-contract tests, Docker Compose, Nginx.

## Global Constraints

- Continue release work on the retained `test-used` branch and update the existing PR.
- A successful save clears the unsaved guard only when the current form still equals the submitted body.
- Edits made while a save is in flight remain dirty and must not be overwritten.
- Every non-selected recorded date shows a blue dot; selected recorded dates use the existing selected background and accessible “已有记录” label.
- Do not change ledger data, date disabling, store authorization, or the overall date-picker layout.
- Preserve server `.env`, `backups/`, and the `autolava_mysql_data` volume.
- Production verification uses `https://nuru-banmian.cn`, not public port 8080.

---

### Task 1: Make saved-baseline acceptance explicit

**Files:**
- Modify: `frontend/src/components/LedgerForm.tsx`
- Modify: `frontend/src/pages/LedgerPage.tsx`
- Test: `frontend/src/pages/LedgerPage.test.tsx`

**Interfaces:**
- Consumes: existing `savedSubmission?: { revision: number; body: LedgerBody; canonicalReady?: boolean }` and semantic/submitted signatures in `LedgerForm`.
- Produces: optional `onSavedSubmissionApplied?(revision: number): void`, called only when the current semantic signature equals the submitted signature; `LedgerPage` treats this callback as the point at which “保存成功” may be shown.

- [ ] **Step 1: Write failing form and page regression tests**

Add a test that rerenders `LedgerForm` with a saved submission and asserts callback ordering:

```tsx
it("accepts a saved submission only after the form is clean", async () => {
  const events: string[] = [];
  const props = {
    config: { store_id: 1, version_id: null, version: 0, enabled: false, formula: "", created_at: null, items: [] },
    categories: [],
    onSave: vi.fn(),
    onDirtyChange: (dirty: boolean) => events.push(`dirty:${dirty}`),
    onSavedSubmissionApplied: (revision: number) => events.push(`saved:${revision}`),
  };
  const view = render(<LedgerForm {...props} />);
  fireEvent.change(screen.getByLabelText("当日营业额"), { target: { value: "66" } });
  view.rerender(<LedgerForm {...props} savedSubmission={{ revision: 1, body: {
    is_open: "营业", daily_revenue: "66.00", config_version_id: null,
    expected_version: null, wash_count: null, weather: null,
    weather_edited: false, activity: null, items: [],
  } }} />);

  await waitFor(() => expect(events.slice(-2)).toEqual(["dirty:false", "saved:1"]));
});
```

Add an integration test in which the save succeeds, “保存成功” becomes visible, and selecting a different recorded date does not open the unsaved dialog:

```tsx
it("changes date without a warning after the saved baseline is applied", async () => {
  renderLedger([
    http.get("/api/database/1/records", ({ request }) =>
      new URL(request.url).searchParams.get("page_size") === "200"
        ? HttpResponse.json({ items: [{ id: 8, date: "2026-07-13" }], categories: [], sum_daily_revenue: "0.00", total: 1, page: 1, page_size: 200 })
        : HttpResponse.json({ items: [], categories: [], sum_daily_revenue: "0.00", total: 0, page: 1, page_size: 1 })),
    http.put("/api/ledger/1/:date", () => HttpResponse.json(recordSnapshot("66.00"))),
  ]);
  fireEvent.change(await screen.findByLabelText("现金"), { target: { value: "66" } });
  fireEvent.click(screen.getByRole("button", { name: "保存今日记录" }));
  expect(await screen.findByRole("status")).toHaveTextContent("保存成功");
  fireEvent.click(screen.getByRole("button", { name: "选择台账日期：2026年7月15日" }));
  fireEvent.click(await screen.findByRole("button", { name: "2026年7月13日，已有记录" }));
  expect(screen.queryByRole("alertdialog", { name: "放弃未保存的修改？" })).not.toBeInTheDocument();
});
```

Keep the existing test `keeps edits made while a save is pending after success and record refetch`; extend it to attempt a date change and assert the warning remains.

- [ ] **Step 2: Run the focused tests and verify RED**

Run from `frontend/` as:

```powershell
npm test -- --run src/pages/LedgerPage.test.tsx
```

Expected: FAIL because `onSavedSubmissionApplied` is not part of `LedgerFormProps` and save success is currently exposed directly from the mutation callback.

- [ ] **Step 3: Implement saved-baseline acknowledgement**

In `LedgerForm.tsx`, import `useLayoutEffect`, add the callback prop, and replace the dirty notification effect with an ordered layout effect:

```tsx
onDirtyChange?(dirty: boolean): void;
onSavedSubmissionApplied?(revision: number): void;

useLayoutEffect(() => {
  const dirty = currentSignature !== effectiveBaselineSignature;
  onDirtyChange?.(dirty);
  if (!dirty && pendingSavedSubmission) {
    onSavedSubmissionApplied?.(pendingSavedSubmission.revision);
  }
}, [currentSignature, effectiveBaselineSignature, onDirtyChange, onSavedSubmissionApplied, pendingSavedSubmission]);
```

Remove the old `useEffect(() => onDirtyChange(...))` call. Do not acknowledge when signatures differ; this preserves edits made while the request was pending.

In `LedgerPage.tsx`, remove `setMessage("保存成功")` from the mutation `onSuccess` block. Pass an acknowledgement callback to `LedgerForm`:

```tsx
onSavedSubmissionApplied={(revision) => {
  if (currentSavedSubmission?.revision === revision) setMessage("保存成功");
}}
```

Keep error/conflict messages unchanged.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
npm test -- --run src/pages/LedgerPage.test.tsx src/navigation/UnsavedChanges.test.tsx
```

Expected: all selected files pass; successful saves expose “保存成功” only after the dirty callback reports `false`, while in-flight edits remain protected.

- [ ] **Step 5: Commit the save-state fix**

```powershell
git add -- frontend/src/components/LedgerForm.tsx frontend/src/pages/LedgerPage.tsx frontend/src/pages/LedgerPage.test.tsx
git commit -m "fix: clear ledger guard after saved baseline"
```

---

### Task 2: Lock the non-selected monthly marker contract

**Files:**
- Modify: `frontend/src/components/MonthCalendar.tsx`
- Test: `frontend/src/components/MonthCalendar.test.tsx`
- Test: `frontend/src/pages/LedgerPage.test.tsx`

**Interfaces:**
- Consumes: `recordedDates: ReadonlySet<string>` and the existing month query at `ledgerMonthKey(storeId, month)`.
- Produces: `span[data-testid="recorded-date-dot"]` only for `recorded && iso !== selected`, with `bg-primary`; accessible date labels continue to include “已有记录” for both selected and non-selected recorded dates.

- [ ] **Step 1: Write failing visual-contract tests**

Replace the single-date marker assertion with multiple recorded dates and explicit dot assertions:

```tsx
render(<MonthCalendar
  month="2026-04"
  selected="2026-04-30"
  today="2026-07-18"
  recordedDates={new Set(["2026-04-26", "2026-04-27", "2026-04-28", "2026-04-30"])}
  onSelect={onSelect}
/>);

for (const day of [26, 27, 28]) {
  const button = screen.getByRole("button", { name: `2026年4月${day}日，已有记录` });
  expect(button).toHaveAttribute("data-recorded", "true");
  expect(button.querySelector('[data-testid="recorded-date-dot"]')).toHaveClass("bg-primary");
}
const selected = screen.getByRole("button", { name: "2026年4月30日，已有记录" });
expect(selected.querySelector('[data-testid="recorded-date-dot"]')).toBeNull();
```

In `LedgerPage.test.tsx`, make the month API return April 26, 27, 28, and 30, then assert all four accessible names are present after opening April.

- [ ] **Step 2: Run marker tests and verify RED**

Run:

```powershell
npm test -- --run src/components/MonthCalendar.test.tsx src/pages/LedgerPage.test.tsx
```

Expected: FAIL because the dot has no stable test identifier and the selected recorded date still renders a white dot.

- [ ] **Step 3: Implement the exact marker rule**

Change the marker rendering in `MonthCalendar.tsx` to:

```tsx
{recorded && iso !== selected && (
  <span
    aria-hidden="true"
    data-testid="recorded-date-dot"
    className="absolute bottom-1 size-1 rounded-full bg-primary"
  />
)}
```

Keep `data-recorded` and the accessible “已有记录” suffix on selected dates.

- [ ] **Step 4: Run marker and month-query tests**

Run:

```powershell
npm test -- --run src/components/MonthCalendar.test.tsx src/pages/LedgerPage.test.tsx src/lib/user-api.test.ts
```

Expected: PASS, including all April recorded dates and store/month query isolation.

- [ ] **Step 5: Commit the marker contract**

```powershell
git add -- frontend/src/components/MonthCalendar.tsx frontend/src/components/MonthCalendar.test.tsx frontend/src/pages/LedgerPage.test.tsx
git commit -m "test: lock ledger monthly record markers"
```

---

### Task 3: Embed and test the runtime Git revision

**Files:**
- Modify: `frontend/Dockerfile`
- Modify: `compose.yaml`
- Modify: `backend/tests/test_deployment_config.py`

**Interfaces:**
- Consumes: Compose environment variable `AUTOLAVA_GIT_SHA`, defaulting to `unknown` for local builds.
- Produces: OCI image label `org.opencontainers.image.revision` and `/version.json` containing `{ "git_sha": "<revision>" }` in the running Web container.

- [ ] **Step 1: Write failing deployment-contract tests**

Add assertions to `backend/tests/test_deployment_config.py`:

```python
def test_web_image_embeds_release_revision() -> None:
    dockerfile = (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))

    assert "ARG AUTOLAVA_GIT_SHA=unknown" in dockerfile
    assert "org.opencontainers.image.revision" in dockerfile
    assert "/app/dist/version.json" in dockerfile
    assert compose["services"]["autolava-web"]["build"]["args"]["AUTOLAVA_GIT_SHA"] == "${AUTOLAVA_GIT_SHA:-unknown}"
```

- [ ] **Step 2: Run the deployment test and verify RED**

Run from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_deployment_config.py -q
```

Expected: FAIL because the Dockerfile and Compose build currently have no revision contract.

- [ ] **Step 3: Add the revision to the Web build and image**

Change the Web service build block in `compose.yaml`:

```yaml
autolava-web:
  build:
    context: ./frontend
    args:
      AUTOLAVA_GIT_SHA: ${AUTOLAVA_GIT_SHA:-unknown}
```

Update `frontend/Dockerfile`:

```dockerfile
FROM docker.m.daocloud.io/library/node:22-alpine AS build
ARG AUTOLAVA_GIT_SHA=unknown

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm config set registry https://registry.npmmirror.com && npm ci
COPY . .
RUN npm run build
RUN printf '{"git_sha":"%s"}\n' "$AUTOLAVA_GIT_SHA" > /app/dist/version.json

FROM docker.m.daocloud.io/library/nginx:1.27-alpine
ARG AUTOLAVA_GIT_SHA=unknown
LABEL org.opencontainers.image.revision=$AUTOLAVA_GIT_SHA
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
```

- [ ] **Step 4: Run deployment-contract tests and a local Web image build**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_deployment_config.py -q
docker build --build-arg AUTOLAVA_GIT_SHA=plan-verification -t autolava-web:plan-verification ..\frontend
docker image inspect autolava-web:plan-verification --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}'
```

Expected: tests pass and inspect prints `plan-verification`.

- [ ] **Step 5: Commit the runtime-version contract**

```powershell
git add -- frontend/Dockerfile compose.yaml backend/tests/test_deployment_config.py
git commit -m "build: identify deployed web revision"
```

---

### Task 4: Release verification, PR update, and server rebuild

**Files:**
- Verify only: frontend and backend suites
- Update through Git: retained `test-used` branch and existing PR #6
- Deploy to: `root@116.62.112.245:/opt/autolava`

**Interfaces:**
- Consumes: clean committed `test-used`, Docker revision contract from Task 3, existing `.env`, Compose files, backup script, and MySQL volume.
- Produces: pushed PR head and running containers whose Web image revision equals the deployed `test-used` commit.

- [ ] **Step 1: Run the complete local release gate**

Frontend:

```powershell
cd frontend
npm test
npm run build
```

Backend: load `AUTOLAVA_DATABASE_URL` from the local secret file, verify the database name is exactly `autolava_test`, then run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

Expected: all frontend tests pass, Vite production build succeeds, and all backend tests pass. The existing Starlette deprecation and Vite chunk-size warnings are non-blocking.

- [ ] **Step 2: Confirm the branch diff and push the PR update**

```powershell
git diff --check
git status --short
git log --oneline origin/test-used..test-used
git push origin test-used
```

Expected: only known pre-existing unrelated worktree files remain unstaged; the new commits push successfully to PR #6.

- [ ] **Step 3: Back up production and record the target revision**

```powershell
$releaseSha = git rev-parse HEAD
ssh root@116.62.112.245 'set -eu; cd /opt/autolava; ./scripts/backup-production-db.sh; test -d backups; docker volume inspect autolava_autolava_mysql_data >/dev/null'
```

Expected: a new non-empty `.sql.gz` backup exists and the production data volume is present.

- [ ] **Step 4: Upload the committed release without touching server state files**

Create the archive from `HEAD`, upload it, and extract it into `/opt/autolava` while retaining `.env` and `backups/`:

```powershell
git archive --format=tar --output "$env:TEMP\autolava-test-used.tar" HEAD
scp "$env:TEMP\autolava-test-used.tar" root@116.62.112.245:/tmp/autolava-test-used.tar
ssh root@116.62.112.245 'set -eu; test -f /opt/autolava/.env; test -d /opt/autolava/backups; tar -xf /tmp/autolava-test-used.tar -C /opt/autolava; rm -f /tmp/autolava-test-used.tar; test -f /opt/autolava/.env; test -d /opt/autolava/backups'
```

Expected: committed files update, secrets/backups remain, and no Docker volume is removed.

- [ ] **Step 5: Rebuild Web/API images with the target revision**

```powershell
ssh root@116.62.112.245 "set -eu; cd /opt/autolava; AUTOLAVA_GIT_SHA=$releaseSha docker compose -f compose.yaml -f compose.temporary.yaml build --no-cache autolava-web; AUTOLAVA_GIT_SHA=$releaseSha docker compose -f compose.yaml -f compose.temporary.yaml build autolava-api; AUTOLAVA_GIT_SHA=$releaseSha docker compose -f compose.yaml -f compose.temporary.yaml up -d; docker compose -f compose.yaml -f compose.temporary.yaml ps"
```

Expected: the Web build completes rather than merely restarting the old image; API, Web, and DB are Up, with DB healthy.

- [ ] **Step 6: Verify the running artifact and health endpoint**

```powershell
ssh root@116.62.112.245 "set -eu; web_id=\$(docker compose -f /opt/autolava/compose.yaml -f /opt/autolava/compose.temporary.yaml ps -q autolava-web); test \"\$(docker inspect -f '{{ index .Config.Labels \"org.opencontainers.image.revision\" }}' \$web_id)\" = '$releaseSha'; docker exec \$web_id cat /usr/share/nginx/html/version.json; curl --fail --silent --show-error http://127.0.0.1:8080/health"
curl.exe --fail --silent --show-error https://nuru-banmian.cn/health
```

Expected: image label and `version.json` equal `$releaseSha`; both health checks return `{ "status": "ok" }`.

- [ ] **Step 7: Verify the real April markers without changing production data**

Using the authenticated production UI:

1. Select `sulmona` and open `/ledger?date=2026-04-30`.
2. Open the calendar and assert 2026-04-26, 27, and 28 have `data-recorded="true"` plus a blue dot; 30 has the selected styling and accessible “已有记录” label.
3. Select April 28 and confirm the saved `613.00` data autofills.
4. Do not edit or save any production ledger field. Rely on Task 1's automated tests for clean-save navigation and in-flight edit protection.

Expected: production monthly markers and autofill match the approved spec without writing ledger data; local automated tests prove clean-save navigation and in-flight edit protection.

- [ ] **Step 8: Record final evidence**

```powershell
git status --short
git rev-parse HEAD
git rev-parse origin/test-used
```

Expected: branch and remote revision match; unrelated pre-existing worktree changes remain untouched. Report test totals, PR URL, deployed SHA, backup filename, image label, health result, and April UI verification.
