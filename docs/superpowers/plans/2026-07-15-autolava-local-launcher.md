# AutoLava AI Windows Local Launcher Implementation Plan

> **Historical implementation record:** The database probe and environment-file snippets below
> describe the superseded launcher. The current launcher contract is SQLite-only and is documented
> in `README.md` and `scripts/start-local.ps1`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable Windows PowerShell launcher that prepares and starts every currently planned AutoLava AI phase on the developer's existing MySQL installation, then opens and supervises the local web application.

**Architecture:** A repository-root PowerShell entry point owns preflight checks, generic `AUTOLAVA_*` configuration loading, dependency hashing, migrations, administrator bootstrap, child-process startup, health polling, and cleanup. Vite proxies stable `/api` and `/health` paths to the loopback FastAPI server. Secrets remain only in ignored local files.

**Tech Stack:** PowerShell 7/Windows PowerShell 5.1, uv, Python 3.12+, FastAPI/Uvicorn, Alembic, MySQL 8.0, Node.js 22+, npm, Vite, pytest, Vitest, Playwright.

## Global Constraints

- Reuse the running local MySQL installation and existing `.autolava-db.env`; do not install or reconfigure MySQL.
- Do not require or install Docker Desktop.
- Never commit, print, snapshot, or document the real database password, JWT secret, or administrator password.
- Store the user's fixed local administrator credentials only in the ignored root `.env`; preserve them across later phases.
- Load every `AUTOLAVA_*` key from `.autolava-db.env` and `.env`; do not hard-code a Phase 1/3/4 environment-variable whitelist.
- Always run `alembic upgrade head` before the API so later-phase migrations apply automatically.
- Reinstall backend/frontend dependencies only when their manifest hash changes or the installation directory is missing.
- Bind API and web servers only to `127.0.0.1`, at ports `8000` and `5173` respectively.
- Open the browser only after `http://127.0.0.1:5173/health` succeeds through the Vite proxy.
- Stop only child processes created by the launcher; never kill processes globally by name.
- Keep production Docker Compose, Nginx, and secure-cookie behavior unchanged.

---

## File Structure

- Create `scripts/start-local.ps1`: repository-root-aware Windows orchestration entry point.
- Create `backend/tests/test_local_launcher.py`: static deployment-contract regressions that run on Linux CI without executing Windows services.
- Modify `frontend/vite.config.ts`: add phase-independent loopback development proxy.
- Modify `.gitignore`: ignore launcher dependency-state directory.
- Modify `README.md`: document one-command local use, secrets, and lifecycle.

### Task 1: Add the phase-independent Vite development proxy

**Files:**
- Create: `backend/tests/test_local_launcher.py`
- Modify: `frontend/vite.config.ts`

**Interfaces:**
- Consumes: the existing frontend client contract, which sends relative requests to `/api`.
- Produces: Vite `server.proxy` entries for `/api` and `/health`, both targeting `http://127.0.0.1:8000`.

- [ ] **Step 1: Write the failing proxy contract test**

Create `backend/tests/test_local_launcher.py`:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_vite_proxies_api_and_health_to_loopback_backend() -> None:
    vite = read("frontend/vite.config.ts")
    assert 'target: "http://127.0.0.1:8000"' in vite
    assert '"/api"' in vite
    assert '"/health"' in vite
    assert "changeOrigin: false" in vite
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `cd backend && pytest tests/test_local_launcher.py -q`

Expected: FAIL because `vite.config.ts` has no `server.proxy` configuration.

- [ ] **Step 3: Add the minimal Vite proxy**

Update `frontend/vite.config.ts` so `defineConfig` includes:

```ts
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: false,
      },
      "/health": {
        target: "http://127.0.0.1:8000",
        changeOrigin: false,
      },
    },
  },
```

Do not change the existing plugins, alias, or Vitest configuration.

- [ ] **Step 4: Verify proxy and existing frontend behavior**

Run: `cd backend && pytest tests/test_local_launcher.py -q`

Expected: 1 passed.

Run: `cd frontend && npm test && npm run build`

