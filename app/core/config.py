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

    # S3 image storage. The bucket stays private; reads go through presigned URLs.
    s3_bucket: str = "lokara-wardrobe"
    s3_region: str = "ap-south-1"
    s3_endpoint_url: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    s3_presign_expiry_seconds: int = 3600

    image_max_bytes: int = 50 * 1024 * 1024 
    image_max_count: int = 8
    image_allowed_content_types: list[str] = [
        "image/jpeg",
        "image/png",
        "image/webp",
    ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
