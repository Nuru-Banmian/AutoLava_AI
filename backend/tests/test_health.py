from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_health() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert not hasattr(app.state, "sqlite_backup_scheduler")
    assert not hasattr(app.state, "operations_retention_scheduler")


def test_production_exposes_one_scheduler_for_backup_and_chained_retention(
    tmp_path, monkeypatch
) -> None:
    settings = Settings(
        environment="production",
        database_path=tmp_path / "production.sqlite3",
        backup_directory=tmp_path / "backups",
        jwt_secret="production-secret-" + "x" * 32,
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    app = create_app()

    assert app.state.sqlite_backup_scheduler is app.state.operations_retention_scheduler
