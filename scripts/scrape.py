import os
import sys
import argparse
from typing import List

# Add parent directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from app.tasks.scrape_tasks import scrape_url_task
from app.core.database import SessionLocal
from app.models.company import Company
from app.models.lead import Lead

def run_generic_scraper(urls: List[str], force_tier: str = None, crawl_depth: int = 0, enable_cooldown: bool = False):
    print("=" * 70)
    print(" 🚀 UNBLOCKABLE MULTI-TIER LEAD GENERATION SCRAPER")
    print("=" * 70)
    print(f"Target URLs to process: {len(urls)}")
    print(f"Recursive Crawl Depth: {crawl_depth}")
    if force_tier:
        print(f"Forced Engine Tier:     {force_tier}")
    if enable_cooldown:
        print(f"Cooldown Check:        Enabled (--cooldown)")
    else:
        print(f"Cooldown Check:        Disabled (Fresh Fetch Every Time)")
    print("-" * 70)

    for idx, target_url in enumerate(urls, 1):
        url = target_url.strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            url = f"https://{url}"

        print(f"\n[{idx}/{len(urls)}] Dispatching Scrape Job for: {url}")
        
        # Dispatch to Celery queue
        job = scrape_url_task.delay(url, force_tier=force_tier, crawl_depth=crawl_depth, enable_cooldown=enable_cooldown)
        print(f"   Task ID: {job.id}")
        print("   Waiting for Celery worker (Tier 1 HTTP -> Tier 2 CDP Fallback)...")

        try:
            result = job.get(timeout=45)
            status = result.get("status")

            print("\n   --- Scrape Task Result ---")
            print(f"   Status:       {status.upper()}")
            print(f"   Engine Used:  {result.get('engine_used', 'N/A')}")
            print(f"   Domain:       {result.get('domain', 'N/A')}")
            print(f"   Company:      {result.get('company_name', 'N/A')}")
            print(f"   Leads Saved:  {result.get('leads_saved', 0)}")
            print(f"   Tech Stack:   {result.get('detected_tech', [])}")

            subpages = result.get("dispatched_subpages", [])
            if subpages:
                print(f"\n   Dispatched Subpages ({len(subpages)}):")
                for sub in subpages:
                    print(f"      -> {sub}")
                print("\n   ⏳ Waiting for Celery worker to process subpage tasks (10s delay)...")
                import time
                time.sleep(10)

            if status == "skipped":
                print(f"   Reason:       {result.get('reason')}")

            elif status in ("success", "failed"):
                db = SessionLocal()
                try:
                    domain = result.get("domain")
                    comp = db.query(Company).filter(Company.domain == domain).first() if domain else None
                    if comp:
                        leads = db.query(Lead).filter(Lead.company_id == comp.id).all()
                        print("\n   ====================================================")
                        print(f"   📊 ALL EXTRACTED LEADS IN POSTGRESQL FOR {domain.upper()} ({len(leads)})")
                        print("   ====================================================")
                        if leads:
                            for l_idx, lead in enumerate(leads, 1):
                                verified_tag = "✓ Deliverable" if lead.email_verified else "✗ Unverified"
                                name_str = f"{lead.first_name or ''} {lead.last_name or ''}".strip() or "N/A"
                                print(f"      [{l_idx}] {name_str}")
                                print(f"          Email:      {lead.work_email} ({verified_tag})")
                                print(f"          Phones:     {lead.phones}")
                                if lead.linkedin_url:
                                    print(f"          LinkedIn:   {lead.linkedin_url}")
                        else:
                            print("      No leads saved for this domain yet.")
                finally:
                    db.close()
            elif status == "error":
                print(f"   Error Log:    {result.get('error')}")

        except Exception as e:
            print(f"   Execution Error: {e}")
            print("   (Ensure Celery worker is running: python -m celery -A app.tasks.celery_app worker --pool=solo -l info)")

    print("\n" + "=" * 70)
    print(" ✅ ALL SCRAPING JOBS PROCESSED")
    print("=" * 70)

def main():
    parser = argparse.ArgumentParser(description="Generic Lead Generation Web Scraper CLI")
    parser.add_argument("urls", nargs="*", help="One or more target website URLs to scrape")
    parser.add_argument("--tier2", action="store_true", help="Force Tier 2 nodriver CDP engine")
    parser.add_argument("-r", "--recursive", action="store_true", help="Recursively scrape internal subpages (/about, /team, /contact)")
    parser.add_argument("-d", "--depth", type=int, default=0, help="Crawl depth (default 0, set 1 for immediate subpages)")
    parser.add_argument("-c", "--cooldown", action="store_true", help="Enable 7-day scrape cooldown check (Disabled by default)")

    args = parser.parse_args()

    target_urls = args.urls

    if not target_urls:
        print("\nNo URL provided via command line.")
        user_input = input("Enter a target website URL to scrape: ").strip()
        if user_input:
            target_urls = [user_input]
        else:
            print("No URL entered. Exiting.")
            sys.exit(0)

    force_tier = "tier2" if args.tier2 else None
    crawl_depth = 1 if args.recursive and args.depth == 0 else args.depth

    run_generic_scraper(target_urls, force_tier=force_tier, crawl_depth=crawl_depth, enable_cooldown=args.cooldown)

if __name__ == "__main__":
    main()
