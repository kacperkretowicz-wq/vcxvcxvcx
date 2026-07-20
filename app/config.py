from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    check_times: str = "07:30,13:30,20:30"
    price_drop_threshold_pct: float = 10.0
    price_drop_renotify_pct: float = 5.0
    database_path: str = "data/app.db"
    log_path: str = "data/app.log"

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_to: str = ""

    @property
    def check_times_list(self) -> list[str]:
        return [t.strip() for t in self.check_times.split(",") if t.strip()]

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def smtp_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_to)


settings = Settings()
