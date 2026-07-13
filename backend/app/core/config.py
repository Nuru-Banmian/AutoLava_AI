from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTOLAVA_", env_file=".env")

    environment: str = "development"
    database_url: str = "mysql+asyncmy://autolava:autolava@127.0.0.1/autolava"
    jwt_secret: SecretStr = SecretStr("development-only-secret")
    cookie_secure: bool = False
    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
