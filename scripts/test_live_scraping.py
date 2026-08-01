import sys
import os
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from app.tasks.scrape_tasks import scrape_url_task
from app.core.database import SessionLocal
from app.models.company import Company
from app.models.lead import Lead

def test_real_live_scrape():
    test_urls = [
        "https://clutch.co/profile/openxcell",
        "https://www.goodfirms.co/company/jploft"
    ]
    
    print("=" * 70)
    print("STARTING LIVE SCRAPE VERIFICATION TEST")
    print("=" * 70)
    
    for url in test_urls:
        print(f"\n---> Executing Live Scrape for: {url}")
        result = scrape_url_task.apply(args=[url]).get()
        print(f"Task Execution Result Status: {result.get('status')}")
        print(f"Engine Used: {result.get('engine_used')}")
        print(f"Target Company Saved: {result.get('company_name')} (Domain: {result.get('domain')})")
        print(f"Leads Extracted Count: {result.get('leads_saved')}")

    print("\n" + "=" * 70)
    print("VERIFYING POSTGRESQL DATABASE ENTITIES")
    print("=" * 70)
    
    db = SessionLocal()
    try:
        companies = db.query(Company).order_by(Company.created_at.desc()).limit(5).all()
        print(f"\nRecent Companies in Database ({len(companies)} found):")
        for c in companies:
            print(f"  - Domain: {c.domain} | Name: {c.name} | Industry: {c.industry} | Size: {c.company_size} | Website: {c.website_url}")
            
        leads = db.query(Lead).order_by(Lead.created_at.desc()).limit(10).all()
        print(f"\nRecent Leads in Database ({len(leads)} found):")
        for l in leads:
            print(f"  - Email: {l.work_email} | Name: {l.first_name} {l.last_name} | Title: {l.title} | Verified: {l.email_verified}")

    finally:
        db.close()

if __name__ == "__main__":
    test_real_live_scrape()
