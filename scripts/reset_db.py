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

def reset_database():
    print("=" * 70)
    print(" 🧹 RESETTING OMNISPIDER POSTGRESQL DATABASE")
    print("=" * 70)

    db = SessionLocal()
    try:
        num_leads = db.query(Lead).delete()
        num_tech = db.query(CompanyTechnology).delete()
        num_logs = db.query(ScrapeLog).delete()
        num_comp = db.query(Company).delete()

        db.commit()

        print(f"   • Deleted {num_leads} Lead records")
        print(f"   • Deleted {num_tech} Technology records")
        print(f"   • Deleted {num_logs} Scrape Log records")
        print(f"   • Deleted {num_comp} Company records")

        print("\nSUCCESS: All database tables cleared completely!")

    except Exception as e:
        db.rollback()
        print(f"\n❌ Error resetting database: {e}")
    finally:
        db.close()

    print("=" * 70)

if __name__ == "__main__":
    reset_database()
