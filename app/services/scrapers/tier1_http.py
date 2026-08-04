import random
import re
from typing import Optional, Dict
from curl_cffi import requests
from bs4 import BeautifulSoup

from app.core.config import settings
from app.services.scrapers.base import ScrapeResult, detect_soft_404

class Tier1HTTPScraper:
    """
    Tier 1 Scraper using curl_cffi to spoof browser TLS/JA3/JA4 fingerprints.
    Provides fast HTTP request fetching without browser overhead.
    """
    def __init__(self, default_impersonate: Optional[str] = None):
        self.default_impersonate = default_impersonate

    def fetch_page(
        self,
        url: str,
        timeout: int = 15,
        impersonate: Optional[str] = None,
        proxies: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> ScrapeResult:
        # Issue 18: Rotate TLS impersonation profiles from settings pool
        browser_profiles = settings.get_browser_profiles()
        target_impersonate = impersonate or self.default_impersonate or (
            random.choice(browser_profiles) if browser_profiles else "chrome120"
        )

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
            
            # Issue 19: Content-based WAF Challenge Detection Heuristic
            # Checks status codes, string signatures, and DOM structure (empty body with challenge title)
            html_text = response.text or ""
            is_blocked = response.status_code in (403, 429, 503)
            
            if not is_blocked:
                # Signature matching
                waf_signatures = ["Just a moment...", "Attention Required! | Cloudflare", "cf-browser-verification", "Ray ID:", "Please enable Cookies", "Access Denied"]
                if any(sig in html_text for sig in waf_signatures):
                    is_blocked = True
                else:
                    # Content heuristic: Title indicates block/captcha and body contains zero main links/data
                    try:
                        soup = BeautifulSoup(html_text, "html.parser")
                        title = (soup.title.string if soup.title else "").lower()
                        if any(w in title for w in ["block", "verify", "captcha", "security check", "robot"]):
                            # Check if page lacks substantive content
                            links = soup.find_all("a")
                            if len(links) < 3:
                                is_blocked = True
                    except Exception:
                        pass

            # Soft-404: 200 OK pages that are actually missing (issue: dead profiles
            # persisted as real companies). Only checked on unblocked successes.
            soft_404 = response.status_code == 200 and not is_blocked and detect_soft_404(html_text)

            return ScrapeResult(
                url=url,
                status_code=response.status_code,
                headers=dict(response.headers),
                html_content=response.text,
                engine_used=f"curl_cffi:{target_impersonate}",
                is_blocked=is_blocked,
                extra_meta={"soft_404": True} if soft_404 else {},
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

