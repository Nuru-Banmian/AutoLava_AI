# 营业记录状态纯文字与发布 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 移除营业记录表格和详情卡片状态文字前的圆点，保留 `test-used` 分支，将成果本地合并至 `main`、创建 PR，并无损更新临时服务器。

**Architecture:** UI 只删除 `RecordTable` 与 `RecordDetailPanel` 中的装饰圆点元素，不改变状态数据或交互。Git 交付在验证后将当前分支改名为 `test-used`，本地合并但不推送 `main`，通过推送 `test-used` 创建 PR。服务器从本地 `main` 生成无密钥 Git 归档，覆盖 `/opt/autolava` 中的版本文件，同时保留 `.env`、备份目录和 Docker 数据卷。

**Tech Stack:** React、TypeScript、Testing Library、Vitest、Vite、Git、GitHub CLI、SSH、Docker Compose。

## Global Constraints

- 桌面营业记录表格和右侧详情卡片仅显示状态文字，不保留隐藏圆点元素。
- 移动端状态显示、状态值、选择行为、详情内容和无障碍名称不改变。
- 不修改或提交工作区中已有的 `README.md`、清理脚本/测试、handoff 文档和 SDD 进度文件。
- 分支最终名称必须为 `test-used`；本地 `main` 必须包含交付提交；`test-used` 分支和工作区必须保留。
- 不直接推送本地 `main`；推送 `test-used` 并创建以远端 `main` 为目标的 PR。
- 服务器目标固定为 `root@116.62.112.245:/opt/autolava`，必须保留 `.env`、`backups/` 和 `autolava_mysql_data` 数据卷。
- 部署不得上传本机 `.env`、虚拟环境、依赖目录或 Git 元数据，不得清空或重建业务数据。

---

### Task 1: 删除营业记录状态圆点

**Files:**
- Modify: `frontend/src/components/RecordTable.tsx`
- Modify: `frontend/src/components/RecordDetailPanel.tsx`
- Test: `frontend/src/components/RecordTable.test.tsx`
- Test: `frontend/src/components/RecordDetailPanel.test.tsx`

**Interfaces:**
- Consumes: `RecordSnapshot.is_open` 与虚拟未录入记录 `{ id: null; date: string }`。
- Produces: 状态容器中的纯文字内容；组件属性和导出类型保持不变。

- [ ] **Step 1: Write the failing table test**

将 `within` 加入 Testing Library import，并在现有语义表格测试中验证状态单元格没有装饰元素：

```tsx
import { fireEvent, render, screen, within } from "@testing-library/react";

const row = screen.getByRole("row", { name: /2026年7月14日 休息/ });
const statusCell = within(row).getByText("休息", { exact: true }).closest("td");
expect(statusCell).not.toBeNull();
expect(statusCell!.querySelector('[aria-hidden="true"]')).toBeNull();
```

- [ ] **Step 2: Write the failing detail test**

在休息记录测试中验证“营业状态”值容器没有装饰元素：

```tsx
const statusValue = screen.getByText("休息", { exact: true }).closest("p");
expect(statusValue).not.toBeNull();
expect(statusValue!.querySelector('[aria-hidden="true"]')).toBeNull();
```

- [ ] **Step 3: Run tests to verify RED**

Run from `frontend`:

```powershell
npm test -- src/components/RecordTable.test.tsx src/components/RecordDetailPanel.test.tsx
```

Expected: both new assertions FAIL because each status container still contains an `aria-hidden="true"` circle.

- [ ] **Step 4: Remove the table marker**

Replace the status cell body in `RecordTable.tsx` with pure text:

```tsx
<td className="px-3 py-3">{isUnrecorded ? "未录入" : record.is_open}</td>
```

- [ ] **Step 5: Remove the detail marker**

Replace the detail status value in `RecordDetailPanel.tsx` with pure text and remove unused flex/gap styling:

```tsx
<p className="font-medium">{isUnrecorded ? "未录入" : record.is_open}</p>
```

- [ ] **Step 6: Run focused tests to verify GREEN**

Run from `frontend`:

```powershell
npm test -- src/components/RecordTable.test.tsx src/components/RecordDetailPanel.test.tsx
```

