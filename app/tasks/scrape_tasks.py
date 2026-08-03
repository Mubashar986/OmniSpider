import hashlib
import logging
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from celery.exceptions import MaxRetriesExceededError, Retry

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.redis import get_redis_client
from app.repositories import CompanyRepository, LeadRepository, ScrapeLogRepository
from app.schemas.lead import LeadCreateSchema
from app.services.scrapers.email_verifier import EmailVerifierService
from app.services.scrapers.parser import HTMLParserService, PageType
from app.services.scrapers.tier1_http import Tier1HTTPScraper
from app.services.scrapers.tier2_cdp import Tier2CDPScraper
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# Initialize stateless services & repositories
tier1_scraper = Tier1HTTPScraper()
parser_service = HTMLParserService()
email_verifier = EmailVerifierService()

company_repo = CompanyRepository()
lead_repo = LeadRepository()
scrape_log_repo = ScrapeLogRepository()

MAX_BLOCK_RETRIES = 2
BLOCK_BACKOFF_SECONDS = 120
MAX_PERSON_PROBES_PER_PAGE = 10
MAX_CANDIDATES_PER_PERSON = 3


# ----------------------------------------------------------------------
# Politeness & engine-memory helpers (proxy-free resiliency pack)
# ----------------------------------------------------------------------
def _respect_domain_rate(domain: str) -> None:
    """Per-domain minimum interval + jitter. Solo pool: a short sleep is the token bucket."""
    floor = settings.PER_DOMAIN_MIN_INTERVAL
    try:
        client = get_redis_client()
        key = f"ratelimit:{domain}"
        last = client.get(key)
        wait = floor
        if last is not None:
            wait = floor - (time.time() - float(last))
        wait += random.uniform(0, settings.PER_DOMAIN_JITTER)
        if wait > 0:
            time.sleep(min(wait, 15.0))
        client.set(key, time.time(), ex=3600)
    except Exception as rate_error:
        logger.debug("Rate limiter degraded for %s (%s); fixed delay applied.", domain, rate_error)
        time.sleep(floor)


def _engine_preference(domain: str) -> Optional[str]:
    """Remember which engine last succeeded per domain ('tier1' or 'tier2')."""
    try:
        return get_redis_client().get(f"engine_pref:{domain}")
    except Exception:
        return None


def _remember_engine(domain: str, engine_used: str) -> None:
    try:
        get_redis_client().set(f"engine_pref:{domain}", "tier2" if "nodriver" in engine_used else "tier1", ex=7 * 86400)
    except Exception:
        pass


def _fetch_with_fallback(url: str, domain: str, force_tier: Optional[str]) -> Any:
    """Tier routing with engine memory: skip Tier 1 where it recently failed."""
    preferred = _engine_preference(domain)
    scrape_result = None
    if force_tier != "tier2" and preferred != "tier2":
        logger.info("Attempting Tier 1 (curl_cffi)...")
        scrape_result = tier1_scraper.fetch_page(url)

    if not scrape_result or scrape_result.status_code != 200 or scrape_result.is_blocked:
        logger.warning("Tier 1 failed/skipped. Executing Tier 2 Fallback (nodriver)...")
        # Task-scoped CDP scraper instantiation (WBS 1.2), headless per politeness pack
        tier2_scraper = Tier2CDPScraper(headless=settings.TIER2_HEADLESS)
        scrape_result = tier2_scraper.fetch_page(url)

    if scrape_result.status_code == 200 and not scrape_result.is_blocked:
        _remember_engine(domain, scrape_result.engine_used)
    return scrape_result


def _dispatch_child(url: str, *, session_id: str, force_tier: Optional[str], crawl_depth: int,
                    enable_cooldown: bool, force_refresh: bool, max_links: Optional[int],
                    source_platform: Optional[str]) -> None:
    task_hash = hashlib.sha256(parser_service.canonicalize_url(url).encode()).hexdigest()[:16]
    scrape_url_task.apply_async(
        args=[url],
        kwargs={
            "force_tier": force_tier,
            "crawl_depth": crawl_depth,
            "enable_cooldown": enable_cooldown,
            "force_refresh": force_refresh,
            "max_links": max_links,
            "session_id": session_id,
            "source_platform": source_platform,
        },
        task_id=f"{session_id}:{task_hash}",
    )


