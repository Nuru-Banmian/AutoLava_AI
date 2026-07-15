[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$BackupPath,
    [string]$TargetDatabase = "autolava_local",
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$StateDir = Join-Path $RepoRoot ".autolava-local"
$BackupDir = Join-Path $RepoRoot ".autolava-local\backups"
$DatabaseEnvFile = Join-Path $RepoRoot ".autolava-db.env"
$LocalEnvFile = Join-Path $RepoRoot ".env"

function Get-EnvFileValues([string]$Path) {
    $values = @{}
    if (-not (Test-Path -LiteralPath $Path)) { return $values }
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }
        $separator = $trimmed.IndexOf("=")
        if ($separator -lt 1) { throw "环境文件格式错误：$Path" }
        $values[$trimmed.Substring(0, $separator).Trim()] = $trimmed.Substring($separator + 1)
    }
    return $values
}

function Get-DatabaseUrl {
    $values = Get-EnvFileValues $DatabaseEnvFile
    foreach ($item in (Get-EnvFileValues $LocalEnvFile).GetEnumerator()) { $values[$item.Key] = $item.Value }
    if (-not $values.ContainsKey("AUTOLAVA_DATABASE_URL")) { throw "缺少 AUTOLAVA_DATABASE_URL。" }
    return [string]$values["AUTOLAVA_DATABASE_URL"]
}

function Resolve-MySqlTool([string]$Name) {
    foreach ($candidateName in @("$Name.exe", $Name)) {
        $command = Get-Command $candidateName -ErrorAction SilentlyContinue
        if ($command) { return $command.Source }
    }
    $roots = @((Join-Path $env:ProgramFiles "MySQL"), (Join-Path ${env:ProgramFiles(x86)} "MySQL")) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    foreach ($root in $roots) {
        $candidate = Get-ChildItem -LiteralPath $root -Directory | Sort-Object Name -Descending | ForEach-Object { Join-Path $_.FullName "bin\$Name.exe" } | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if ($candidate) { return $candidate }
    }
    throw "找不到 $Name。请安装 MySQL 客户端工具并重试。"
}

function ConvertTo-OptionValue([string]$Value) { return '"' + $Value.Replace('\', '\\').Replace('"', '\"') + '"' }

function New-DefaultsFile([Uri]$Uri) {
    New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
    $defaultsFile = Join-Path $StateDir ("db-client-{0}.cnf" -f [Guid]::NewGuid().ToString("N"))
    $userInfo = $Uri.UserInfo.Split(":", 2)
    $username = [Uri]::UnescapeDataString($userInfo[0])
    $password = if ($userInfo.Count -gt 1) { [Uri]::UnescapeDataString($userInfo[1]) } else { "" }
    $port = if ($Uri.IsDefaultPort) { 3306 } else { $Uri.Port }
    $content = @("[client]", "host=$(ConvertTo-OptionValue $Uri.Host)", "port=$port", "user=$(ConvertTo-OptionValue $username)", "password=$(ConvertTo-OptionValue $password)", "default-character-set=utf8mb4") -join [Environment]::NewLine
    [IO.File]::WriteAllText($defaultsFile, $content, [Text.UTF8Encoding]::new($false))
    return $defaultsFile
}

function Set-RuntimeDatabaseUrl([string]$Path, [string]$DatabaseName) {
    $lines = @(Get-Content -LiteralPath $Path -Encoding UTF8)
    $updated = $false
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if (-not $lines[$index].StartsWith("AUTOLAVA_DATABASE_URL=")) { continue }
        $source = $lines[$index].Substring("AUTOLAVA_DATABASE_URL=".Length)
        $builder = [UriBuilder]([Uri]$source)
        $builder.Path = "/$DatabaseName"
        $lines[$index] = "AUTOLAVA_DATABASE_URL=$($builder.Uri.AbsoluteUri)"
        $updated = $true
    }
    if (-not $updated) { throw "$Path 中缺少 AUTOLAVA_DATABASE_URL。" }
    $temporaryPath = "$Path.tmp"
    try {
        [IO.File]::WriteAllLines($temporaryPath, $lines, [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temporaryPath -Destination $Path -Force
    } finally {
        if (Test-Path -LiteralPath $temporaryPath) { Remove-Item -LiteralPath $temporaryPath -Force }
    }
}

if ($TargetDatabase.endsWith("_test", [StringComparison]::OrdinalIgnoreCase)) { throw "TargetDatabase 不能是自动化测试数据库。使用 -Force 也不会绕过此限制。" }
if ($TargetDatabase -notmatch '^[A-Za-z0-9_]+$') { throw "TargetDatabase 只能包含字母、数字和下划线。" }
$resolvedBackup = (Resolve-Path -LiteralPath $BackupPath).Path
$resolvedBackupDir = (Resolve-Path -LiteralPath $BackupDir).Path.TrimEnd('\') + '\'
if (-not $resolvedBackup.StartsWith($resolvedBackupDir, [StringComparison]::OrdinalIgnoreCase)) { throw "BackupPath 必须位于 .autolava-local\backups。" }

$databaseUri = [Uri](Get-DatabaseUrl)
$mysqlTool = Resolve-MySqlTool "mysql"
$defaultsFile = New-DefaultsFile $databaseUri
try {
    $existingTables = & $mysqlTool "--defaults-extra-file=$defaultsFile" "--batch" "--skip-column-names" "--execute=SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$TargetDatabase';"
    if ($LASTEXITCODE -ne 0) { throw "无法检查目标数据库。" }
    if ([int]($existingTables | Select-Object -First 1) -gt 0 -and -not $Force) { throw "目标数据库非空；如已确认备份，请显式传入 -Force。" }
    if ($Force) {
        & $mysqlTool "--defaults-extra-file=$defaultsFile" "--execute=DROP DATABASE IF EXISTS ``$TargetDatabase``; CREATE DATABASE ``$TargetDatabase`` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    } else {
        & $mysqlTool "--defaults-extra-file=$defaultsFile" "--execute=CREATE DATABASE IF NOT EXISTS ``$TargetDatabase`` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    }
    if ($LASTEXITCODE -ne 0) { throw "创建目标数据库失败。" }
    $process = Start-Process -FilePath $mysqlTool -ArgumentList @("--defaults-extra-file=$defaultsFile", $TargetDatabase) -RedirectStandardInput $resolvedBackup -Wait -NoNewWindow -PassThru
    if ($process.ExitCode -ne 0) { throw "恢复数据库失败，退出码 $($process.ExitCode)。" }
    $restoredTables = & $mysqlTool "--defaults-extra-file=$defaultsFile" "--batch" "--skip-column-names" "--execute=SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$TargetDatabase';"
    if ([int]($restoredTables | Select-Object -First 1) -le 0) { throw "恢复完成但未发现数据表。" }
    Set-RuntimeDatabaseUrl $DatabaseEnvFile $TargetDatabase
    Write-Host "备份已恢复到数据库 $TargetDatabase。使用 -Force 可显式覆盖非空目标。"
} finally {
    if (Test-Path -LiteralPath $defaultsFile) { Remove-Item -LiteralPath $defaultsFile -Force }
}