Expected: all 64 existing tests pass and the production build succeeds. The Vite development-only proxy must not alter production output behavior.

- [ ] **Step 5: Commit the proxy**

```bash
git add backend/tests/test_local_launcher.py frontend/vite.config.ts
git commit -m "feat: proxy local development API"
```

### Task 2: Implement secure configuration, preflight, and dependency preparation

**Files:**
- Modify: `backend/tests/test_local_launcher.py`
- Create: `scripts/start-local.ps1`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: root `.autolava-db.env`, optional root `.env`, `backend/pyproject.toml`, `frontend/package-lock.json`, local `uv`, Node.js, npm, and MySQL TCP availability.
- Produces: `Get-EnvFileValues([string]) -> hashtable`, `Initialize-LocalSettings([hashtable]) -> hashtable`, `Set-AutoLavaEnvironment([hashtable])`, `Ensure-Dependencies()`, and ignored `.autolava-local/*.sha256` markers.

- [ ] **Step 1: Add failing launcher configuration tests**

Append to `backend/tests/test_local_launcher.py`:

```python
def test_launcher_has_generic_secret_safe_configuration_contract() -> None:
    launcher = read("scripts/start-local.ps1")
    for fragment in (
        "$PSScriptRoot",
        ".autolava-db.env",
        'Join-Path $RepoRoot ".env"',
        "Get-EnvFileValues",
        "Initialize-LocalSettings",
        "Set-AutoLavaEnvironment",
        "AUTOLAVA_JWT_SECRET",
        "Read-Host -AsSecureString",
        "RandomNumberGenerator",
    ):
        assert fragment in launcher
    assert "Get-ChildItem Env:AUTOLAVA_*" not in launcher


def test_launcher_preflight_and_dependency_cache_are_repository_local() -> None:
    launcher = read("scripts/start-local.ps1")
    for fragment in (
        "Assert-Command",
        "Test-TcpPort",
        "Assert-PortFree",
        "Get-FileHash",
        'Join-Path $RepoRoot ".autolava-local"',
        'Join-Path $BackendDir ".venv"',
        "uv pip install",
        "npm ci",
    ):
        assert fragment in launcher
    assert ".autolava-local/" in read(".gitignore")
```

The `Get-ChildItem Env:AUTOLAVA_*` assertion prevents copying ambient machine secrets into the persisted file. The launcher may set explicit parsed keys in the current process.

- [ ] **Step 2: Run the tests and verify missing launcher failures**

Run: `cd backend && pytest tests/test_local_launcher.py -q`

Expected: the proxy test passes; both launcher tests fail because `scripts/start-local.ps1` does not exist.

- [ ] **Step 3: Add ignored launcher state**

Append exactly this entry to `.gitignore`:

```gitignore
.autolava-local/
```

The existing `.env`, `.autolava-db.env`, `.venv/`, `node_modules/`, and `dist/` rules remain intact.

- [ ] **Step 4: Create the launcher preparation layer**

Create `scripts/start-local.ps1` with the following structure and complete functions. Use `[CmdletBinding()] param([switch]$NoBrowser)` followed by `Set-StrictMode -Version Latest` and `$ErrorActionPreference = "Stop"`.

Define repository paths only from `$PSScriptRoot`:

```powershell
$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot "backend"
$FrontendDir = Join-Path $RepoRoot "frontend"
$StateDir = Join-Path $RepoRoot ".autolava-local"
$DatabaseEnvFile = Join-Path $RepoRoot ".autolava-db.env"
$LocalEnvFile = Join-Path $RepoRoot ".env"
$BackendVenv = Join-Path $BackendDir ".venv"
$BackendPython = Join-Path $BackendVenv "Scripts\python.exe"
```

Implement these complete helpers:

