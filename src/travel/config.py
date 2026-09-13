from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class TravelSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRAVEL_", env_file=".env", extra="ignore")
    enabled: bool = False
    amap_key: SecretStr | None = None
    mcp_url: str | None = None
    mcp_token: SecretStr | None = None
    redis_url: str = "redis://localhost:6379/0"
    jobs_enabled: bool = False
    embedding_model: str | None = None
    cross_encoder_model: str | None = None
    query_expansion: bool = False


travel_settings = TravelSettings()
