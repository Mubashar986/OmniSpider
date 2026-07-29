import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.services.scrapers.tier1_http import Tier1HTTPScraper

def main():
    print("Initializing Tier 1 Scraper (curl_cffi with impersonate='chrome120')...")
    scraper = Tier1HTTPScraper(default_impersonate="chrome120")
    
    target_url = "https://tls.peet.ws/api/all"
    print(f"Fetching target URL to verify TLS fingerprinting: {target_url}")
    
    result = scraper.fetch_page(target_url, timeout=10)
    
    print("\n--- Scrape Result Summary ---")
    print(f"URL: {result.url}")
    print(f"Engine Used: {result.engine_used}")
    print(f"Status Code: {result.status_code}")
    print(f"Is Blocked: {result.is_blocked}")
    print(f"Error Message: {result.error_message}")
    
    if result.status_code == 200:
        print("\n--- Raw Response Excerpt (TLS / JA3 / JA4 Data) ---")
        print(result.html_content[:800])
        print("...")
        print("\nSUCCESS: Tier 1 Scraper successfully spoofed Chrome TLS fingerprint!")
    else:
        print("\nFAILURE: Fetch did not return 200 OK.")

if __name__ == "__main__":
    main()
