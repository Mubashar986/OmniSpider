import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


from pathlib import Path

ENV_FILE_PATH = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    # Database
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "lead_gen_db"

    # Redis
    REDIS_URL: str = "rediss://default:password@localhost:6379"

    # Scraper Pipeline
    SCRAPE_COOLDOWN_DAYS: int = 7
    MAX_LINKS_PER_PAGE: int = 15

    # Dynamic Directory Domains (Issue #6)
    DIRECTORY_DOMAINS: str = "clutch.co,goodfirms.co,designrush.com,upcity.com,g2.com"

    # Path Blocklist (Issue #2)
    BLOCKLIST_PATTERNS: str = "cdn-cgi,wp-json,wp-admin,wp-includes,feed,xmlrpc.php,privacy,terms,advertise,get-listed,press-releases,blog,cookies,legal,sitemap,careers,faq"

    # Query Parameter Stripping (Issue #4)
    # NOTE: "page" must NOT be ignored — stripping it canonicalizes ?page=2 to the
    # page-1 URL and makes listing pagination unreachable (issue N4).
    IGNORED_QUERY_PARAMS: str = "utm_,fbclid,gclid,sort_by,location,project_cost,filter_by_service,verified,rating,review_sort,search"

    # DNS Servers for Email Verification (Issue #21)
    DNS_SERVERS: str = "8.8.8.8,1.1.1.1,9.9.9.9"

    # SMTP RCPT-TO Verification Stage (SRS section 4, WBS 3.1)
    SMTP_VERIFY_ENABLED: bool = True
    SMTP_PORT: int = 25
    SMTP_TIMEOUT: int = 10
    SMTP_HELO_DOMAIN: str = "omnispider-validator.local"
    SMTP_MAIL_FROM: str = "probe@omnispider-validator.local"

    # Per-Domain Politeness (replaces proxy rotation)
    PER_DOMAIN_MIN_INTERVAL: float = 3.0
    PER_DOMAIN_JITTER: float = 3.0

    # Phone Extraction & Tier-2 Engine
    PHONE_DEFAULT_REGION: str = "US"
    TIER2_HEADLESS: bool = True

    # Browser Fingerprint Pool (Issue #18)
    BROWSER_PROFILES: str = "chrome120,chrome124,chrome126"

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE_PATH),
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

    def get_directory_domains(self) -> List[str]:
        return [d.strip() for d in self.DIRECTORY_DOMAINS.split(",") if d.strip()]

    def get_blocklist_patterns(self) -> List[str]:
        return [p.strip() for p in self.BLOCKLIST_PATTERNS.split(",") if p.strip()]

    def get_ignored_query_params(self) -> tuple:
        return tuple(p.strip() for p in self.IGNORED_QUERY_PARAMS.split(",") if p.strip())

    def get_dns_servers(self) -> List[str]:
        return [s.strip() for s in self.DNS_SERVERS.split(",") if s.strip()]

    def get_browser_profiles(self) -> List[str]:
        return [p.strip() for p in self.BROWSER_PROFILES.split(",") if p.strip()]


settings = Settings()
