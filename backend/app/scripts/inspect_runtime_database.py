from dataclasses import dataclass

from sqlalchemy.engine import make_url


@dataclass(frozen=True)
class DatabaseIdentity:
    host: str
    database: str
    is_test_database: bool


def inspect_database_url(value: str) -> DatabaseIdentity:
    url = make_url(value)
    database = url.database or ""
    return DatabaseIdentity(
        host=url.host or "",
        database=database,
        is_test_database=database.lower().endswith("_test"),
    )
