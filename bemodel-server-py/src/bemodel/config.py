from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_database: str = "bemodel_platform"
    mysql_username: str = ""
    mysql_password: str = ""
    jwt_secret: str = ""
    app_secret_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_timeout_seconds: int = 30
    inspect_cron: str = Field("0 0/30 * * * *", validation_alias="BEMODEL_INSPECT_CRON")
    disable_scheduler: bool = Field(False, validation_alias="BEMODEL_DISABLE_SCHEDULER")


settings = Settings()