```powershell
function Write-Stage([string]$Message) {
    Write-Host "[AutoLava] $Message" -ForegroundColor Cyan
}

function Stop-WithMessage([string]$Message) {
    throw "[AutoLava] $Message"
}

function Assert-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        Stop-WithMessage "缺少命令 $Name，请先安装后重试。"
    }
}

function Get-EnvFileValues([string]$Path) {
    $values = @{}
    if (-not (Test-Path -LiteralPath $Path)) { return $values }
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }
        $separator = $trimmed.IndexOf("=")
        if ($separator -lt 1) { Stop-WithMessage "环境文件格式错误：$Path" }
        $key = $trimmed.Substring(0, $separator).Trim()
        $value = $trimmed.Substring($separator + 1)
        if ($key -notmatch '^AUTOLAVA_[A-Z0-9_]+$') {
            Stop-WithMessage "环境文件包含不支持的键：$key"
        }
        if ($value.Contains("`r") -or $value.Contains("`n")) {
            Stop-WithMessage "环境变量 $key 不能包含换行。"
        }
        $values[$key] = $value
    }
    return $values
}

function New-JwtSecret {
    $bytes = New-Object byte[] 48
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
        return [Convert]::ToBase64String($bytes)
    } finally {
        $generator.Dispose()
    }
}

function Read-PlainSecret([string]$Prompt) {
    $secure = Read-Host $Prompt -AsSecureString
    return [Net.NetworkCredential]::new("", $secure).Password
}

function Write-LocalEnv([hashtable]$Values) {
    $orderedKeys = @(
        "AUTOLAVA_ENVIRONMENT",
        "AUTOLAVA_JWT_SECRET",
        "AUTOLAVA_COOKIE_SECURE",
        "AUTOLAVA_BOOTSTRAP_USERNAME",
        "AUTOLAVA_BOOTSTRAP_PASSWORD"
    )
    $orderedKeys += @($Values.Keys | Where-Object { $_ -notin $orderedKeys } | Sort-Object)
    $lines = foreach ($key in $orderedKeys) {
        if ($Values.ContainsKey($key)) { "$key=$($Values[$key])" }
    }
    [IO.File]::WriteAllLines($LocalEnvFile, $lines, [Text.UTF8Encoding]::new($false))
}

function Initialize-LocalSettings([hashtable]$DatabaseValues) {
    $local = Get-EnvFileValues $LocalEnvFile
    $changed = $false
    if (-not $local.ContainsKey("AUTOLAVA_ENVIRONMENT")) {
        $local["AUTOLAVA_ENVIRONMENT"] = "development"; $changed = $true
    }
    if (-not $local.ContainsKey("AUTOLAVA_JWT_SECRET")) {
        $local["AUTOLAVA_JWT_SECRET"] = New-JwtSecret; $changed = $true
    }
    if (-not $local.ContainsKey("AUTOLAVA_COOKIE_SECURE")) {
        $local["AUTOLAVA_COOKIE_SECURE"] = "false"; $changed = $true
    }
    if (-not $local.ContainsKey("AUTOLAVA_BOOTSTRAP_USERNAME")) {
        $local["AUTOLAVA_BOOTSTRAP_USERNAME"] = Read-Host "本地管理员用户名"
        $changed = $true
    }
    if (-not $local.ContainsKey("AUTOLAVA_BOOTSTRAP_PASSWORD")) {
        $local["AUTOLAVA_BOOTSTRAP_PASSWORD"] = Read-PlainSecret "本地管理员密码"
        $changed = $true
    }
    if ($changed) { Write-LocalEnv $local }

    $merged = @{}
    foreach ($item in $DatabaseValues.GetEnumerator()) { $merged[$item.Key] = $item.Value }
    foreach ($item in $local.GetEnumerator()) { $merged[$item.Key] = $item.Value }
    if (-not $merged.ContainsKey("AUTOLAVA_DATABASE_URL")) {
        Stop-WithMessage ".autolava-db.env 或 .env 必须提供 AUTOLAVA_DATABASE_URL。"
    }
    return $merged
}

function Set-AutoLavaEnvironment([hashtable]$Values) {
    foreach ($item in $Values.GetEnumerator()) {
        [Environment]::SetEnvironmentVariable($item.Key, [string]$item.Value, "Process")
    }
}
```

`Write-LocalEnv` writes launcher-created base values first and preserves every additional Phase 3/4 key in sorted order.

Add complete preflight and cache helpers:

