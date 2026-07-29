from typing import Optional, Dict
from curl_cffi import requests
from app.services.scrapers.base import ScrapeResult

class Tier1HTTPScraper:
    """
    Tier 1 Scraper using curl_cffi to spoof browser TLS/JA3/JA4 fingerprints.
    Provides fast HTTP request fetching without browser overhead.
    """
    def __init__(self, default_impersonate: str = "chrome120"):
        self.default_impersonate = default_impersonate

    def fetch_page(
        self,
        url: str,
        timeout: int = 15,
        impersonate: Optional[str] = None,
        proxies: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> ScrapeResult:
        target_impersonate = impersonate or self.default_impersonate
        custom_headers = headers or {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        }
        
        try:
            response = requests.get(
                url,
                impersonate=target_impersonate,
                headers=custom_headers,
                timeout=timeout,
                proxies=proxies,
                allow_redirects=True
            )
            
            # Check for WAF / Cloudflare blockage indicators
            is_blocked = (
                response.status_code in (403, 429, 503) or
                "Just a moment..." in response.text or
                "Attention Required! | Cloudflare" in response.text or
                "cf-browser-verification" in response.text
            )
            
            return ScrapeResult(
                url=url,
                status_code=response.status_code,
                headers=dict(response.headers),
                html_content=response.text,
                engine_used="curl_cffi",
                is_blocked=is_blocked
            )
        except Exception as e:
            return ScrapeResult(
                url=url,
                status_code=0,
                headers={},
                html_content="",
                engine_used="curl_cffi",
                is_blocked=True,
                error_message=str(e)
            )
