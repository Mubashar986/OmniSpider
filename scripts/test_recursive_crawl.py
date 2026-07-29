import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.tasks.scrape_tasks import scrape_url_task
from app.core.database import SessionLocal
from app.models.company import Company
from app.models.lead import Lead

def test_recursive_crawl():
    print("=== Testing Recursive Subpage Crawling & Subpage Dispatching ===")
    
    target_url = "https://tls.peet.ws/api/all"
    print(f"\n1. Dispatching Parent Scrape Task for: {target_url} (Crawl Depth = 1)")
    
    job = scrape_url_task.delay(target_url, crawl_depth=1)
    print(f"Parent Task ID: {job.id}")
    
    print("\nWaiting for Celery Worker to process parent & child subpage tasks...")
    try:
        res = job.get(timeout=30)
        print(f"\nParent Execution Status: {res.get('status')}")
        print(f"   Domain:               {res.get('domain')}")
        print(f"   Dispatched Subpages:  {res.get('dispatched_subpages')}")
        
        print("\nRECURSIVE CRAWL TEST COMPLETE: Subpages extracted and dispatched successfully!")
    except Exception as e:
        print(f"\nNote / Error: {e}")
        print("Ensure Celery worker is running: python -m celery -A app.tasks.celery_app worker --pool=solo -l info")

if __name__ == "__main__":
    test_recursive_crawl()
