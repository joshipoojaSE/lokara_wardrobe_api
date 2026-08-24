from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "lokara-wardrobe"
    environment: str = "local"
    debug: bool = False

    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = ["*"]

    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/lokara_wardrobe"
    )
    test_database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/lokara_wardrobe_test"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
