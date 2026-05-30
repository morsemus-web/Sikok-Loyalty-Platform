from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://sikok:sikok@localhost:5432/sikok"
    jwt_secret: str = "change-me"
    telegram_bot_token: str = ""
    default_shop_id: int = 1
    debounce_seconds: int = 60
    discount_per_item: int = 100
    stamps_to_reward: int = 4
    # Indian Standard Time, used for once-per-day stamp gating and any user-facing dates.
    timezone_name: str = "Asia/Kolkata"
    ist_offset_minutes: int = 330  # IST = UTC+5:30

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
