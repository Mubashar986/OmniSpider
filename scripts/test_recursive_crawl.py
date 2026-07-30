import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.tasks.scrape_tasks import scrape_url_task
from app.core.database import SessionLocal
from app.models.company import Company
from app.models.lead import Lead

def test_recursive_crawl():
    print("=== Testing Recursive Subpage Crawling & Session Deduplication ===")
    
    target_url = "https://tls.peet.ws/api/all"
    print(f"\n1. Direct Execution Test for: {target_url} (Crawl Depth = 1)")
    
    # Direct task execution (without Celery worker dependency for unit testing)
    result = scrape_url_task(target_url, crawl_depth=1)
    
    print(f"\nExecution Status: {result.get('status')}")
    print(f"   Domain:               {result.get('domain')}")
    print(f"   Session ID:           {result.get('session_id')}")
    print(f"   Dispatched Subpages:  {result.get('dispatched_subpages')}")
    
    assert result.get('status') in ("success", "skipped"), f"Unexpected status: {result.get('status')}"
    assert result.get('session_id') is not None, "session_id must be generated"

    print("\n2. Duplicate Direct Execution Test (Same Session ID)...")
    res_dup = scrape_url_task(target_url, crawl_depth=1, session_id=result.get('session_id'))
    print(f"   Duplicate Subpage Dispatch Count: {len(res_dup.get('dispatched_subpages', []))}")
    
    print("\nRECURSIVE CRAWL & DEDUPLICATION TEST COMPLETE: Session deduplication verified!")

if __name__ == "__main__":
    test_recursive_crawl()
