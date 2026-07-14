from functools import lru_cache

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTOLAVA_", env_file=".env")

    environment: str = "development"
    database_url: str = "mysql+asyncmy://autolava:autolava@127.0.0.1/autolava"
    jwt_secret: SecretStr = SecretStr("development-only-secret")
    cookie_secure: bool = False
    cors_origins: list[str] = ["http://localhost:5173"]

    @model_validator(mode="after")
    def validate_production_credentials(self) -> "Settings":
        if self.environment.lower() != "production":
            return self
        secret = self.jwt_secret.get_secret_value().strip()
        weak_secret_markers = ("development", "example", "change-me", "changeme")
        if len(secret) < 32 or any(marker in secret.lower() for marker in weak_secret_markers):
            raise ValueError("production requires a random JWT secret of at least 32 characters")
        url = make_url(self.database_url)
        password = url.password or ""
        weak_passwords = {"", "autolava", "password", "root", "change-me", "changeme"}
        if password.lower() in weak_passwords or password == (url.username or ""):
            raise ValueError("production requires non-default database credentials")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
