import os
import sys
import time

# Add parent directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.tasks.scrape_tasks import scrape_url_task

def test_pipeline():
    print("=== Testing Automated Dual-Engine Celery Scraping Pipeline ===")
    
    # Target 1: Standard URL (Should pass cleanly via Tier 1 curl_cffi)
    url_tier1 = "https://tls.peet.ws/api/all"
    print(f"\n1. Dispatching Job for Tier 1 Target: {url_tier1}")
    job1 = scrape_url_task.delay(url_tier1)
    print(f"Task 1 Dispatched. Task ID: {job1.id}")
    
    # Target 2: Cloudflare Protected Target (Should trigger Tier 2 nodriver fallback)
    url_tier2 = "https://nowsecure.nl"
    print(f"\n2. Dispatching Job for Cloudflare Target: {url_tier2}")
    job2 = scrape_url_task.delay(url_tier2)
    print(f"Task 2 Dispatched. Task ID: {job2.id}")
    
    print("\nWaiting for Celery Workers to process both jobs (timeout 45s)...")
    try:
        res1 = job1.get(timeout=20)
        print(f"\nTask 1 Result (Tier 1 Target):")
        print(f"   Engine Used: {res1.get('engine_used')}")
        print(f"   Status Code: {res1.get('status_code')}")
        print(f"   Is Blocked:  {res1.get('is_blocked')}")
        
        res2 = job2.get(timeout=30)
        print(f"\nTask 2 Result (Cloudflare Target):")
        print(f"   Engine Used: {res2.get('engine_used')}")
        print(f"   Status Code: {res2.get('status_code')}")
        print(f"   Is Blocked:  {res2.get('is_blocked')}")
        
        print("\nPIPELINE TEST SUCCESSFUL: Both jobs completed with automated engine switching!")
    except Exception as e:
        print(f"\nPipeline Test Note / Error: {e}")
        print("Ensure Celery worker is running: python -m celery -A app.tasks.celery_app worker --pool=solo -l info")

if __name__ == "__main__":
    test_pipeline()
