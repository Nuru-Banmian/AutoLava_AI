from app.scripts.inspect_runtime_database import inspect_database_url


def test_runtime_guard_rejects_test_database() -> None:
    identity = inspect_database_url(
        "mysql+asyncmy://user:secret@127.0.0.1/autolava_test"
    )

    assert identity.database == "autolava_test"
    assert identity.is_test_database is True


def test_runtime_guard_accepts_local_database_without_exposing_password() -> None:
    identity = inspect_database_url(
        "mysql+asyncmy://user:secret@127.0.0.1/autolava_local"
    )

    assert identity.database == "autolava_local"
    assert identity.is_test_database is False
    assert "secret" not in repr(identity)
