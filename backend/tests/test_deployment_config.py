from pathlib import Path

import yaml
import pytest
from pydantic import ValidationError

from app.core.config import Settings


ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_compose_contains_only_api_and_web_with_host_database_configuration() -> None:
    compose = yaml.safe_load(read("compose.yaml"))

    assert set(compose["services"]) == {"autolava-api", "autolava-web"}
    api = compose["services"]["autolava-api"]
    assert api["environment"] == {
        "AUTOLAVA_ENVIRONMENT": "production",
        "AUTOLAVA_DATABASE_URL": "${AUTOLAVA_DATABASE_URL:?set a non-default production database URL}",
        "AUTOLAVA_JWT_SECRET": "${AUTOLAVA_JWT_SECRET:?set a random production JWT secret}",
        "AUTOLAVA_COOKIE_SECURE": "${AUTOLAVA_COOKIE_SECURE:-true}",
        "AUTOLAVA_BOOTSTRAP_USERNAME": "${AUTOLAVA_BOOTSTRAP_USERNAME}",
        "AUTOLAVA_BOOTSTRAP_PASSWORD": "${AUTOLAVA_BOOTSTRAP_PASSWORD}",
    }
    assert api["extra_hosts"] == ["host.docker.internal:host-gateway"]
    assert "image" not in api or "mysql" not in api["image"].lower()


def test_images_and_nginx_define_the_release_boundaries() -> None:
    backend = read("backend/Dockerfile")
    frontend = read("frontend/Dockerfile")
    nginx = read("frontend/nginx.conf")

    assert "alembic upgrade head" in backend
    assert "uvicorn app.main:app --host 0.0.0.0 --port 8000" in backend
    assert "npm ci" in frontend and "npm run build" in frontend
    assert frontend.count("FROM ") == 2 and "nginx" in frontend
    assert "proxy_pass http://autolava-api:8000/api/;" in nginx
    assert "proxy_pass http://autolava-api:8000/health;" in nginx
    assert "try_files $uri /index.html;" in nginx


def test_ci_runs_backend_frontend_browser_and_container_release_gates() -> None:
    ci_text = read(".github/workflows/ci.yml")
    workflow = yaml.safe_load(ci_text)
    containers = workflow["jobs"]["containers"]
    commands = [step["run"] for step in containers["steps"] if "run" in step]

    for contract in (
        "mysql:8.4",
        "ruff check .",
        "pytest --cov=app --cov-report=term-missing",
        "npm ci",
        "npm test",
        "npm run build",
        "playwright install --with-deps chromium",
        "playwright test",
        "docker compose config",
        "docker compose build",
    ):
        assert contract in ci_text
    assert containers["services"]["mysql"]["image"] == "mysql:8.4"
    assert "@host.docker.internal:3306/autolava" in containers["env"][
        "AUTOLAVA_DATABASE_URL"
    ]
    assert any("docker compose up -d --build" in command for command in commands)
    assert any("nginx -t" in command for command in commands)
    assert any("curl --fail" in command and "/health" in command for command in commands)
    cleanup = containers["steps"][-1]
    assert cleanup["if"] == "always()"
    assert "docker compose logs --no-color || true" in cleanup["run"]
    assert "docker compose down" in cleanup["run"]


def test_environment_example_and_readme_document_bootstrap_without_real_secrets() -> None:
    environment = read(".env.example")
    readme = read("README.md")

    for key in (
        "AUTOLAVA_DATABASE_URL",
        "AUTOLAVA_JWT_SECRET",
        "AUTOLAVA_COOKIE_SECURE",
        "AUTOLAVA_BOOTSTRAP_USERNAME",
        "AUTOLAVA_BOOTSTRAP_PASSWORD",
    ):
        assert f"{key}=" in environment
    assert "development-only-secret" not in environment
    assert "AUTOLAVA_COOKIE_SECURE=true" in environment
    assert "python -m app.scripts.create_admin" in readme
    assert "docker compose up -d --build" in readme
    assert "HTTPS" in readme
    assert "AUTOLAVA_COOKIE_SECURE=false" in readme


@pytest.mark.parametrize(
    ("database_url", "jwt_secret"),
    [
        ("mysql+asyncmy://autolava:strong@db/autolava", ""),
        ("mysql+asyncmy://autolava:strong@db/autolava", "development-only-secret"),
        ("mysql+asyncmy://autolava:strong@db/autolava", "short-secret"),
        ("mysql+asyncmy://autolava:autolava@db/autolava", "a" * 32),
        ("mysql+asyncmy://autolava:change-me@db/autolava", "a" * 32),
    ],
)
def test_production_settings_reject_weak_credentials(database_url: str, jwt_secret: str) -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production", database_url=database_url, jwt_secret=jwt_secret)


def test_development_defaults_remain_available() -> None:
    settings = Settings(_env_file=None)
    assert settings.environment == "development"


def test_nginx_enforces_a_bounded_login_rate_limit() -> None:
    nginx = read("frontend/nginx.conf")
    assert "limit_req_zone $binary_remote_addr zone=login" in nginx
    assert "location = /api/auth/login" in nginx
    assert "limit_req zone=login" in nginx
