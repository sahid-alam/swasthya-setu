import logging
from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("swasthya.config")

# Credentials that can never legitimately contain whitespace. A token copied out of
# BotFather across a line wrap, or a Gmail app password shown in groups of four, both
# arrive with spaces in them and both fail with an error that names nothing useful —
# Telegram answers a token with a space in it with a bare 404.
NO_WHITESPACE = (
    "telegram_bot_token",
    "whatsapp_token",
    "vapi_private_key",
    "vapi_public_key",
    "smtp_password",
    "sms_gateway_token",
)


class Settings(BaseSettings):
    # Both, later wins: the repo-root .env is the one a human edits, and `backend/.env`
    # stays available for a machine-specific override. Without the first, running
    # uvicorn from backend/ silently ignores the file the README tells you to fill in.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    database_url: str = "postgresql+asyncpg://setu:setu@localhost:5432/swasthya"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "change-me"
    # Seeded staff login. Empty means `make seed` generates one and writes it to the
    # gitignored .admin-password — a password committed to a repo is not a password.
    admin_password: str = ""
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
    telegram_mock_mode: bool = True  # false needs TELEGRAM_BOT_TOKEN

    # Only read when sms_mock_mode is false: an Android running the Traccar SMS
    # Gateway app, reachable on the LAN (never localhost from inside compose).
    sms_gateway_url: str = ""
    sms_gateway_token: str = ""

    # Only read when telegram_mock_mode is false.
    telegram_bot_token: str = ""
    telegram_bot_username: str = "Swasthya_Setu_bot"

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

    # Vapi voice agent. The private key is server-side (creating assistants, and the
    # only one that can spend money); the public key is the browser's and is safe in
    # the bundle. Alias list because the key was set before this name existed.
    vapi_private_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "VAPI_PRIVATE_KEY",
            "VAPI_API",
            "VAPI_API_KEY",
            "VAPI_KEY",
            "VAPI_TOKEN",
            "vapi_private_key",
        ),
    )
    vapi_public_key: str = ""
    # Vapi accepted these on the create call, which is the only validation available —
    # there is no voice-list endpoint on this API version. Change them here rather than
    # in code when you want a different voice.
    vapi_voice_provider: str = "vapi"
    vapi_voice_id: str = "Elliot"
    vapi_assistant_id: str = ""  # written by infra/vapi_setup.py, then set here
    # Vapi calls our tools from its own servers, so this must be reachable from the
    # internet. Empty means the assistant is created without server tools — it can
    # talk, it just cannot book (Iron Rule 4: the IVR path still books with no internet).
    public_base_url: str = ""
    # Vapi sends this on every tool call; without it the endpoint refuses to be wired.
    vapi_tool_secret: str = ""

    # The demo needs one patient whose address you can actually receive mail at.
    # Applied by `make seed` to the first seeded patient; empty leaves every patient
    # without an email, which is the honest default.
    demo_patient_email: str = ""

    # .env.example also lists the remaining *_MOCK_MODE flags; those arrive with their
    # adapters.

    @field_validator(*NO_WHITESPACE, mode="after")
    @classmethod
    def _strip_whitespace(cls, value: str, info) -> str:
        cleaned = "".join(value.split())
        if cleaned != value:
            # Repaired, not hidden: silently fixing it would leave .env wrong forever.
            log.warning("%s contained whitespace; stripped it", info.field_name.upper())
        return cleaned


@lru_cache
def get_settings() -> Settings:
    return Settings()
