import logging
from dataclasses import asdict
from typing import Optional, Dict, Any

from app.tasks.celery_app import celery_app
from app.core.database import SessionLocal
from app.services.scrapers.tier1_http import Tier1HTTPScraper
from app.services.scrapers.tier2_cdp import Tier2CDPScraper
from app.services.scrapers.parser import HTMLParserService
from app.services.scrapers.email_verifier import EmailVerifierService
from app.repositories import CompanyRepository, LeadRepository, ScrapeLogRepository

logger = logging.getLogger(__name__)

# Initialize services & repositories
tier1_scraper = Tier1HTTPScraper()
tier2_scraper = Tier2CDPScraper(headless=True)
parser_service = HTMLParserService()
email_verifier = EmailVerifierService()

company_repo = CompanyRepository()
lead_repo = LeadRepository()
scrape_log_repo = ScrapeLogRepository()

@celery_app.task(name="tasks.scrape_url_task", bind=True)
def scrape_url_task(self, url: str, force_tier: Optional[str] = None, crawl_depth: int = 0) -> Dict[str, Any]:
    """
    Complete End-to-End Celery Scraping Pipeline:
    1. 7-Day Frequency Cooldown Check (skip if recently scraped)
    2. Tier 1 HTTP Scrape (curl_cffi)
    3. Tier 2 Direct-CDP Fallback (nodriver) if Tier 1 blocked
    4. HTML Data Parsing & Technographic Extraction
    5. Email & MX Verification
    6. PostgreSQL Atomic UPSERT (Companies & Leads)
    7. Scrape Attempt Logging
    8. Recursive Subpage Crawling (if crawl_depth > 0)
    """
    task_id = self.request.id or "direct"
    domain = parser_service.extract_domain(url)
    logger.info(f"[Task {task_id}] Processing URL: {url} (Domain: {domain}, Crawl Depth: {crawl_depth})")

    db = SessionLocal()
    try:
        # 1. Incremental 7-Day Frequency Control Check (by exact URL)
        if scrape_log_repo.was_scraped_recently(db, url, days=7):
            logger.info(f"[Task {task_id}] URL '{url}' was scraped within last 7 days. Skipping fetch.")
            return {
                "status": "skipped",
                "reason": "scraped_within_7_days",
                "domain": domain,
                "url": url
            }

        # 2. Scrape Page (Tier 1 -> Tier 2 Fallback)
        scrape_result = None
        if force_tier != "tier2":
            logger.info(f"[Task {task_id}] Attempting Tier 1 (curl_cffi)...")
            scrape_result = tier1_scraper.fetch_page(url)

        if not scrape_result or scrape_result.status_code != 200 or scrape_result.is_blocked:
            logger.warning(f"[Task {task_id}] Tier 1 failed or blocked. Executing Tier 2 Fallback (nodriver)...")
            scrape_result = tier2_scraper.fetch_page(url)

        # Log scrape attempt
        scrape_log_repo.log_scrape_attempt(
            db=db,
            url=url,
            domain=domain,
            status_code=scrape_result.status_code,
            engine_used=scrape_result.engine_used,
            error_message=scrape_result.error_message
        )

        if scrape_result.status_code != 200 or scrape_result.is_blocked:
            logger.error(f"[Task {task_id}] Scrape failed for {url}")
            return {
                "status": "failed",
                "engine_used": scrape_result.engine_used,
                "status_code": scrape_result.status_code,
                "error": scrape_result.error_message
            }

        # 3. Parse HTML & Extract Structured Schemas
        company_schema, lead_schemas = parser_service.parse_html(scrape_result.html_content, url)

        # 4. Save Company & Technographics to PostgreSQL
        company = company_repo.upsert_company(db, company_schema)
        logger.info(f"[Task {task_id}] Saved Company: {company.name} (ID: {company.id})")

        # 5. Verify Emails & Save Leads to PostgreSQL
        saved_leads_count = 0
        for lead_schema in lead_schemas:
            # Perform Email Verification
            ver_res = email_verifier.verify_email(lead_schema.work_email)
            lead_schema.email_verified = ver_res.is_deliverable
            lead_schema.mx_valid = ver_res.has_mx_records
            lead_schema.disposable_flag = ver_res.is_disposable

            lead = lead_repo.upsert_lead(db, company.id, lead_schema)
            saved_leads_count += 1
            logger.info(f"[Task {task_id}] Saved Lead: {lead.work_email} (Verified={lead.email_verified})")

        # 6. Recursive Subpage Crawling Dispatch
        dispatched_subpages = []
        if crawl_depth > 0:
            internal_links = parser_service.extract_internal_links(scrape_result.html_content, url, max_links=5)
            logger.info(f"[Task {task_id}] Discovered {len(internal_links)} internal subpages. Dispatching child tasks at depth={crawl_depth - 1}...")
            
            for sub_url in internal_links:
                scrape_url_task.delay(sub_url, force_tier=force_tier, crawl_depth=crawl_depth - 1)
                dispatched_subpages.append(sub_url)

        return {
            "status": "success",
            "domain": domain,
            "engine_used": scrape_result.engine_used,
            "company_name": company.name,
            "leads_saved": saved_leads_count,
            "detected_tech": company_schema.detected_technologies,
            "dispatched_subpages": dispatched_subpages
        }
    except Exception as e:
        logger.exception(f"[Task {task_id}] Pipeline exception on {url}: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        db.close()
