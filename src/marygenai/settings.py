from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MARYGENAI_", extra="ignore")

    data_dir: Path = Field(default=Path("data"))
    temp_dir: Path = Field(default=Path("temp"))
    mcp_bearer_token_sha256: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