```powershell
function Test-TcpPort([string]$HostName, [int]$Port, [int]$TimeoutMs = 500) {
    $client = [Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync($HostName, $Port)
        return $task.Wait($TimeoutMs) -and $client.Connected
    } catch { return $false } finally { $client.Dispose() }
}

function Assert-PortFree([int]$Port) {
    if (Test-TcpPort "127.0.0.1" $Port 250) {
        Stop-WithMessage "端口 $Port 已被占用，请关闭占用程序后重试。"
    }
}

function Invoke-Checked([string]$Label, [scriptblock]$Action) {
    Write-Stage $Label
    & $Action
    if ($LASTEXITCODE -ne 0) { Stop-WithMessage "$Label 失败，退出码 $LASTEXITCODE。" }
}

function Get-ManifestHash([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
}

function Test-HashCurrent([string]$Marker, [string]$Hash) {
    return (Test-Path -LiteralPath $Marker) -and
        ((Get-Content -Raw -LiteralPath $Marker).Trim() -eq $Hash)
}

function Save-Hash([string]$Marker, [string]$Hash) {
    [IO.File]::WriteAllText($Marker, $Hash, [Text.UTF8Encoding]::new($false))
}

function Ensure-Dependencies {
    New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
    $backendHash = Get-ManifestHash (Join-Path $BackendDir "pyproject.toml")
    $backendMarker = Join-Path $StateDir "backend.sha256"
    if (-not (Test-Path $BackendPython) -or -not (Test-HashCurrent $backendMarker $backendHash)) {
        if (-not (Test-Path $BackendPython)) {
            Invoke-Checked "创建 Python 虚拟环境" { uv venv $BackendVenv }
        }
        Invoke-Checked "安装后端依赖" { uv pip install --python $BackendPython -e $BackendDir }
        Save-Hash $backendMarker $backendHash
    }

    $frontendHash = Get-ManifestHash (Join-Path $FrontendDir "package-lock.json")
    $frontendMarker = Join-Path $StateDir "frontend.sha256"
    if (-not (Test-Path (Join-Path $FrontendDir "node_modules")) -or
        -not (Test-HashCurrent $frontendMarker $frontendHash)) {
        Invoke-Checked "安装前端依赖" { npm ci --prefix $FrontendDir }
        Save-Hash $frontendMarker $frontendHash
    }
}
```

At the main entry, assert Windows, `uv`, `node`, and `npm`; assert ports 8000/5173 are free; parse the database URL host/port without logging it; require successful MySQL TCP connection; initialize and set environment; then call `Ensure-Dependencies`. Use a regex that accepts the current SQLAlchemy URL:

```powershell
if ($PSVersionTable.PSVersion.Major -ge 6 -and -not $IsWindows) {
    Stop-WithMessage "本启动器仅支持 Windows。"
}
Assert-Command "uv"
Assert-Command "node"
Assert-Command "npm"
Assert-PortFree 8000
Assert-PortFree 5173

$databaseValues = Get-EnvFileValues $DatabaseEnvFile
$settings = Initialize-LocalSettings $databaseValues
$databaseUrl = [string]$settings["AUTOLAVA_DATABASE_URL"]
if ($databaseUrl -notmatch '@(?<host>\[[^\]]+\]|[^:/]+)(:(?<port>\d+))?/') {
    Stop-WithMessage "无法解析 AUTOLAVA_DATABASE_URL 的数据库主机。"
}
$databaseHost = $Matches.host.Trim('[', ']')
$databasePort = if ($Matches.port) { [int]$Matches.port } else { 3306 }
if (-not (Test-TcpPort $databaseHost $databasePort 1500)) {
    Stop-WithMessage "MySQL 无法连接，请确认 MySQL80 服务正在运行。"
}
Set-AutoLavaEnvironment $settings
Ensure-Dependencies
```

- [ ] **Step 5: Run launcher contract and regression tests**

Run: `cd backend && pytest tests/test_local_launcher.py tests/test_deployment_config.py -q && ruff check .`

Expected: all launcher/deployment tests pass and Ruff reports no issues.

Run: `git diff --check`

