import json
from pathlib import Path
import tomllib

import pytest
from pydantic import ValidationError
import yaml

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


def test_compose_contains_exactly_api_and_web_with_persistent_sqlite_data() -> None:
    compose = yaml.safe_load(read("compose.yaml"))

    assert set(compose["services"]) == {"autolava-api", "autolava-web"}
    assert set(compose["volumes"]) == {"autolava_data"}

    api = compose["services"]["autolava-api"]
    assert api["image"] == "${AUTOLAVA_API_IMAGE:-autolava-api:latest}"
    assert api["build"] == {"context": "./backend", "dockerfile": "Dockerfile"}
    assert api["environment"] == {
        "AUTOLAVA_ENVIRONMENT": "production",
        "AUTOLAVA_DATABASE_PATH": "/data/autolava.sqlite3",
        "AUTOLAVA_BACKUP_DIRECTORY": "/data/backups",
        "AUTOLAVA_JWT_SECRET": "${AUTOLAVA_JWT_SECRET:?set a random production JWT secret}",
        "AUTOLAVA_COOKIE_SECURE": "${AUTOLAVA_COOKIE_SECURE:-true}",
        "AUTOLAVA_BOOTSTRAP_USERNAME": "${AUTOLAVA_BOOTSTRAP_USERNAME}",
        "AUTOLAVA_BOOTSTRAP_PASSWORD": "${AUTOLAVA_BOOTSTRAP_PASSWORD}",
    }
    assert api["volumes"] == ["autolava_data:/data"]
    assert "ports" not in api
    assert "extra_hosts" not in api
    assert "mem_limit" not in api

    web = compose["services"]["autolava-web"]
    assert web["image"] == "${AUTOLAVA_WEB_IMAGE:-autolava-web:latest}"
    assert web["build"] == {
        "context": "./frontend",
        "dockerfile": "Dockerfile.prebuilt",
    }
    assert web["ports"] == ["${AUTOLAVA_WEB_HOST_PORT:-127.0.0.1:80}:80"]
    assert web["depends_on"] == ["autolava-api"]
    assert "mem_limit" not in web


def test_compose_keeps_the_private_network_and_real_ip_boundary() -> None:
    compose = yaml.safe_load(read("compose.yaml"))
    nginx = read("frontend/nginx.conf")

    network = compose["networks"]["default"]["ipam"]["config"][0]
    assert network == {"subnet": "172.30.0.0/24", "gateway": "172.30.0.1"}
    assert "real_ip_header X-Forwarded-For;" in nginx
    assert "real_ip_recursive on;" in nginx
    assert "set_real_ip_from 127.0.0.1;" in nginx
    assert "set_real_ip_from 172.30.0.1;" in nginx
    assert "set_real_ip_from 172.16.0.0/12;" not in nginx
    assert "set_real_ip_from 0.0.0.0/0;" not in nginx


def test_obsolete_database_deployment_and_restore_files_are_deleted() -> None:
    for relative in (
        "compose.temporary.yaml",
        "scripts/backup-local-db.ps1",
        "scripts/restore-local-db.ps1",
        "scripts/backup-production-db.sh",
        "backend/app/scripts/inspect_runtime_database.py",
        "backend/tests/test_runtime_database_guard.py",
    ):
        assert not (ROOT / relative).exists(), relative


def test_runtime_and_dependency_files_have_no_legacy_database_contract() -> None:
    blocked = ("my" + "sql", "async" + "my", "my" + "sqldump", "MY" + "SQL_", "33" + "06")
    runtime_files = (
        "compose.yaml",
        ".env.example",
        "backend/Dockerfile",
        "backend/pyproject.toml",
        "frontend/Dockerfile.prebuilt",
        ".github/workflows/ci.yml",
        "scripts/start-local.ps1",
        "frontend/src/router.tsx",
    )
    for relative in runtime_files:
        content = read(relative)
        for term in blocked:
            assert term.lower() not in content.lower(), f"{relative} contains {term}"


def test_images_and_nginx_define_prebuilt_release_boundaries() -> None:
    backend = read("backend/Dockerfile")
    frontend = read("frontend/Dockerfile.prebuilt")
    frontend_ignore = read("frontend/.dockerignore").splitlines()
    nginx = read("frontend/nginx.conf")

    assert "alembic upgrade head" in backend
    assert "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1" in backend
    assert frontend.count("FROM ") == 1
    assert "nginx" in frontend
    assert "COPY dist /usr/share/nginx/html" in frontend
    assert "npm ci" not in frontend
    assert "npm run build" not in frontend
    assert "dist/" not in frontend_ignore
    assert "proxy_pass http://autolava-api:8000/api/;" in nginx
    assert "proxy_pass http://autolava-api:8000/health;" in nginx
    assert "try_files $uri /index.html;" in nginx


def test_container_builds_use_configured_package_mirrors() -> None:
    backend = read("backend/Dockerfile")
    frontend_build = read("frontend/Dockerfile")
    frontend_prebuilt = read("frontend/Dockerfile.prebuilt")

    assert "mirrors.aliyun.com/pypi/simple" in backend
    assert "registry.npmmirror.com" in frontend_build
    assert "docker.m.daocloud.io/library/python:3.12-slim" in backend
    assert "docker.m.daocloud.io/library/node:22-alpine" in frontend_build
    assert "docker.m.daocloud.io/library/nginx:1.27-alpine" in frontend_prebuilt


