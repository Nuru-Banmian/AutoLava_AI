# Issues 15–17 Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a clean integration branch containing only the completed frontend behavior for GitHub Issues #15, #16, and #17, verify it, and unblock Issue #18.

**Architecture:** Preserve the original mixed commit on `codex/issue17`. Start a new integration branch from `main`, copy only the frontend paths belonging to the three tickets from commit `01405c0`, and exclude unrelated deployment documentation and redundant per-agent plan files.

**Tech Stack:** Git, React, TypeScript, Vitest, Testing Library, Vite, GitHub CLI.

## Global Constraints

- Do not rewrite or delete commit `01405c0` or its branch.
- Do not include `README.md`, `docs/deployment.md`, or the two per-agent plan files from `01405c0` in the feature integration commit.
- Keep the backend contract unchanged.
- Close Issues #15–#17 only after focused tests, the complete frontend suite, TypeScript checking, and the production build pass.

---

### Task 1: Build the scoped integration branch

**Files:**
- Create: `docs/superpowers/plans/2026-07-19-integrate-issues-15-17.md`
- Modify: frontend files changed by commit `01405c0`

**Interfaces:**
- Consumes: completed implementation in commit `01405c0` and baseline branch `main`.
- Produces: branch `codex/integrate-issues-15-17` containing only the frontend behavior for Issues #15–#17.

- [ ] **Step 1: Create the integration branch from main**

Run: `git switch -c codex/integrate-issues-15-17 main`

Expected: the new branch points at `a79da19` before integration changes are committed.

- [ ] **Step 2: Restore only the ticket-related frontend paths from the mixed commit**

Run: `git restore --source 01405c0 -- frontend/src/components/BusinessAnalysisCard.test.tsx frontend/src/components/BusinessAnalysisCard.tsx frontend/src/components/DeleteRecordDialog.test.tsx frontend/src/components/DeleteRecordDialog.tsx frontend/src/components/IncomeComposition.test.tsx frontend/src/components/IncomeComposition.tsx frontend/src/components/MobileRecordSheet.test.tsx frontend/src/components/MobileRecordSheet.tsx frontend/src/components/RecordDetailPanel.test.tsx frontend/src/components/RecordDetailPanel.tsx frontend/src/components/RecordManagementDialogs.test.tsx frontend/src/components/RecordManagementDialogs.tsx frontend/src/navigation/business-records-return.ts frontend/src/pages/BusinessRecordsPage.test.tsx frontend/src/pages/BusinessRecordsPage.tsx frontend/src/pages/LedgerPage.test.tsx frontend/src/pages/LedgerPage.tsx`

Expected: the intended additions, modifications, and deletions appear in the working tree; deployment documentation does not.

- [ ] **Step 3: Inspect the scoped diff**

Run: `git status --short; git diff --stat; git diff --check`

Expected: only this integration plan and the listed frontend paths appear, with no whitespace errors.

### Task 2: Verify the integrated behavior

**Files:**
- Test: `frontend/src/pages/BusinessRecordsPage.test.tsx`
- Test: `frontend/src/pages/LedgerPage.test.tsx`
- Test: `frontend/src/components/DeleteRecordDialog.test.tsx`
- Test: `frontend/src/components/RecordDetailPanel.test.tsx`
- Test: `frontend/src/components/BusinessAnalysisCard.test.tsx`
- Test: `frontend/src/components/IncomeComposition.test.tsx`

**Interfaces:**
- Consumes: the scoped working-tree implementation.
- Produces: evidence that all three ticket slices work together and the production bundle remains valid.

- [ ] **Step 1: Run focused tests**

Run: `cd frontend; npm test -- src/pages/BusinessRecordsPage.test.tsx src/pages/LedgerPage.test.tsx src/components/DeleteRecordDialog.test.tsx src/components/RecordDetailPanel.test.tsx src/components/BusinessAnalysisCard.test.tsx src/components/IncomeComposition.test.tsx`

Expected: all focused tests pass.

- [ ] **Step 2: Run TypeScript checking**

Run: `cd frontend; npx tsc -b --pretty false`

Expected: exit code 0.

- [ ] **Step 3: Run the complete frontend suite**

Run: `cd frontend; npm test`

Expected: all tests pass.

- [ ] **Step 4: Run the production build**

Run: `cd frontend; npm run build`

Expected: TypeScript and Vite finish with exit code 0.

### Task 3: Commit and unblock final verification

**Files:**
- Commit: the integration plan and scoped frontend changes.

**Interfaces:**
- Consumes: verified integration diff.
- Produces: one clean integration commit and three closed prerequisite Issues, making Issue #18 ready.

- [ ] **Step 1: Commit the verified integration**

Run: `git add docs/superpowers/plans/2026-07-19-integrate-issues-15-17.md frontend/src; git commit -m "feat: integrate business records workflow improvements"`

Expected: the commit succeeds and the working tree is clean.

- [ ] **Step 2: Close the completed prerequisite Issues**

Run: `gh issue close 15 --comment "Implemented and verified on the integration branch."`, then repeat for #16 and #17.

Expected: Issues #15–#17 are closed.

- [ ] **Step 3: Verify Issue #18 is unblocked**

Run: `gh api repos/Nuru-Banmian/AutoLava_AI/issues/18 --jq '{state,issue_dependencies_summary}'`

Expected: `issue_dependencies_summary.blocked_by` is `0` and Issue #18 remains open.