Expected: no whitespace errors; `git status --short` must not list `.env`, `.autolava-db.env`, `.autolava-local`, `.venv`, or `node_modules`.

- [ ] **Step 6: Commit preparation support**

```bash
git add .gitignore scripts/start-local.ps1 backend/tests/test_local_launcher.py
git commit -m "feat: prepare local AutoLava runtime"
```

### Task 3: Add migration, bootstrap, process supervision, and cleanup

**Files:**
- Modify: `backend/tests/test_local_launcher.py`
- Modify: `scripts/start-local.ps1`

**Interfaces:**
- Consumes: prepared `$BackendPython`, Vite binary, explicit process environment, and free loopback ports from Task 2.
- Produces: `Invoke-DatabaseSetup()`, `Start-Backend() -> Process`, `Start-Frontend() -> Process`, `Wait-Healthy(uri, process, timeout)`, `Stop-OwnedProcess(process)`, browser opening, and unified `try/finally` cleanup.

- [ ] **Step 1: Add failing lifecycle contract tests**

Append to `backend/tests/test_local_launcher.py`:

```python
def test_launcher_migrates_bootstraps_and_waits_for_proxied_health() -> None:
    launcher = read("scripts/start-local.ps1")
    ordered = [
        "Ensure-Dependencies",
        "Invoke-DatabaseSetup",
        "Start-Backend",
        'Wait-Healthy "http://127.0.0.1:8000/health"',
        "Start-Frontend",
        'Wait-Healthy "http://127.0.0.1:5173/health"',
    ]
    positions = [launcher.rindex(fragment) for fragment in ordered]
    assert positions == sorted(positions)
    assert '"-m", "alembic", "upgrade", "head"' in launcher
    assert '"-m", "app.scripts.create_admin"' in launcher


def test_launcher_owns_and_cleans_up_only_its_child_processes() -> None:
    launcher = read("scripts/start-local.ps1")
    assert "try {" in launcher
    assert "finally {" in launcher
    assert "Stop-OwnedProcess $frontendProcess" in launcher
    assert "Stop-OwnedProcess $backendProcess" in launcher
    assert "Stop-Process -Id $Process.Id" in launcher
    assert "taskkill" not in launcher.lower()
    assert "Stop-Process -Name" not in launcher
```

- [ ] **Step 2: Run lifecycle tests and verify failure**

Run: `cd backend && pytest tests/test_local_launcher.py -q`

Expected: configuration tests pass; lifecycle tests fail because the functions and ordered main flow are absent.

- [ ] **Step 3: Implement database setup and child-process functions**

Add these complete functions before the main entry:

```powershell
function Invoke-PythonCommand([string]$Label, [string[]]$Arguments) {
    Write-Stage $Label
    $process = Start-Process -FilePath $BackendPython -ArgumentList $Arguments `
        -WorkingDirectory $BackendDir -NoNewWindow -Wait -PassThru
    if ($process.ExitCode -ne 0) { Stop-WithMessage "$Label 失败，退出码 $($process.ExitCode)。" }
}

function Invoke-DatabaseSetup {
    Invoke-PythonCommand "升级数据库结构" @("-m", "alembic", "upgrade", "head")
    Invoke-PythonCommand "初始化本地管理员" @("-m", "app.scripts.create_admin")
}

function Start-Backend {
    Write-Stage "启动 FastAPI：http://127.0.0.1:8000"
    return Start-Process -FilePath $BackendPython `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--workers", "1") `
        -WorkingDirectory $BackendDir -NoNewWindow -PassThru
}

function Start-Frontend {
    $node = (Get-Command node).Source
    $vite = Join-Path $FrontendDir "node_modules\vite\bin\vite.js"
    if (-not (Test-Path -LiteralPath $vite)) { Stop-WithMessage "Vite 未安装，请重新运行启动器。" }
    Write-Stage "启动 Vite：http://127.0.0.1:5173"
    return Start-Process -FilePath $node `
        -ArgumentList @($vite, "--host", "127.0.0.1", "--port", "5173", "--strictPort") `
        -WorkingDirectory $FrontendDir -NoNewWindow -PassThru
}

