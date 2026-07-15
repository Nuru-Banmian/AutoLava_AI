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
