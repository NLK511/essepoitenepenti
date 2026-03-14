from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    app_name: str = "Trade Proposer App"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    database_url: str = "sqlite:///./trade_proposer.db"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = "change-me"
    prototype_repo_path: str = "/home/aurelio/workspace/pi-mono"
    prototype_python_executable: str = "python3"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = AppSettings()