def test_domain_http_template_keeps_acme_challenge_reachable() -> None:
    config = read("deploy/nginx/d-washpilot.http.conf")

    assert "server_name d-washpilot.tech www.d-washpilot.tech;" in config
    assert "location ^~ /.well-known/acme-challenge/" in config
    assert "root /var/www/certbot;" in config
    assert "return 301 https://$host$request_uri;" in config


def test_domain_https_template_uses_tls_and_replaces_forwarded_client_ip() -> None:
    config = read("deploy/nginx/d-washpilot.https.conf")

    assert "listen 443 ssl;" in config
    assert "ssl_certificate /root/autolava-cert/d-washpilot.tech.pem;" in config
    assert "ssl_certificate_key /root/autolava-cert/d-washpilot.tech.key;" in config
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in config
    assert "proxy_set_header X-Forwarded-Proto https;" in config
    assert "proxy_pass http://127.0.0.1:8080;" in config


def test_ci_uses_disposable_sqlite_and_prebuilt_release_images() -> None:
    ci_text = read(".github/workflows/ci.yml")
    workflow = yaml.safe_load(ci_text)
    backend = workflow["jobs"]["backend"]
    containers = workflow["jobs"]["containers"]
    backend_commands = [step["run"] for step in backend["steps"] if "run" in step]
    container_commands = [step["run"] for step in containers["steps"] if "run" in step]

    assert "services" not in backend
    assert "services" not in containers
    assert backend["env"]["AUTOLAVA_DATABASE_PATH"] == "${{ runner.temp }}/autolava-ci.sqlite3"
    assert any("aiosqlite" in command for command in backend_commands)
    assert any("alembic upgrade head" in command for command in backend_commands)
    assert any("ruff check ." in command for command in backend_commands)
    assert any("pytest --cov=app --cov-report=term-missing" in command for command in backend_commands)

    for contract in (
        "npm ci",
        "npm test",
        "npm run build",
        "playwright install --with-deps chromium",
        "playwright test",
        "docker compose config",
        "docker compose up -d --no-build",
        "frontend/Dockerfile.prebuilt",
    ):
        assert contract in ci_text
    assert any("docker build" in command and "autolava-api:latest" in command for command in container_commands)
    assert any("docker build" in command and "autolava-web:latest" in command for command in container_commands)
    assert any("nginx -t" in command for command in container_commands)
    assert any("curl --fail" in command and "/health" in command for command in container_commands)
    cleanup = containers["steps"][-1]
    assert cleanup["if"] == "always()"
    assert "docker compose logs --no-color || true" in cleanup["run"]
    assert "docker compose down --volumes --remove-orphans" in cleanup["run"]


def test_environment_example_and_readme_document_sqlite_release_operations() -> None:
    environment = read(".env.example")
    readme = read("README.md")

    for key in (
        "AUTOLAVA_JWT_SECRET",
        "AUTOLAVA_COOKIE_SECURE",
        "AUTOLAVA_BOOTSTRAP_USERNAME",
        "AUTOLAVA_BOOTSTRAP_PASSWORD",
    ):
        assert f"{key}=" in environment
    assert "AUTOLAVA_DATABASE_PATH=" not in environment
    assert "AUTOLAVA_BACKUP_DIRECTORY=" not in environment
    assert "development-only-secret" not in environment
    assert "AUTOLAVA_COOKIE_SECURE=true" in environment

    for fragment in (
        "docker compose up -d --no-build",
        "docker load",
        "/data/autolava.sqlite3",
        "/data/backups",
        "three days",
        "docker stats",
        "stop the API",
        "-wal",
        "-shm",
        "no in-app restore",
        "no migration of old data",
        "python -m app.scripts.create_admin",
        "AUTOLAVA_COOKIE_SECURE=false",
    ):
        assert fragment.lower() in readme.lower()
    assert "docker compose up -d --build" not in readme


@pytest.mark.parametrize(
    "jwt_secret",
    ("", "development-only-secret", "short-secret", "change-me-" + "x" * 32),
)
def test_production_settings_reject_weak_jwt_secrets(jwt_secret: str) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            environment="production",
            database_path=ROOT / "production.sqlite3",
            jwt_secret=jwt_secret,
        )


def test_production_settings_reject_in_memory_database() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            environment="production",
            database_path=":memory:",
            jwt_secret="a" * 32,
        )


def test_development_defaults_remain_available() -> None:
    settings = Settings(_env_file=None)
    assert settings.environment == "development"


def test_nginx_enforces_a_bounded_login_rate_limit() -> None:
    nginx = read("frontend/nginx.conf")

    assert "limit_req_zone $binary_remote_addr zone=login:1m rate=10r/m;" in nginx
    assert "location = /api/auth/login" in nginx
    assert "limit_req zone=login burst=10 nodelay;" in nginx
    assert "limit_req_status 429;" in nginx
    assert "127.0.0.1:80" in read("README.md")
