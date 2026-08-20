from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://setu:setu@localhost:5432/swasthya"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "change-me"
    jwt_ttl_minutes: int = 12 * 60
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:4173"]

    # Demo time-compression. Presence decay constants divide by this, so a compressed
    # day ages signals at the same rate relative to simulated time.
    sim_speed: int = 1
    # How often presence is re-fused with no new signal arriving. This is what makes a
    # dead beacon decay instead of sitting on a stale PRESENT. 0 disables (tests).
    presence_sweep_seconds: int = 20

    # Adapters default to mock (Iron Rule 1). Declared here because the factory reads
    # them — a flag in this class is a flag that actually does something.
    sms_mock_mode: bool = True
    whatsapp_mock_mode: bool = True

    # .env.example also lists COUCHDB_URL and the remaining *_MOCK_MODE flags; those
    # arrive with their adapters.


@lru_cache
def get_settings() -> Settings:
    return Settings()
