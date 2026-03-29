from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    app_name: str = "Trade Proposer App"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    database_url: str = "sqlite:///./trade_proposer.db"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = "change-me"
    weights_file_path: str = ""
    run_stale_after_seconds: int = 1800
    single_user_auth_enabled: bool = True
    single_user_auth_token: str = "change-me"
    single_user_auth_allowlist_paths: str | None = None
    single_user_auth_username: str = "admin"
    single_user_auth_password: str = "change-me"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = AppSettings()
