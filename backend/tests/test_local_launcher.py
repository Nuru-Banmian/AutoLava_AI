import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_vite_proxies_api_and_health_to_loopback_backend() -> None:
    vite = read("frontend/vite.config.ts")
    for route in ("api", "health"):
        match = re.search(rf'"/{route}"\s*:\s*\{{(?P<body>.*?)\n\s*\}}', vite, re.DOTALL)
        assert match, f"missing /{route} proxy block"
        block = match.group("body")
        assert 'target: "http://127.0.0.1:8000"' in block
        assert "changeOrigin: false" in block


def test_launcher_has_generic_secret_safe_configuration_contract() -> None:
    launcher = read("scripts/start-local.ps1")
    for fragment in (
        "$PSScriptRoot",
        ".autolava-db.env",
        'Join-Path $RepoRoot ".env"',
        "Get-EnvFileValues",
        "Initialize-LocalSettings",
        "Set-AutoLavaEnvironment",
        "Get-AutoLavaEnvironmentSnapshot",
        "Restore-AutoLavaEnvironment",
        "AUTOLAVA_JWT_SECRET",
        "Read-Host -AsSecureString",
        "RandomNumberGenerator",
    ):
        assert fragment in launcher
    assert "Get-ChildItem Env:AUTOLAVA_*" not in launcher


def test_launcher_validates_local_credentials_without_echoing_values() -> None:
    launcher = read("scripts/start-local.ps1")
    assert '::IsNullOrWhiteSpace([string]$local["AUTOLAVA_JWT_SECRET"])' in launcher
    assert '$jwtSecret.Trim().Length -lt 32' in launcher
    assert "JWT 密钥长度不能少于 32 个字符" in launcher
    assert '::IsNullOrWhiteSpace([string]$local["AUTOLAVA_BOOTSTRAP_USERNAME"])' in launcher
    assert '::IsNullOrWhiteSpace([string]$local["AUTOLAVA_BOOTSTRAP_PASSWORD"])' in launcher
    assert '$username = ([string]$local["AUTOLAVA_BOOTSTRAP_USERNAME"]).Trim()' in launcher
    assert '$username.Length -lt 3 -or $username.Length -gt 80' in launcher
    assert '$local["AUTOLAVA_BOOTSTRAP_USERNAME"] = $username' in launcher
    assert '$password.Length -lt 8 -or $password.Length -gt 128' in launcher
    assert "管理员用户名长度必须为 3 到 80 个字符" in launcher
    assert "管理员密码长度必须为 8 到 128 个字符" in launcher


