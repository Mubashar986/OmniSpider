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

def test_crunchbase_scrape(url: str):
    print("=== Testing Lead Scraper Pipeline on Crunchbase ===")
    print(f"Target Crunchbase URL: {url}")
    
    print("\n1. Dispatching Scrape Task to Celery queue...")
    job = scrape_url_task.delay(url)
    print(f"Task Dispatched. Task ID: {job.id}")
    
    print("\nWaiting for Celery Worker (Tier 1 -> Tier 2 Fallback) to process (timeout 45s)...")
    try:
        result = job.get(timeout=45)
        print(f"\nWorker Task Execution Result:")
        print(f"   Status:       {result.get('status')}")
        print(f"   Engine Used:  {result.get('engine_used')}")
        print(f"   Domain:       {result.get('domain')}")
        print(f"   Company:      {result.get('company_name')}")
        print(f"   Leads Saved:  {result.get('leads_saved')}")
        print(f"   Tech Stack:   {result.get('detected_tech')}")
        
        if result.get('status') == 'success':
            print("\n2. Querying PostgreSQL to inspect saved Crunchbase record...")
            db = SessionLocal()
            try:
                company = db.query(Company).filter(Company.domain == result.get('domain')).first()
                if company:
                    print(f"   Saved Company: {company.name}")
                    print(f"   Domain:        {company.domain}")
                    print(f"   Website URL:   {company.website_url}")
                    
                    leads = db.query(Lead).filter(Lead.company_id == company.id).all()
                    print(f"   Associated Leads Extracted: {len(leads)}")
                    for idx, lead in enumerate(leads, 1):
                        print(f"      Lead #{idx}: {lead.first_name} {lead.last_name} | {lead.work_email} | Verified: {lead.email_verified}")
            finally:
                db.close()
                
            print("\nCRUNCHBASE TEST COMPLETED SUCCESSFULLY!")
        else:
            print(f"\nNotice: Task returned status '{result.get('status')}'. Reason: {result.get('reason') or result.get('error')}")

    except Exception as e:
        print(f"\nExecution Note / Error: {e}")
        print("Ensure Celery worker is running: python -m celery -A app.tasks.celery_app worker --pool=solo -l info")

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "https://www.crunchbase.com/organization/stripe"
    test_crunchbase_scrape(target)
