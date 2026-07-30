import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "lead_gen_db"
    
    REDIS_URL: str = "rediss://default:password@localhost:6379"
    SCRAPE_COOLDOWN_DAYS: int = 7

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    @property
    def REDIS_URL_FORMATTED(self) -> str:
        url = self.REDIS_URL
        if url.startswith("rediss://") and "ssl_cert_reqs" not in url:
            delimiter = "&" if "?" in url else "?"
            url = f"{url}{delimiter}ssl_cert_reqs=none"
        return url

settings = Settings()