@pytest.mark.skipif(shutil.which("powershell.exe") is None, reason="requires Windows PowerShell")
def test_launcher_restores_process_environment_when_backend_setup_fails() -> None:
    launcher = read("scripts/start-local.ps1")
    function_names = (
        "Set-AutoLavaEnvironment",
        "Get-AutoLavaEnvironmentSnapshot",
        "Restore-AutoLavaEnvironment",
        "Start-ConfiguredBackend",
    )
    definitions = []
    for name in function_names:
        match = re.search(rf"function {name}.*?^}}", launcher, re.DOTALL | re.MULTILINE)
        assert match, f"missing {name}"
        definitions.append(match.group(0))

    powershell = "\n".join(definitions) + r'''
function Invoke-DatabaseSetup {
    if ($env:AUTOLAVA_TEST_RESTORE_PRESENT -ne "during") { throw "setup missing env" }
    if ($script:failurePoint -eq "setup") { throw "synthetic setup failure" }
}
function Start-Backend {
    if ($env:AUTOLAVA_TEST_RESTORE_MISSING -ne "during") { throw "backend missing env" }
    if ($script:failurePoint -eq "backend") { throw "synthetic backend failure" }
    return "synthetic-process"
}
function Assert-Restored {
    if ([Environment]::GetEnvironmentVariable($present, "Process") -ne "before") {
        throw "existing value was not restored"
    }
    if ($null -ne [Environment]::GetEnvironmentVariable($missing, "Process")) {
        throw "originally missing value was not removed"
    }
}
$present = "AUTOLAVA_TEST_RESTORE_PRESENT"
$missing = "AUTOLAVA_TEST_RESTORE_MISSING"
try {
    $values = @{$present = "during"; $missing = "during"}
    foreach ($script:failurePoint in @("setup", "backend")) {
        [Environment]::SetEnvironmentVariable($present, "before", "Process")
        [Environment]::SetEnvironmentVariable($missing, $null, "Process")
        $caughtExpectedFailure = $false
        try { Start-ConfiguredBackend $values | Out-Null } catch {
            if ($_.Exception.Message -ne "synthetic $script:failurePoint failure") { throw }
            $caughtExpectedFailure = $true
        }
        if (-not $caughtExpectedFailure) { throw "$script:failurePoint did not fail" }
        Assert-Restored
    }
    $script:failurePoint = "none"
    $process = Start-ConfiguredBackend $values
    if ($process -ne "synthetic-process") { throw "backend result was not returned" }
    Assert-Restored
} finally {
    [Environment]::SetEnvironmentVariable($present, $null, "Process")
    [Environment]::SetEnvironmentVariable($missing, $null, "Process")
}
'''
    completed = subprocess.run(
        [shutil.which("powershell.exe"), "-NoProfile", "-Command", powershell],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


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


def test_launcher_windows_check_short_circuits_before_iswindows_on_powershell_51() -> None:
    launcher = read("scripts/start-local.ps1")
    assert "$PSVersionTable.PSVersion.Major -ge 6 -and -not $IsWindows" in launcher


def test_launcher_migrates_bootstraps_and_waits_for_proxied_health() -> None:
    launcher = read("scripts/start-local.ps1")
    configured = re.search(
        r"function Start-ConfiguredBackend.*?^}", launcher, re.DOTALL | re.MULTILINE
    )
    assert configured
    configured_order = [
        "Get-AutoLavaEnvironmentSnapshot",
        "Set-AutoLavaEnvironment",
        "Invoke-DatabaseSetup",
        "Start-Backend",
        "Restore-AutoLavaEnvironment",
    ]
    configured_positions = [configured.group(0).index(fragment) for fragment in configured_order]
    assert configured_positions == sorted(configured_positions)
    assert "try {" in configured.group(0)
    assert "} finally {" in configured.group(0)

    main = launcher[launcher.index("$backendProcess = $null") :]
    main_order = [
        "Ensure-Dependencies",
        "Start-ConfiguredBackend $settings",
        'Wait-Healthy "http://127.0.0.1:8000/health"',
        "Start-Frontend",
        'Wait-Healthy "http://127.0.0.1:5173/health"',
        'Start-Process "http://127.0.0.1:5173"',
    ]
    positions = [main.index(fragment) for fragment in main_order]
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


def test_launcher_passes_vite_entrypoint_relative_to_frontend_working_directory() -> None:
    launcher = read("scripts/start-local.ps1")
    assert '$viteArgument = "node_modules\\vite\\bin\\vite.js"' in launcher
    assert "-ArgumentList @($viteArgument," in launcher
    assert "-ArgumentList @($vite," not in launcher


def test_launcher_rejects_test_database_without_explicit_override() -> None:
    launcher = read("scripts/start-local.ps1")
    assert "[switch]$AllowTestDatabase" in launcher
    assert "function Assert-RuntimeDatabaseUrl" in launcher
    assert "数据库保留给自动化测试" in launcher
    assert "Assert-RuntimeDatabaseUrl $databaseUrl $AllowTestDatabase" in launcher


def test_database_backup_and_restore_scripts_are_secret_safe() -> None:
    backup = read("scripts/backup-local-db.ps1")
    restore = read("scripts/restore-local-db.ps1")
    for script in (backup, restore):
        assert "--defaults-extra-file" in script
        assert "Remove-Item -LiteralPath $defaultsFile" in script
        assert "finally" in script
        assert "AUTOLAVA_DATABASE_URL" in script
        assert "--password=" not in script
    assert '.autolava-local\\backups' in backup
    assert "mysqldump" in backup
    assert '"--no-tablespaces"' in backup
    assert "TargetDatabase" in restore
    assert "endsWith(\"_test\"" in restore
    assert "-Force" in restore
    assert "function Set-RuntimeDatabaseUrl" in restore
    assert "Set-RuntimeDatabaseUrl $DatabaseEnvFile $TargetDatabase" in restore


def test_readme_documents_reusable_windows_launcher_without_secrets() -> None:
    readme = read("README.md")
    for fragment in (
        r".\scripts\start-local.ps1",
        "http://127.0.0.1:5173",
        "-NoBrowser",
        "alembic upgrade head",
        "manifests change",
        "Ctrl+C",
        "Phase 2",
        "Phase 3",
        "Phase 4",
        ".autolava-db.env",
        ".env",
        "backup-local-db.ps1",
        "restore-local-db.ps1",
        "autolava_local",
        "-AllowTestDatabase",
    ):
        assert fragment in readme


def test_local_runtime_artifacts_are_ignored() -> None:
    ignore = read(".gitignore").splitlines()
    assert ".env" in ignore
    assert ".autolava-db.env" in ignore
    assert ".autolava-local/" in ignore
    assert ".venv/" in ignore
    assert "node_modules/" in ignore
