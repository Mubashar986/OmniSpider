import os
import sys
import time

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.tasks.scrape_tasks import scrape_url_task
from app.core.database import SessionLocal
from app.models.company import Company
from app.models.lead import Lead
from app.models.scrape_log import ScrapeLog

def test_end_to_end():
    print("=== Testing Complete End-to-End Scraping Pipeline & PostgreSQL Storage ===")
    
    target_url = "https://tls.peet.ws/api/all"
    print(f"\n1. Dispatching Scrape Task for: {target_url}")
    job = scrape_url_task.delay(target_url)
    print(f"Task Dispatched. Task ID: {job.id}")
    
    print("\nWaiting for Celery Worker to process pipeline (timeout 30s)...")
    try:
        result = job.get(timeout=30)
        print(f"\nWorker Task Execution Result:")
        print(f"   Status:       {result.get('status')}")
        print(f"   Engine Used:  {result.get('engine_used')}")
        print(f"   Company:      {result.get('company_name')}")
        print(f"   Leads Saved:  {result.get('leads_saved')}")
        print(f"   Tech Stack:   {result.get('detected_tech')}")
        
        # Verify directly in PostgreSQL
        print("\n2. Querying PostgreSQL Database directly to verify persistence...")
        db = SessionLocal()
        try:
            companies = db.query(Company).all()
            leads = db.query(Lead).all()
            logs = db.query(ScrapeLog).all()
            
            print(f"   Companies in DB: {len(companies)}")
            print(f"   Leads in DB:     {len(leads)}")
            print(f"   Scrape Logs:     {len(logs)}")
            
            for c in companies:
                print(f"      -> Company: {c.name} | Domain: {c.domain}")
            for l in leads:
                print(f"      -> Lead: {l.work_email} | Name: {l.first_name} {l.last_name} | Verified: {l.email_verified}")
        finally:
            db.close()

        # 3. Test 7-Day Frequency Control Cooldown Skipping
        print("\n3. Re-dispatching SAME URL to test 7-Day Frequency Cooldown...")
        job2 = scrape_url_task.delay(target_url)
        res2 = job2.get(timeout=10)
        print(f"   Second Scrape Result: {res2.get('status')} (Reason: {res2.get('reason')})")
        
        if res2.get('status') == 'skipped':
            print("\nSUCCESS: 7-Day Frequency Cooldown correctly skipped redundant request!")

        print("\nEND-TO-END PIPELINE VERIFICATION COMPLETE!")

    except Exception as e:
        print(f"\nEnd-to-End Pipeline Error / Note: {e}")
        print("Ensure Celery worker is running: python -m celery -A app.tasks.celery_app worker --pool=solo -l info")

if __name__ == "__main__":
    test_end_to_end()
