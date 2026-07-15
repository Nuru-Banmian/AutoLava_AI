[CmdletBinding()]
param([switch]$NoBrowser)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot "backend"
$FrontendDir = Join-Path $RepoRoot "frontend"
$StateDir = Join-Path $RepoRoot ".autolava-local"
$DatabaseEnvFile = Join-Path $RepoRoot ".autolava-db.env"
$LocalEnvFile = Join-Path $RepoRoot ".env"
$BackendVenv = Join-Path $BackendDir ".venv"
$BackendPython = Join-Path $BackendVenv "Scripts\python.exe"

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
    $secure = Read-Host -AsSecureString -Prompt $Prompt
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
