[CmdletBinding()]
param([string]$OutputDirectory)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$StateDir = Join-Path $RepoRoot ".autolava-local"
$BackupDir = if ($OutputDirectory) { $OutputDirectory } else { Join-Path $RepoRoot ".autolava-local\backups" }
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

function ConvertTo-OptionValue([string]$Value) {
    return '"' + $Value.Replace('\', '\\').Replace('"', '\"') + '"'
}

function New-DefaultsFile([Uri]$Uri) {
    New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
    $defaultsFile = Join-Path $StateDir ("db-client-{0}.cnf" -f [Guid]::NewGuid().ToString("N"))
    $userInfo = $Uri.UserInfo.Split(":", 2)
    $username = [Uri]::UnescapeDataString($userInfo[0])
    $password = if ($userInfo.Count -gt 1) { [Uri]::UnescapeDataString($userInfo[1]) } else { "" }
    $port = if ($Uri.IsDefaultPort) { 3306 } else { $Uri.Port }
    $content = @(
        "[client]",
        "host=$(ConvertTo-OptionValue $Uri.Host)",
        "port=$port",
        "user=$(ConvertTo-OptionValue $username)",
        "password=$(ConvertTo-OptionValue $password)",
        "default-character-set=utf8mb4"
    ) -join [Environment]::NewLine
    [IO.File]::WriteAllText($defaultsFile, $content, [Text.UTF8Encoding]::new($false))
    return $defaultsFile
}

$databaseUri = [Uri](Get-DatabaseUrl)
$databaseName = [Uri]::UnescapeDataString($databaseUri.AbsolutePath.TrimStart('/'))
if ([string]::IsNullOrWhiteSpace($databaseName)) { throw "数据库 URL 中缺少数据库名称。" }
$dumpTool = Resolve-MySqlTool "mysqldump"
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
$resolvedBackupDir = (Resolve-Path -LiteralPath $BackupDir).Path
$backupPath = Join-Path $resolvedBackupDir ("{0}-{1}.sql" -f $databaseName, (Get-Date -Format "yyyyMMdd-HHmmss"))
$defaultsFile = New-DefaultsFile $databaseUri
try {
    & $dumpTool "--defaults-extra-file=$defaultsFile" "--single-transaction" "--no-tablespaces" "--routines" "--triggers" "--hex-blob" "--default-character-set=utf8mb4" "--result-file=$backupPath" $databaseName
    if ($LASTEXITCODE -ne 0) { throw "mysqldump 失败，退出码 $LASTEXITCODE。" }
    if (-not (Test-Path -LiteralPath $backupPath) -or (Get-Item -LiteralPath $backupPath).Length -le 0) { throw "数据库备份为空。" }
    Write-Host "数据库 $databaseName 已备份到 $backupPath"
} finally {
    if (Test-Path -LiteralPath $defaultsFile) { Remove-Item -LiteralPath $defaultsFile -Force }
}
