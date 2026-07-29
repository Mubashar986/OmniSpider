import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.services.scrapers.tier2_cdp import Tier2CDPScraper

def main():
    print("Initializing Tier 2 Scraper (nodriver Direct-CDP over WebSocket)...")
    scraper = Tier2CDPScraper(headless=True)
    
    target_url = "https://nowsecure.nl"
    print(f"Fetching Cloudflare Turnstile benchmark target URL: {target_url}")
    
    result = scraper.fetch_page(target_url, timeout=30)
    
    print("\n--- Scrape Result Summary ---")
    print(f"URL: {result.url}")
    print(f"Engine Used: {result.engine_used}")
    print(f"Status Code: {result.status_code}")
    print(f"Is Blocked: {result.is_blocked}")
    print(f"Error Message: {result.error_message}")
    
    if result.status_code == 200 and not result.is_blocked:
        print("\n--- HTML Excerpt ---")
        print(result.html_content[:600])
        print("...")
        print("\nSUCCESS: Tier 2 Scraper (nodriver) successfully bypassed Cloudflare Turnstile & rendered DOM!")
    else:
        print("\nFAILURE: Tier 2 Scraper was unable to render page or hit error.")

if __name__ == "__main__":
    main()
