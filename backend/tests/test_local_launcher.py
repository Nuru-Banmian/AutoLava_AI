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


def test_launcher_windows_check_short_circuits_before_iswindows_on_powershell_51() -> None:
    launcher = read("scripts/start-local.ps1")
    assert "$PSVersionTable.PSVersion.Major -ge 6 -and -not $IsWindows" in launcher


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


def test_launcher_passes_vite_entrypoint_relative_to_frontend_working_directory() -> None:
    launcher = read("scripts/start-local.ps1")
    assert '$viteArgument = "node_modules\\vite\\bin\\vite.js"' in launcher
    assert "-ArgumentList @($viteArgument," in launcher
    assert "-ArgumentList @($vite," not in launcher


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
    ):
        assert fragment in readme


def test_local_runtime_artifacts_are_ignored() -> None:
    ignore = read(".gitignore").splitlines()
    assert ".env" in ignore
    assert ".autolava-db.env" in ignore
    assert ".autolava-local/" in ignore
    assert ".venv/" in ignore
    assert "node_modules/" in ignore