function Wait-Healthy([string]$Uri, [Diagnostics.Process]$Process, [int]$TimeoutSeconds = 45) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        $Process.Refresh()
        if ($Process.HasExited) { Stop-WithMessage "子进程在健康检查前退出，退出码 $($Process.ExitCode)。" }
        try {
            $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) { return }
        } catch { Start-Sleep -Milliseconds 500 }
    }
    Stop-WithMessage "等待 $Uri 健康检查超时。"
}

function Stop-OwnedProcess([Diagnostics.Process]$Process) {
    if ($null -eq $Process) { return }
    try {
        $Process.Refresh()
        if (-not $Process.HasExited) {
            Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
            $Process.WaitForExit(5000) | Out-Null
        }
    } catch { Write-Warning "清理子进程 $($Process.Id) 时出现问题。" }
}
```

- [ ] **Step 4: Implement the ordered supervised main flow**

After Task 2 preflight, use this exact lifecycle shape:

```powershell
$backendProcess = $null
$frontendProcess = $null
try {
    Ensure-Dependencies
    Invoke-DatabaseSetup
    $backendProcess = Start-Backend
    Wait-Healthy "http://127.0.0.1:8000/health" $backendProcess
    $frontendProcess = Start-Frontend
    Wait-Healthy "http://127.0.0.1:5173/health" $frontendProcess
    Write-Host "AutoLava AI 已就绪：http://127.0.0.1:5173" -ForegroundColor Green
    if (-not $NoBrowser) { Start-Process "http://127.0.0.1:5173" | Out-Null }

    while ($true) {
        Start-Sleep -Seconds 1
        $backendProcess.Refresh()
        $frontendProcess.Refresh()
        if ($backendProcess.HasExited) {
            Stop-WithMessage "FastAPI 已退出，退出码 $($backendProcess.ExitCode)。"
        }
        if ($frontendProcess.HasExited) {
            Stop-WithMessage "Vite 已退出，退出码 $($frontendProcess.ExitCode)。"
        }
    }
} finally {
    Write-Stage "正在关闭本地服务"
    Stop-OwnedProcess $frontendProcess
    Stop-OwnedProcess $backendProcess
}
```

Keep `Ensure-Dependencies` only in this final location so the ordering regression uses `rindex` to validate the executable main flow rather than function definitions.

- [ ] **Step 5: Verify lifecycle contracts and frontend regressions**

Run: `cd backend && pytest tests/test_local_launcher.py tests/test_deployment_config.py -q && ruff check .`

Expected: all tests pass and Ruff is clean.

Run: `cd frontend && npm test && npm run build && npx playwright test`

Expected: 64 unit tests, production build, and 3 responsive Playwright tests pass.

- [ ] **Step 6: Commit supervised startup**

```bash
git add scripts/start-local.ps1 backend/tests/test_local_launcher.py
git commit -m "feat: supervise local AutoLava services"
```

### Task 4: Document, provision local secrets, and perform real Windows acceptance

**Files:**
- Modify: `README.md`
- Modify: `backend/tests/test_local_launcher.py`
- Local only, never stage: `.env`, `.autolava-local/`, `backend/.venv/`, `frontend/node_modules/`

**Interfaces:**
- Consumes: the complete launcher and the user's existing ignored database URL.
- Produces: durable local administrator/JWT configuration, documented one-command use, real browser-visible service, and proof that cleanup/restart work.

- [ ] **Step 1: Add failing documentation/security tests**

Append to `backend/tests/test_local_launcher.py`:

```python
def test_readme_documents_reusable_windows_launcher_without_secrets() -> None:
    readme = read("README.md")
    for fragment in (
        r".\scripts\start-local.ps1",
        "http://127.0.0.1:5173",
        "Ctrl+C",
        "Phase 3",
        "Phase 4",
        ".autolava-db.env",
        ".env",
    ):
        assert fragment in readme


