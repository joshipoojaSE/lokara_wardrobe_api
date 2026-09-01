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

    # Vision analysis. `openai_api_key` may stay unset: the SDK then falls back
    # to OPENAI_API_KEY in the environment.
    openai_api_key: str | None = None
    analysis_enabled: bool = True
    analysis_model: str = "gpt-5.5"
    # Reasoning-model only. Blank it out for a non-reasoning model like gpt-4o.
    analysis_effort: str = "medium"
    analysis_max_output_tokens: int = 16000
    analysis_timeout_seconds: float = 180.0
    # Extra views of the same garment sharpen the read but cost tokens.
    analysis_max_images: int = 4

    # Similarity search. Shares `openai_api_key` with the vision analysis above.
    # The vector width is not configurable here: it is fixed by the column, as
    # `EMBEDDING_DIMENSIONS` in app/models/analysis.py.
    embeddings_enabled: bool = True
    embedding_model: str = "text-embedding-3-small"
    embedding_timeout_seconds: float = 30.0

    # Grounded answers over search results. Shares
    # `openai_api_key` with the two services above.
    answers_enabled: bool = True
    answer_model: str = "gpt-5.5"
    # Reasoning-model only. Blank it out for a non-reasoning model like gpt-4o.
    answer_effort: str = "low"
    answer_max_output_tokens: int = 4000
    answer_timeout_seconds: float = 90.0
    # How many of the retrieved items are rendered into the prompt. More context
    # costs tokens on every answered search and gives the model more near-misses
    # to sift; the answer only ever cites what is in this window.
    answer_context_items: int = 5

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
