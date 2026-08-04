from functools import lru_cache
from pathlib import Path
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AUTOLAVA_",
        env_file=ROOT_ENV_FILE,
        extra="ignore",
    )

    environment: str = "development"
    database_path: Path = Path("../.autolava-local/autolava.sqlite3")
    backup_directory: Path = Path("../.autolava-local/backups")
    maintenance_timezone: str = "Europe/Rome"
    jwt_secret: SecretStr = SecretStr("development-only-secret")
    bootstrap_username: str = ""
    cookie_secure: bool = False
    cors_origins: list[str] = ["http://localhost:5173"]
    agent_model_endpoint: str = ""
    agent_model_region: str = ""
    agent_model_id: str = ""
    agent_model_api_key: SecretStr = SecretStr("")
    agent_turn_timeout_seconds: float = Field(default=120, gt=0, le=3600)
    agent_stop_new_tools_seconds: float = Field(
        default=90,
        gt=0,
        le=3600,
    )
    agent_model_round_limit: int = Field(default=8, ge=1, le=100)
    agent_data_tool_call_limit: int = Field(default=12, ge=1, le=1000)
    agent_data_tool_timeout_seconds: float = Field(
        default=10,
        gt=0,
        le=300,
    )
    agent_transient_retry_limit: int = Field(default=1, ge=0, le=1)

    @property
    def agent_model_config_ready(self) -> bool:
        return all(
            value.strip()
            for value in (
                self.agent_model_endpoint,
                self.agent_model_region,
                self.agent_model_id,
                self.agent_model_api_key.get_secret_value(),
            )
        )

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.agent_stop_new_tools_seconds > self.agent_turn_timeout_seconds:
            raise ValueError(
                "agent tool-start deadline cannot exceed turn timeout"
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
