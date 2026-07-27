from functools import lru_cache
from pathlib import Path
from typing import Literal

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
    model_adapter: Literal["fake", "openai_compatible"] = "fake"
    model_provider: str = "primary"
    model_base_url: str = ""
    model_id: str = ""
    model_api_key: SecretStr = SecretStr("")
    model_structured_output_method: Literal[
        "json_schema", "function_calling", "json_mode"
    ] = "json_schema"
    model_thinking_parameters: dict[str, str | int | bool] = Field(default_factory=dict)
    model_timeout_seconds: float = Field(default=30, gt=0, le=120)
    model_max_output_tokens: int = Field(default=2000, ge=100, le=10_000)
    model_input_cost_per_million: float | None = None
    model_output_cost_per_million: float | None = None
    fallback_model_provider: str = "fallback"
    fallback_model_base_url: str = ""
    fallback_model_id: str = ""
    fallback_model_api_key: SecretStr = SecretStr("")
    fallback_model_structured_output_method: Literal[
        "json_schema", "function_calling", "json_mode"
    ] = "json_schema"
    fallback_model_thinking_parameters: dict[str, str | int | bool] = Field(
        default_factory=dict
    )
    fallback_model_input_cost_per_million: float | None = None
    fallback_model_output_cost_per_million: float | None = None
    agent_evidence_batch_limit: Literal[1] = 1
    agent_release_report_path: str = ""

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
            fallback_values = (
                self.fallback_model_base_url.strip(),
                self.fallback_model_id.strip(),
                self.fallback_model_api_key.get_secret_value().strip(),
            )
            if any(fallback_values) and not all(fallback_values):
                raise ValueError(
                    "fallback model requires fallback_model_base_url, "
                    "fallback_model_id, fallback_model_api_key"
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
