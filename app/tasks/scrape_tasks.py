import uuid
import hashlib
import logging
import redis
from dataclasses import asdict
from typing import Optional, Dict, Any

from app.core.config import settings
from app.core.redis import get_redis_client
from app.tasks.celery_app import celery_app
from app.core.database import SessionLocal
from app.services.scrapers.tier1_http import Tier1HTTPScraper
from app.services.scrapers.tier2_cdp import Tier2CDPScraper
from app.services.scrapers.parser import HTMLParserService
from app.services.scrapers.email_verifier import EmailVerifierService
from app.repositories import CompanyRepository, LeadRepository, ScrapeLogRepository

logger = logging.getLogger(__name__)

# Initialize stateless services & repositories
tier1_scraper = Tier1HTTPScraper()
parser_service = HTMLParserService()
email_verifier = EmailVerifierService()

company_repo = CompanyRepository()
lead_repo = LeadRepository()
scrape_log_repo = ScrapeLogRepository()

@celery_app.task(name="tasks.scrape_url_task", bind=True)
def scrape_url_task(self, url: str, force_tier: Optional[str] = None, crawl_depth: int = 0, enable_cooldown: bool = False, force_refresh: bool = False, max_links: Optional[int] = None, session_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Complete End-to-End Celery Scraping Pipeline:
    1. Tier 1 HTTP Scrape (curl_cffi)
    2. Tier 2 Direct-CDP Fallback (nodriver) if Tier 1 blocked
    3. HTML Data Parsing & Technographic Extraction
    4. Email & MX Verification
    5. PostgreSQL Atomic UPSERT (Companies & Leads)
    6. Scrape Attempt Logging
    7. Recursive Subpage Crawling (with Session Deduplication)
    """
    task_id = self.request.id or "direct"
    session_id = session_id or str(uuid.uuid4())
    domain = parser_service.extract_domain(url)
    logger.info(f"[Task {task_id}] [Session {session_id}] Processing URL: {url} (Domain: {domain}, Crawl Depth: {crawl_depth})")

    db = SessionLocal()
    try:
        # 1. Optional Frequency Control Check (Disabled by default; only active if enable_cooldown=True)
        cooldown_days = settings.SCRAPE_COOLDOWN_DAYS
        if enable_cooldown and not force_refresh and cooldown_days > 0 and scrape_log_repo.was_scraped_recently(db, url, days=cooldown_days):
            logger.info(f"[Task {task_id}] URL '{url}' was scraped within last {cooldown_days} days. Skipping fetch.")
            return {
                "status": "skipped",
                "reason": f"scraped_within_{cooldown_days}_days",
                "domain": domain,
                "url": url,
                "session_id": session_id
            }

        # Issue 17: Update progress state (FETCHING)
        self.update_state(state="PROGRESS", meta={"step": "fetching", "url": url, "session_id": session_id})

        # 2. Scrape Page (Tier 1 -> Tier 2 Fallback)
        scrape_result = None
        if force_tier != "tier2":
            logger.info(f"[Task {task_id}] Attempting Tier 1 (curl_cffi)...")
            scrape_result = tier1_scraper.fetch_page(url)

        if not scrape_result or scrape_result.status_code != 200 or scrape_result.is_blocked:
            logger.warning(f"[Task {task_id}] Tier 1 failed or blocked. Executing Tier 2 Fallback (nodriver)...")
            # Task-scoped CDP scraper instantiation (WBS 1.2)
            tier2_scraper = Tier2CDPScraper(headless=False)
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
                "error": scrape_result.error_message,
                "session_id": session_id
            }

        # 3. Parse HTML & Extract Structured Schemas
        self.update_state(state="PROGRESS", meta={"step": "parsing", "url": url, "session_id": session_id})
        company_schema, lead_schemas = parser_service.parse_html(scrape_result.html_content, url)

        # 4. Save Company & Technographics to PostgreSQL
        company = company_repo.upsert_company(db, company_schema)
        logger.info(f"[Task {task_id}] Saved Company: {company.name} (ID: {company.id})")

        # 5. Verify Emails & Save Leads to PostgreSQL
        self.update_state(state="PROGRESS", meta={"step": "verifying", "leads_found": len(lead_schemas), "session_id": session_id})
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

        # 6. Recursive Subpage Crawling Dispatch with Session Deduplication (WBS 1.1)
        dispatched_subpages = []
        if crawl_depth > 0:
            effective_max_links = max_links or settings.MAX_LINKS_PER_PAGE
            internal_links = parser_service.extract_internal_links(scrape_result.html_content, url, max_links=effective_max_links)
            logger.info(f"[Task {task_id}] Discovered {len(internal_links)} internal subpages. Applying Redis SADD dedup check...")
            
            try:
                redis_client = get_redis_client()
                dedup_key = f"crawl:session:{session_id}:visited"
                # Mark current URL as visited
                redis_client.sadd(dedup_key, parser_service.canonicalize_url(url))
                redis_client.expire(dedup_key, 86400)

                for sub_url in internal_links:
                    normalized_sub = parser_service.canonicalize_url(sub_url)
                    is_new = redis_client.sadd(dedup_key, normalized_sub)
                    redis_client.expire(dedup_key, 86400)

                    if is_new == 0:
                        logger.info(f"[Task {task_id}] Subpage '{normalized_sub}' already visited in session {session_id}. Skipping dispatch.")
                        continue

                    task_hash = hashlib.sha256(normalized_sub.encode()).hexdigest()[:16]
                    child_task_id = f"{session_id}:{task_hash}"

                    scrape_url_task.apply_async(
                        args=[sub_url],
                        kwargs={
                            "force_tier": force_tier,
                            "crawl_depth": crawl_depth - 1,
                            "enable_cooldown": enable_cooldown,
                            "force_refresh": force_refresh,
                            "max_links": max_links,
                            "session_id": session_id,
                        },
                        task_id=child_task_id
                    )
                    dispatched_subpages.append(sub_url)
            except Exception as red_err:
                logger.warning(f"[Task {task_id}] Redis dedup check error ({red_err}); falling back to direct dispatch.")
                for sub_url in internal_links:
                    scrape_url_task.delay(sub_url, force_tier=force_tier, crawl_depth=crawl_depth - 1, enable_cooldown=enable_cooldown, force_refresh=force_refresh, max_links=max_links, session_id=session_id)
                    dispatched_subpages.append(sub_url)

        return {
            "status": "success",
            "domain": domain,
            "session_id": session_id,
            "engine_used": scrape_result.engine_used,
            "company_name": company.name,
            "leads_saved": saved_leads_count,
            "detected_tech": company_schema.detected_technologies,
            "dispatched_subpages": dispatched_subpages
        }
    except Exception as e:
        logger.exception(f"[Task {task_id}] Pipeline exception on {url}: {e}")
        return {"status": "error", "error": str(e), "session_id": session_id}
    finally:
        db.close()
