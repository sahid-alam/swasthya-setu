from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://setu:setu@localhost:5432/swasthya"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "change-me"
    jwt_ttl_minutes: int = 12 * 60
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:4173"]

    # .env.example also lists COUCHDB_URL, SIM_SPEED and the per-service *_MOCK_MODE
    # flags. They are declared here only when something reads them, so a flag that
    # appears in this class is a flag that actually does something.


@lru_cache
def get_settings() -> Settings:
    return Settings()
