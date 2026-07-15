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
