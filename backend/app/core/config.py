from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTOLAVA_", env_file=ROOT_ENV_FILE)

    environment: str = "development"
    database_path: Path = Path("../.autolava-local/autolava.sqlite3")
    backup_directory: Path = Path("../.autolava-local/backups")
    maintenance_timezone: str = "Europe/Rome"
    jwt_secret: SecretStr = SecretStr("development-only-secret")
    bootstrap_username: str = ""
    cookie_secure: bool = False
    cors_origins: list[str] = ["http://localhost:5173"]
    model_adapter: Literal["fake", "openai_compatible"] = "fake"
    model_base_url: str = ""
    model_id: str = ""
    model_api_key: SecretStr = SecretStr("")
    model_structured_output_method: Literal[
        "json_schema", "function_calling", "json_mode"
    ] = "json_schema"

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.model_adapter == "openai_compatible":
            required = {
                "model_base_url": self.model_base_url,
                "model_id": self.model_id,
                "model_api_key": self.model_api_key.get_secret_value(),
            }
            missing = [name for name, value in required.items() if not value.strip()]
            if missing:
                raise ValueError(
                    "openai_compatible model adapter requires " + ", ".join(missing)
                )
        if self.environment.lower() != "production":
            return self
        secret = self.jwt_secret.get_secret_value().strip()
        weak_secret_markers = ("development", "example", "change-me", "changeme")
        if len(secret) < 32 or any(marker in secret.lower() for marker in weak_secret_markers):
            raise ValueError("production requires a random JWT secret of at least 32 characters")
        if str(self.database_path) == ":memory:":
            raise ValueError("production requires a file-backed SQLite database")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
