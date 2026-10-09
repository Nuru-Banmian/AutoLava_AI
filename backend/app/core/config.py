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
    backup_ssh_host: str = ""
    backup_ssh_user: str = ""
    backup_ssh_directory: str = ""
    backup_ssh_key_file: Path | None = None
    backup_ssh_known_hosts_file: Path | None = None
    backup_restore_report_file: Path | None = None
    maintenance_timezone: str = "Europe/Rome"
    jwt_secret: SecretStr = SecretStr("development-only-secret")
    bootstrap_username: str = ""
    cookie_secure: bool = False
    cors_origins: list[str] = ["http://localhost:5173"]
    weather_max_inflight: int = Field(default=4, ge=1, le=32)
    # Each workload has its own deployment parameters. No paid model is selected implicitly.
    agent_chat_base_url: str = ""
    agent_chat_api_key: SecretStr = SecretStr("")
    agent_chat_model: str = ""
    agent_chat_enable_thinking: bool | None = False
    agent_memory_base_url: str = ""
    agent_memory_api_key: SecretStr = SecretStr("")
    agent_memory_model: str = ""
    agent_memory_enable_thinking: bool | None = None
    agent_memory_max_calls: int = Field(default=2, ge=1, le=3)
    agent_memory_timeout_seconds: float = Field(default=30, gt=0, le=120)
    agent_memory_context_chars: int = Field(default=18000, ge=8000, le=64000)
    agent_memory_output_chars: int = Field(default=4000, ge=500, le=8000)
    agent_memory_output_tokens: int = Field(default=8192, ge=1, le=8192)
    agent_embedding_base_url: str = ""
    agent_embedding_api_key: SecretStr = SecretStr("")
    agent_embedding_model: str = ""
    agent_embedding_dimensions: int | None = Field(default=None, ge=1)
    agent_embedding_timeout_seconds: float = Field(default=10, gt=0, le=30)
    # Empty path disables vector retrieval. Local storage permits only one process.
    agent_vector_path: Path | None = None
    agent_vector_url: str = ""
    agent_vector_api_key: SecretStr = SecretStr("")
    agent_vector_index_version: int = Field(default=1, ge=1)
    agent_index_max_attempts: int = Field(default=3, ge=1, le=5)
    agent_index_poll_seconds: float = Field(default=2, ge=0.1, le=60)
    agent_max_calls: int = Field(default=2, ge=1, le=3)
    agent_max_steps: int = Field(default=8, ge=1, le=12)
    agent_max_tool_calls: int = Field(default=8, ge=1, le=16)
    agent_timeout_seconds: float = Field(default=60, gt=0, le=180)
    # Full query/chart schemas, catalog and three small result pages need
    # headroom in addition to the protected answer/control reserve.
    agent_context_chars: int = Field(default=48000, ge=8000, le=64000)
    agent_output_chars: int = Field(default=16000, ge=1, le=32000)
    agent_output_tokens: int = Field(default=4096, ge=1, le=8192)

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
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