def _session_claim(urls: List[str], session_id: str) -> List[str]:
    """Atomically claim URLs in the session visited set; returns only the new ones."""
    try:
        redis_client = get_redis_client()
        dedup_key = f"crawl:session:{session_id}:visited"
        fresh = []
        for url in urls:
            if redis_client.sadd(dedup_key, parser_service.canonicalize_url(url)) == 1:
                fresh.append(url)
        redis_client.expire(dedup_key, 86400)
        return fresh
    except Exception as redis_error:
        logger.warning("Redis session dedup unavailable (%s); dispatching without dedup.", redis_error)
        return urls


def _apply_verification(lead: LeadCreateSchema, verification: Optional[Any], source_platform: Optional[str]) -> None:
    if verification is not None:
        lead.email_status = verification.status
        lead.email_verified = verification.status == "verified"
        lead.mx_valid = verification.has_mx_records
        lead.disposable_flag = verification.is_disposable
        if verification.smtp_checked:
            lead.email_verified_at = datetime.now(timezone.utc)
    lead.source_platform = source_platform


@celery_app.task(name="tasks.scrape_url_task", bind=True, max_retries=MAX_BLOCK_RETRIES)
def scrape_url_task(self, url: str, force_tier: Optional[str] = None, crawl_depth: int = 0,
                    enable_cooldown: bool = True, force_refresh: bool = False,
                    max_links: Optional[int] = None, session_id: Optional[str] = None,
                    source_platform: Optional[str] = None) -> Dict[str, Any]:
    """
    End-to-End routed pipeline:
      DIRECTORY_LISTING  -> harvest profile links and dispatch them (no DB writes)
      DIRECTORY_PROFILE  -> upsert target company, save domain-matched leads,
                            dispatch second hop onto the target's own website
      COMPANY_SITE       -> upsert company (+tech/socials/hq_phone), verify & save
                            leads, infer & verify decision-maker emails, recurse
    Politeness: per-domain delay + jitter, 7-day cooldown (default on),
    engine memory, 403 backoff retries. No proxy rotation (out of scope).
    """
    task_id = self.request.id or "direct"
    session_id = session_id or str(uuid.uuid4())
    domain = parser_service.extract_domain(url)
    source_platform = source_platform or (domain if parser_service.classify_page(url) != PageType.COMPANY_SITE else "direct")
    logger.info(f"[Task {task_id}] [Session {session_id}] {url} (domain={domain}, depth={crawl_depth})")

    db = SessionLocal()
    try:
        # 1. Frequency control (default ON since the politeness pack)
        cooldown_days = settings.SCRAPE_COOLDOWN_DAYS
        if enable_cooldown and not force_refresh and cooldown_days > 0 and scrape_log_repo.was_scraped_recently(db, url, days=cooldown_days):
            logger.info(f"[Task {task_id}] '{url}' scraped within {cooldown_days}d. Skipping.")
            return {"status": "skipped", "reason": f"scraped_within_{cooldown_days}_days", "domain": domain, "url": url, "session_id": session_id}

        # 2. Fetch with politeness + engine memory
        self.update_state(state="PROGRESS", meta={"step": "fetching", "url": url, "session_id": session_id})
        _respect_domain_rate(domain)
        scrape_result = _fetch_with_fallback(url, domain, force_tier)

        scrape_log_repo.log_scrape_attempt(
            db=db, url=url, domain=domain,
            status_code=scrape_result.status_code, engine_used=scrape_result.engine_used,
            error_message=scrape_result.error_message,
        )

        if scrape_result.status_code != 200 or scrape_result.is_blocked:
            logger.error(f"[Task {task_id}] Scrape blocked/failed for {url}")
            if not self.request.called_directly:
                try:
                    raise self.retry(countdown=BLOCK_BACKOFF_SECONDS * (self.request.retries + 1))
                except MaxRetriesExceededError:
                    logger.error(f"[Task {task_id}] Block retries exhausted for {url}")
            return {
                "status": "failed", "engine_used": scrape_result.engine_used,
                "status_code": scrape_result.status_code, "error": scrape_result.error_message,
                "session_id": session_id,
            }

        # 3. Route by page type
        self.update_state(state="PROGRESS", meta={"step": "parsing", "url": url, "session_id": session_id})
        page = parser_service.parse_page(scrape_result.html_content, url)

        # -- DIRECTORY LISTING: only harvest & dispatch profile pages ----------------
        if page.page_type == PageType.DIRECTORY_LISTING:
            effective_max = max_links or settings.MAX_LINKS_PER_PAGE
            fresh_profiles = _session_claim(page.profile_links[:effective_max], session_id)
            for profile_url in fresh_profiles:
                _dispatch_child(
                    profile_url, session_id=session_id, force_tier=force_tier,
                    crawl_depth=0, enable_cooldown=enable_cooldown, force_refresh=force_refresh,
                    max_links=max_links, source_platform=source_platform,
                )
            logger.info(f"[Task {task_id}] Listing page: dispatched {len(fresh_profiles)} profile pages.")
            return {
                "status": "success", "page_type": page.page_type, "domain": domain,
                "session_id": session_id, "engine_used": scrape_result.engine_used,
                "profile_links_found": len(page.profile_links), "dispatched_profiles": fresh_profiles,
            }

        # -- DIRECTORY PROFILE & COMPANY SITE both upsert the real company ----------
        company = company_repo.upsert_company(db, page.company)
        logger.info(f"[Task {task_id}] Saved Company: {company.name} ({company.domain})")

        # 4. Batch-verify every email we intend to store (leads + person candidates)
        self.update_state(state="PROGRESS", meta={"step": "verifying", "leads_found": len(page.leads), "session_id": session_id})
        persons = page.persons[:MAX_PERSON_PROBES_PER_PAGE]
        candidate_pool = {
            candidate
            for person in persons
            for candidate in person.candidate_emails[:MAX_CANDIDATES_PER_PERSON]
        }
        all_emails = [lead.work_email for lead in page.leads] + sorted(candidate_pool)
        verification = email_verifier.verify_emails(all_emails) if all_emails else {}

        saved_leads_count = 0
        known_emails = set()
        for lead_schema in page.leads:
            _apply_verification(lead_schema, verification.get(lead_schema.work_email), source_platform)
            lead_repo.upsert_lead(db, company.id, lead_schema)
            known_emails.add(lead_schema.work_email)
            saved_leads_count += 1

        # 5. Decision-maker inference: keep the first SMTP-confirmed candidate per person
        inferred_count = 0
        for person in persons:
            confirmed = next(
                (email for email in person.candidate_emails[:MAX_CANDIDATES_PER_PERSON]
                 if email not in known_emails
                 and verification.get(email) is not None
                 and verification[email].status in ("verified", "catch_all")),
                None,
            )
            if not confirmed:
                continue
            inferred = LeadCreateSchema(
                first_name=person.first_name, last_name=person.last_name,
                title=person.title, seniority=person.seniority, department=person.department,
                work_email=confirmed, linkedin_url=person.linkedin_url,
            )
            _apply_verification(inferred, verification[confirmed], source_platform)
            lead_repo.upsert_lead(db, company.id, inferred)
            known_emails.add(confirmed)
            inferred_count += 1

        # 6. Second hop / recursion dispatch
        dispatched_subpages: List[str] = []
        if page.page_type == PageType.DIRECTORY_PROFILE and page.target_website:
            # The hop that actually finds leads: crawl the target company's own site.
            fresh_targets = _session_claim([page.target_website], session_id)
            for target in fresh_targets:
                _dispatch_child(
                    target, session_id=session_id, force_tier=force_tier,
                    crawl_depth=max(crawl_depth, 1), enable_cooldown=enable_cooldown,
                    force_refresh=force_refresh, max_links=max_links, source_platform=source_platform,
                )
                dispatched_subpages.append(target)
        elif page.page_type == PageType.COMPANY_SITE and crawl_depth > 0:
            effective_max = max_links or settings.MAX_LINKS_PER_PAGE
            internal_links = parser_service.extract_internal_links(scrape_result.html_content, url, max_links=effective_max)
            fresh_links = _session_claim([url, *internal_links], session_id)
            for sub_url in fresh_links:
                if sub_url == parser_service.canonicalize_url(url):
                    continue
                _dispatch_child(
                    sub_url, session_id=session_id, force_tier=force_tier,
                    crawl_depth=crawl_depth - 1, enable_cooldown=enable_cooldown,
                    force_refresh=force_refresh, max_links=max_links, source_platform=source_platform,
                )
                dispatched_subpages.append(sub_url)

        return {
            "status": "success", "page_type": page.page_type, "domain": domain,
            "session_id": session_id, "engine_used": scrape_result.engine_used,
            "company_name": company.name, "company_domain": company.domain,
            "leads_saved": saved_leads_count, "inferred_leads": inferred_count,
            "detected_tech": page.company.detected_technologies,
            "target_website": page.target_website,
            "dispatched_subpages": dispatched_subpages,
        }
    except Retry:
        # Celery control-flow exception: must propagate so the 403 backoff retry is scheduled.
        raise
    except Exception as e:
        logger.exception(f"[Task {task_id}] Pipeline exception on {url}: {e}")
        return {"status": "error", "error": str(e), "session_id": session_id}
    finally:
        db.close()
