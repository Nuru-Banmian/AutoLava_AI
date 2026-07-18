import json
from pathlib import Path
import tomllib

import yaml
import pytest
from pydantic import ValidationError

from app.core.config import Settings


ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_ci_lockfile_contains_linux_native_bindings() -> None:
    package = json.loads(read("frontend/package.json"))
    lock = json.loads(read("frontend/package-lock.json"))
    packages = lock["packages"]
    native_families = {
        "rolldown": (
            "@rolldown/binding-linux-x64-gnu",
            "@rolldown/binding-linux-x64-musl",
        ),
        "lightningcss": (
            "lightningcss-linux-x64-gnu",
            "lightningcss-linux-x64-musl",
        ),
        "@tailwindcss/oxide": (
            "@tailwindcss/oxide-linux-x64-gnu",
            "@tailwindcss/oxide-linux-x64-musl",
        ),
    }
    for dependency, bindings in native_families.items():
        dependency_version = packages[f"node_modules/{dependency}"]["version"]
        for binding in bindings:
            assert package["optionalDependencies"][binding] == dependency_version
            locked_binding = packages.get(f"node_modules/{binding}")
            assert locked_binding is not None
            assert locked_binding["version"] == dependency_version


def test_async_database_tests_share_one_event_loop() -> None:
    config = tomllib.loads(read("backend/pyproject.toml"))["tool"]["pytest"]["ini_options"]

    assert config["asyncio_default_fixture_loop_scope"] == "session"
    assert config["asyncio_default_test_loop_scope"] == "session"


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


def test_temporary_compose_keeps_database_private_and_exposes_only_web() -> None:
    base = yaml.safe_load(read("compose.yaml"))
    compose = yaml.safe_load(read("compose.temporary.yaml"))

    assert set(compose["services"]) == {"autolava-api", "autolava-db"}
    assert base["services"]["autolava-web"]["ports"] == [
        "${AUTOLAVA_WEB_HOST_PORT:-127.0.0.1:80}:80"
    ]
    assert "ports" not in compose["services"]["autolava-db"]
    assert compose["services"]["autolava-api"]["depends_on"]["autolava-db"]["condition"] == "service_healthy"
    assert compose["services"]["autolava-db"]["volumes"] == ["autolava_mysql_data:/var/lib/mysql"]


def test_production_backup_exports_the_full_database_and_keeps_seven_days() -> None:
    script = read("scripts/backup-production-db.sh")

    assert "mysqldump" in script
    assert '"$MYSQL_DATABASE"' in script
    assert "gzip -c" in script
    assert "-mtime +6 -delete" in script


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


def test_container_builds_use_china_package_mirrors() -> None:
    backend = read("backend/Dockerfile")
    frontend = read("frontend/Dockerfile")

    assert "mirrors.aliyun.com/pypi/simple" in backend
    assert "registry.npmmirror.com" in frontend


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
    compose = yaml.safe_load(read("compose.yaml"))
    assert "limit_req_zone $binary_remote_addr zone=login" in nginx
    assert "location = /api/auth/login" in nginx
    assert "limit_req zone=login" in nginx
    assert compose["services"]["autolava-web"]["ports"] == [
        "${AUTOLAVA_WEB_HOST_PORT:-127.0.0.1:80}:80"
    ]
    assert "real_ip_header X-Forwarded-For;" in nginx
    assert "real_ip_recursive on;" in nginx
    assert "set_real_ip_from 127.0.0.1;" in nginx
    network = compose["networks"]["default"]["ipam"]["config"][0]
    assert network == {"subnet": "172.30.0.0/24", "gateway": "172.30.0.1"}
    assert "set_real_ip_from 172.30.0.1;" in nginx
    assert "set_real_ip_from 172.16.0.0/12;" not in nginx
    assert "set_real_ip_from 0.0.0.0/0;" not in nginx
    assert "127.0.0.1:80" in read("README.md")