Expected: both test files pass with no test warnings or failures.

- [ ] **Step 7: Commit the UI change**

```powershell
git add -- frontend/src/components/RecordTable.tsx frontend/src/components/RecordDetailPanel.tsx frontend/src/components/RecordTable.test.tsx frontend/src/components/RecordDetailPanel.test.tsx
git commit -m "style: remove business record status dots"
```

### Task 2: 验证、改名、合并并创建 PR

**Files:**
- No source-file changes.
- Preserve: existing uncommitted files reported by `git status --short` outside Task 1.

**Interfaces:**
- Consumes: Task 1 commit、当前 `feature/phase-1-foundation` worktree、main checkout `D:\work\myself\AI-try\AutoLava-AI`、GitHub remote `origin`。
- Produces: 本地 `test-used` 分支、本地合并后的 `main`、远端 `test-used`、面向远端 `main` 的 PR。

- [ ] **Step 1: Verify the feature branch**

Run the backend full suite from the worktree root:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend\tests -q
```

Then run from `frontend` in the worktree:

```powershell
npm test
npm run build
```

Then run from the worktree root:

```powershell
git diff --check
git status --short
```

Expected: backend full tests and all frontend tests pass, production build exits 0, diff check is empty, and status contains only the known unrelated user-owned files.

- [ ] **Step 2: Rename the checked-out branch**

Run from the worktree root:

```powershell
git show-ref --verify --quiet refs/heads/test-used
if ($LASTEXITCODE -eq 0) { throw "Local branch test-used already exists" }
git branch -m test-used
git branch --show-current
```

Expected: current branch is exactly `test-used`; the worktree remains at `D:\work\myself\AI-try\AutoLava-AI\.worktrees\phase-1-foundation`.

- [ ] **Step 3: Verify the main checkout is safe to merge**

```powershell
git -C D:\work\myself\AI-try\AutoLava-AI branch --show-current
git -C D:\work\myself\AI-try\AutoLava-AI status --short
```

Expected: the checkout is on `main`; if it contains unrelated tracked or untracked changes that overlap the merge, stop and report rather than modify them.

- [ ] **Step 4: Merge locally into main**

```powershell
git -C D:\work\myself\AI-try\AutoLava-AI merge --no-ff test-used -m "merge: integrate test-used"
```

Expected: merge exits 0. Do not delete `test-used` or remove its worktree.

- [ ] **Step 5: Verify the merged main tree**

Run the backend suite from the merged main root:

```powershell
D:\work\myself\AI-try\AutoLava-AI\backend\.venv\Scripts\python.exe -m pytest D:\work\myself\AI-try\AutoLava-AI\backend\tests -q
```

Then run from `D:\work\myself\AI-try\AutoLava-AI\frontend`:

```powershell
npm test
npm run build
```

Expected: backend full tests and all frontend tests pass, and production build exits 0 on the actual merged result.

- [ ] **Step 6: Push the retained branch**

```powershell
git -C D:\work\myself\AI-try\AutoLava-AI\.worktrees\phase-1-foundation push -u origin test-used
```

Expected: remote branch `origin/test-used` is created or fast-forwarded; local main is not pushed.

- [ ] **Step 7: Create or reuse the PR**

First inspect existing PRs:

```powershell
gh pr list --repo Nuru-Banmian/AutoLava_AI --head test-used --base main --state open
```

If no open PR exists, create one:

```powershell
gh pr create --repo Nuru-Banmian/AutoLava_AI --base main --head test-used --title "feat: improve ledger calendar and record status display" --body "Adds monthly recorded-date markers to the daily ledger calendar, preserves existing-record autofill, and removes decorative status dots from business records. Frontend tests and production build pass."
```

Expected: command returns a GitHub PR URL. Record the URL; keep `test-used` and its worktree.

### Task 3: 无损更新临时服务器

**Files:**
- Create temporary local artifact: `$env:TEMP\autolava-test-used-release.tar`
- Overwrite tracked release files under server `/opt/autolava`.
- Preserve on server: `/opt/autolava/.env`, `/opt/autolava/backups/`, Docker volume `autolava_mysql_data`.

**Interfaces:**
- Consumes: locally merged `main`, SSH access to `root@116.62.112.245`, existing server Compose stack.
- Produces: rebuilt `autolava-api` and `autolava-web` containers with existing MySQL data and secrets.

- [ ] **Step 1: Preflight server state without mutation**

```powershell
ssh root@116.62.112.245 'set -eu; test -d /opt/autolava; test -f /opt/autolava/.env; test -f /opt/autolava/compose.yaml; test -f /opt/autolava/compose.temporary.yaml; cd /opt/autolava; docker compose -f compose.yaml -f compose.temporary.yaml ps'
```

Expected: SSH succeeds, required files exist, and current Compose state is printed. Do not continue if `.env` or either Compose file is missing.

- [ ] **Step 2: Create a fresh database backup**

```powershell
ssh root@116.62.112.245 'set -eu; /opt/autolava/scripts/backup-production-db.sh; find /opt/autolava/backups -maxdepth 1 -type f -name "*.sql.gz" -printf "%f\n" | sort | tail -n 1'
```

Expected: backup command exits 0 and prints the newest compressed SQL filename without exposing credentials.

- [ ] **Step 3: Build a secret-free release archive from local main**

```powershell
$releaseTar = Join-Path $env:TEMP 'autolava-test-used-release.tar'
$resolvedTemp = [System.IO.Path]::GetFullPath($releaseTar)
if (Test-Path -LiteralPath $resolvedTemp) { Remove-Item -LiteralPath $resolvedTemp -Force }
git -C D:\work\myself\AI-try\AutoLava-AI archive --format=tar --output=$resolvedTemp main
Get-Item -LiteralPath $resolvedTemp | Select-Object FullName,Length
```

Expected: archive exists under the Windows temporary directory and contains only tracked files from local `main`.

- [ ] **Step 4: Upload and extract without deleting server state**

```powershell
$releaseTar = Join-Path $env:TEMP 'autolava-test-used-release.tar'
scp $releaseTar root@116.62.112.245:/tmp/autolava-test-used-release.tar
ssh root@116.62.112.245 'set -eu; test -f /opt/autolava/.env; tar -xf /tmp/autolava-test-used-release.tar -C /opt/autolava; rm -f /tmp/autolava-test-used-release.tar; test -f /opt/autolava/.env; test -d /opt/autolava/backups'
```

Expected: tracked release files update in place; server `.env` and `backups/` still exist. This step does not remove the deployment directory or Docker volumes.

- [ ] **Step 5: Rebuild and start the Compose stack**

```powershell
ssh root@116.62.112.245 'set -eu; cd /opt/autolava; docker compose -f compose.yaml -f compose.temporary.yaml up -d --build; docker compose -f compose.yaml -f compose.temporary.yaml ps'
```

Expected: build and startup exit 0; `autolava-api`, `autolava-web`, and `autolava-db` are running/healthy, with only Web exposed on port 8080.

- [ ] **Step 6: Verify health, logs, and public access**

```powershell
ssh root@116.62.112.245 'set -eu; curl --fail --silent --show-error http://127.0.0.1:8080/health; cd /opt/autolava; docker compose -f compose.yaml -f compose.temporary.yaml logs --tail=100 autolava-api autolava-web autolava-db'
curl.exe --fail --silent --show-error http://116.62.112.245:8080/health
curl.exe --fail --silent --show-error --output NUL http://116.62.112.245:8080/
```

Expected: both health requests succeed, public Web returns success, and logs contain no migration, database connection, or container startup errors.

- [ ] **Step 7: Remove only the verified local temporary archive**

```powershell
$resolvedTemp = [System.IO.Path]::GetFullPath((Join-Path $env:TEMP 'autolava-test-used-release.tar'))
$tempRoot = [System.IO.Path]::GetFullPath($env:TEMP).TrimEnd('\') + '\'
if (-not $resolvedTemp.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase)) { throw "Release archive is outside TEMP" }
Remove-Item -LiteralPath $resolvedTemp -Force
```

Expected: only `$env:TEMP\autolava-test-used-release.tar` is removed; repository and server files are unaffected.
