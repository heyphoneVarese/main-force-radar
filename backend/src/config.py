from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        # 关键:shell 里设了空字符串的环境变量(如 ANTHROPIC_API_KEY=)
        # 不应覆盖 .env 里的真值。Docker / VPS 默认空值同理。
        env_ignore_empty=True,
    )

    database_url: str = "sqlite:///./main_force_radar.db"
    anthropic_api_key: str = ""
    server_chan_sckey: str = ""


settings = Settings()