def test_local_runtime_artifacts_are_ignored() -> None:
    ignore = read(".gitignore").splitlines()
    assert ".env" in ignore
    assert ".autolava-db.env" in ignore
    assert ".autolava-local/" in ignore
    assert ".venv/" in ignore
    assert "node_modules/" in ignore
```

- [ ] **Step 2: Run documentation tests and verify failure**

Run: `cd backend && pytest tests/test_local_launcher.py -q`

Expected: README test fails because local launcher instructions are absent; ignore test passes.

- [ ] **Step 3: Document local launcher use and future-stage behavior**

Add a `## Windows local development` section to `README.md` before `## Production deployment`. It must state:

```markdown
## Windows local development

The reusable local launcher supports the current Phase 1 application and remains the entry point
for possible future Phase 3 agent and Phase 4 automation features. It reuses the local
MySQL service, applies every migration through `alembic upgrade head`, refreshes dependencies when
their manifests change, starts FastAPI and Vite, and opens `http://127.0.0.1:5173`.

Keep the SQLAlchemy database URL in the ignored `.autolava-db.env`. The launcher creates or reuses
the ignored root `.env` for the local JWT and administrator credentials. Later-phase model keys and
other `AUTOLAVA_*` settings also belong in `.env`; the launcher passes them through without needing
a code change. Never commit either environment file.

Run from PowerShell:

```powershell
.\scripts\start-local.ps1
```

The first run installs missing dependencies and asks for administrator credentials only when they
are absent. Later runs reuse the saved local values. Press `Ctrl+C` in the launcher window to stop
both services. Use `-NoBrowser` when an automatic browser window is not wanted.
```

- [ ] **Step 4: Provision the user's fixed local administrator configuration without exposing it**

Run the launcher in a dedicated local PowerShell window. If `.env` is absent, use its secure prompts to write `AUTOLAVA_ENVIRONMENT=development`, a generated 48-byte random JWT, `AUTOLAVA_COOKIE_SECURE=false`, and the fixed administrator username/password already supplied directly by the user. Root-agent orchestration owns this secret-bearing interaction; do not delegate it to a subagent or copy the literal password into this plan, shell history shown to the user, tests, patches, commits, progress ledgers, or review messages.

Confirm the result without reading its values:

```powershell
git check-ignore .env
git status --short
```

Expected: the first command prints `.env`; the second command does not list `.env` in tracked or untracked changes.

- [ ] **Step 5: Run real Windows acceptance**

Run from the worktree root in a dedicated visible PowerShell window:

```powershell
.\scripts\start-local.ps1 -NoBrowser
```

Expected sequence:

1. MySQL TCP check succeeds without printing its URL.
2. Dependency installation runs only when required.
3. Alembic reaches `head`.
4. Administrator bootstrap reports created or already exists without printing a password.
5. Direct backend health returns 200.
6. Proxied frontend health returns 200.
7. `http://127.0.0.1:5173` loads and the configured administrator can log in.

From a second shell, verify:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:5173/health -UseBasicParsing
```

Expected: both status codes are 200.

Send `Ctrl+C` to the launcher and verify:

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8000,5173 -ErrorAction SilentlyContinue
```

Expected: no listeners. Start the launcher a second time and confirm both dependency installation stages are skipped because hashes are current; stop it again and confirm ports are released.

- [ ] **Step 6: Run the complete verification gate**

With the dedicated `autolava_test` MySQL configuration used for tests:

```text
cd backend
ruff check .
pytest --cov=app --cov-report=term-missing
cd ../frontend
npm test
npm run build
npx playwright test
```

Expected: backend suite and coverage command pass, frontend 64+ tests pass, production build passes, and all Playwright tests pass. Run `git diff --check`, confirm the worktree is clean except intended tracked changes, and request an independent code review.

- [ ] **Step 7: Commit documentation and final regressions**

```bash
git add README.md backend/tests/test_local_launcher.py
git commit -m "docs: add reusable local startup workflow"
```

- [ ] **Step 8: Push and verify pull-request CI**

```bash
git push origin feature/phase-1-foundation
gh pr checks 2 --watch
```

Expected: backend, frontend, and containers jobs all pass. The ignored `.env` remains local and the remote diff contains no real credentials.
