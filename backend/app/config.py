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
    telephony_mock_mode: bool = True  # Exotel: IVR now, outbound TTS calls later
    email_mock_mode: bool = True  # false needs the SMTP_* block below

    # Only read when whatsapp_mock_mode is false.
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_api_version: str = "v21.0"
    # JSON: {"otp": {"name": "setu_otp", "lang": "en", "params": ["code"]}}. A message
    # named here goes as an approved template and works cold; anything else goes as
    # free-form text, which Meta only allows inside the 24h customer-service window.
    whatsapp_templates: str = ""

    # Only read when email_mock_mode is false (D10: no flag that does nothing).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_timeout_seconds: int = 10

    # The demo needs one patient whose address you can actually receive mail at.
    # Applied by `make seed` to the first seeded patient; empty leaves every patient
    # without an email, which is the honest default.
    demo_patient_email: str = ""

    # .env.example also lists the remaining *_MOCK_MODE flags; those arrive with their
    # adapters.


@lru_cache
def get_settings() -> Settings:
    return Settings()
