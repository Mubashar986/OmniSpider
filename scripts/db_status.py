import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from app.core.database import SessionLocal
from app.models.company import Company
from app.models.lead import Lead
from app.models.technology import CompanyTechnology
from app.models.scrape_log import ScrapeLog

def show_database_status():
    print("=" * 70)
    print(" 🗄️ OMNISPIDER POSTGRESQL DATABASE INSPECTOR")
    print("=" * 70)

    db = SessionLocal()
    try:
        companies = db.query(Company).all()
        leads = db.query(Lead).all()
        technologies = db.query(CompanyTechnology).all()
        logs = db.query(ScrapeLog).order_by(ScrapeLog.scraped_at.desc()).limit(10).all()

        print(f"\n📊 DATABASE SUMMARY:")
        print(f"   • Total Companies:    {len(companies)}")
        print(f"   • Total Leads:        {len(leads)}")
        print(f"   • Total Tech Stack:   {len(technologies)}")
        print(f"   • Recent Scrape Logs: {len(logs)}")

        if companies:
            print("\n🏢 SAVED COMPANIES:")
            print("-" * 70)
            for c in companies:
                print(f"   [ID: {c.id}] {c.name} ({c.domain}) | {c.website_url}")

        if leads:
            print("\n👥 SAVED LEADS:")
            print("-" * 70)
            for idx, l in enumerate(leads, 1):
                ver_status = "✓ Deliverable" if l.email_verified else "✗ Unverified"
                name_str = f"{l.first_name or ''} {l.last_name or ''}".strip() or "N/A"
                print(f"   [{idx}] {name_str}")
                print(f"       Email:      {l.work_email} ({ver_status})")
                print(f"       Phones:     {l.phones}")
                if l.linkedin_url:
                    print(f"       LinkedIn:   {l.linkedin_url}")

        if logs:
            print("\n📜 RECENT SCRAPE LOGS (Last 10):")
            print("-" * 70)
            for log in logs:
                print(f"   • [{log.scraped_at.strftime('%Y-%m-%d %H:%M:%S')}] {log.domain} | Engine: {log.engine_used} | Status: {log.status_code}")

    except Exception as e:
        print(f"\n❌ Error querying database: {e}")
    finally:
        db.close()

    print("\n" + "=" * 70)

if __name__ == "__main__":
    show_database_status()
