import asyncio
import logging
from typing import Optional, Dict, Any
import nodriver as uc
from app.services.scrapers.base import ScrapeResult

logger = logging.getLogger(__name__)

class Tier2CDPScraper:
    """
    Tier 2 Scraper using nodriver (Direct Chrome DevTools Protocol over WebSockets).
    Provides an unblockable fallback engine for Cloudflare Turnstile, JS rendering, and SPA pages.
    """
    def __init__(self, headless: bool = True):
        self.headless = headless

    async def fetch_page_async(
        self,
        url: str,
        timeout: int = 30,
        wait_for_seconds: int = 4
    ) -> ScrapeResult:
        browser = None
        try:
            logger.info(f"Launching nodriver Chrome instance (headless={self.headless})...")
            browser = await uc.start(
                headless=self.headless,
                browser_args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-accelerated-2d-canvas",
                    "--disable-gpu",
                    "--blink-settings=imagesEnabled=false",  # Block images to save bandwidth
                ]
            )
            
            logger.info(f"Navigating via WebSocket CDP to: {url}")
            page = await browser.get(url)
            
            # Allow time for JS execution / Turnstile verification
            await asyncio.sleep(wait_for_seconds)
            
            # Extract rendered HTML content
            html_content = await page.get_content()
            
            # Check for Cloudflare block / unsolved challenge
            is_blocked = (
                "Just a moment..." in html_content and "Cloudflare" in html_content
            )
            
            return ScrapeResult(
                url=url,
                status_code=200 if not is_blocked else 403,
                headers={},
                html_content=html_content,
                engine_used="nodriver",
                is_blocked=is_blocked
            )
        except Exception as e:
            import traceback
            logger.error(f"Tier 2 CDP Scraping Error on {url}: {e}\n{traceback.format_exc()}")
            return ScrapeResult(
                url=url,
                status_code=0,
                headers={},
                html_content="",
                engine_used="nodriver",
                is_blocked=True,
                error_message=f"{e}\n{traceback.format_exc()}"
            )
        finally:
            if browser:
                try:
                    await asyncio.sleep(0.2)  # Drain WebSocket pipes gracefully before loop teardown
                    browser.stop()
                except Exception as clean_err:
                    logger.debug(f"Browser stop exception: {clean_err}")

    def fetch_page(self, url: str, timeout: int = 30) -> ScrapeResult:
        """Synchronous wrapper for Celery task compatibility."""
        return asyncio.run(self.fetch_page_async(url, timeout=timeout))
