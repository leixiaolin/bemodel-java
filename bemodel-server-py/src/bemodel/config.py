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
    ontology_analysis_interval_seconds: int = Field(10, validation_alias="BEMODEL_ONTOLOGY_ANALYSIS_INTERVAL_SECONDS")
    ontology_analysis_lock_seconds: int = Field(300, validation_alias="BEMODEL_ONTOLOGY_ANALYSIS_LOCK_SECONDS")
    ontology_analysis_max_attempts: int = Field(3, validation_alias="BEMODEL_ONTOLOGY_ANALYSIS_MAX_ATTEMPTS")
    ontology_analysis_chunk_tables: int = Field(8, validation_alias="BEMODEL_ONTOLOGY_ANALYSIS_CHUNK_TABLES")
    ontology_analysis_timeout_seconds: int = Field(120, ge=1, le=240, validation_alias="BEMODEL_ONTOLOGY_ANALYSIS_TIMEOUT_SECONDS")
    ontology_stats_timeout_seconds: int = Field(5, validation_alias="BEMODEL_ONTOLOGY_STATS_TIMEOUT_SECONDS")
    ontology_stats_max_columns: int = Field(80, validation_alias="BEMODEL_ONTOLOGY_STATS_MAX_COLUMNS")
    ontology_stats_enum_limit: int = Field(20, validation_alias="BEMODEL_ONTOLOGY_STATS_ENUM_LIMIT")


settings = Settings()
