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
