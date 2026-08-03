"""Lead-database quality report.

Computes the success metrics from docs/LEAD_GEN_AUDIT_REPORT.md (section 8)
plus the SRS email_status distribution, prints PASS/FAIL per metric, and
exits non-zero when any applicable metric misses its target.

Usage:
    venv\\Scripts\\python.exe scripts\\quality_report.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from sqlalchemy import func

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.company import Company
from app.models.lead import Lead
from app.models.scrape_log import ScrapeLog
from app.services.scrapers.parser import FREE_EMAIL_DOMAINS

CORRUPT_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


def _pct(part: int, whole: int) -> float:
    return (100.0 * part / whole) if whole else 0.0


def main() -> int:
    db = SessionLocal()
    results = []  # (metric, value_str, target_str, passed or None for N/A)
    try:
        total_leads = db.query(func.count(Lead.id)).scalar() or 0
        total_companies = db.query(func.count(Company.id)).scalar() or 0
        email_domain = func.lower(func.split_part(Lead.work_email, "@", 2))

        # 1. Leads whose email domain matches their company's domain (> 80%)
        matched = (
            db.query(func.count(Lead.id))
            .join(Company, Lead.company_id == Company.id)
            .filter(email_domain == func.lower(Company.domain))
            .scalar()
        ) or 0
        value = _pct(matched, total_leads)
        results.append((
            "Leads with email on target company domain",
            f"{matched}/{total_leads} ({value:.1f}%)",
            "> 80%",
            (value > 80.0) if total_leads else None,
        ))

        # 2. Corrupted emails in DB (0)
        corrupted = (
            db.query(func.count(Lead.id))
            .filter(Lead.work_email.op("!~")(CORRUPT_EMAIL_PATTERN))
            .scalar()
        ) or 0
        results.append((
            "Corrupted emails in DB",
            str(corrupted),
            "0",
            (corrupted == 0) if total_leads else None,
        ))

        # 3. Personal/free-provider emails (< 5%)
        personal = (
            db.query(func.count(Lead.id))
            .filter(email_domain.in_(sorted(FREE_EMAIL_DOMAINS)))
            .scalar()
        ) or 0
        value = _pct(personal, total_leads)
        results.append((
            "Personal-email leads",
            f"{personal}/{total_leads} ({value:.1f}%)",
            "< 5%",
            (value < 5.0) if total_leads else None,
        ))

        # 4. Leads with at least one phone (> 50%)
        phone_count = func.coalesce(func.jsonb_array_length(Lead.phones), 0)
        with_phones = (
            db.query(func.count(Lead.id)).filter(phone_count > 0).scalar()
        ) or 0
        value = _pct(with_phones, total_leads)
        results.append((
            "Leads with phones",
            f"{with_phones}/{total_leads} ({value:.1f}%)",
            "> 50%",
            (value > 50.0) if total_leads else None,
        ))

        # 5. Leads with a personal LinkedIn profile (> 80%)
        with_linkedin = (
            db.query(func.count(Lead.id))
            .filter(Lead.linkedin_url.ilike("%linkedin.com/in/%"))
            .scalar()
        ) or 0
        value = _pct(with_linkedin, total_leads)
        results.append((
            "Leads with personal LinkedIn",
            f"{with_linkedin}/{total_leads} ({value:.1f}%)",
            "> 80%",
            (value > 80.0) if total_leads else None,
        ))

        # 6. Directory domains must not be stored as target companies (0)
        directory_domains = settings.get_directory_domains()
        directory_companies = (
            db.query(func.count(Company.id))
            .filter(func.lower(Company.domain).in_([d.lower() for d in directory_domains]))
            .scalar()
        ) or 0 if directory_domains else 0
        results.append((
            "Directory domains stored as companies",
            f"{directory_companies} (total companies: {total_companies})",
            "0",
            (directory_companies == 0) if total_companies else None,
        ))

        # 7. leads.title populated (> 60%)
        with_title = (
            db.query(func.count(Lead.id))
            .filter(Lead.title.isnot(None), Lead.title != "")
            .scalar()
        ) or 0
        value = _pct(with_title, total_leads)
        results.append((
            "Leads with job title",
            f"{with_title}/{total_leads} ({value:.1f}%)",
            "> 60%",
            (value > 60.0) if total_leads else None,
        ))

        # 8. Re-crawls per unique page (<= 1.1x)
        total_fetches = db.query(func.count(ScrapeLog.id)).scalar() or 0
        unique_pages = db.query(func.count(func.distinct(ScrapeLog.url))).scalar() or 0
        ratio = (total_fetches / unique_pages) if unique_pages else 0.0
        results.append((
            "Re-crawls per unique page",
            f"{ratio:.2f}x ({total_fetches} fetches / {unique_pages} pages)",
            "<= 1.1x",
            (ratio <= 1.1) if unique_pages else None,
        ))

        # 9. Scrape success rate (>= 95%)
        coded = (
            db.query(func.count(ScrapeLog.id))
            .filter(ScrapeLog.status_code.isnot(None))
            .scalar()
        ) or 0
        successful = (
            db.query(func.count(ScrapeLog.id))
            .filter(ScrapeLog.status_code.between(200, 399))
            .scalar()
        ) or 0
        value = _pct(successful, coded)
        results.append((
            "Scrape success rate (HTTP 2xx/3xx)",
            f"{successful}/{coded} ({value:.1f}%)",
            ">= 95%",
            (value >= 95.0) if coded else None,
        ))

        # Info: SRS email_status distribution (not gated)
        status_rows = (
            db.query(Lead.email_status, func.count(Lead.id))
            .group_by(Lead.email_status)
            .order_by(func.count(Lead.id).desc())
            .all()
        )
        seniority_rows = (
            db.query(Lead.seniority, func.count(Lead.id))
            .filter(Lead.seniority.isnot(None))
            .group_by(Lead.seniority)
            .order_by(func.count(Lead.id).desc())
            .all()
        )
    finally:
        db.close()

    print("=" * 78)
    print(" OMNISPIDER LEAD-DATA QUALITY REPORT")
    print("=" * 78)
    print(f" {'Metric':<44}{'Value':<22}{'Target':<9}Result")
    print("-" * 78)
    failures = 0
    for metric, value, target, passed in results:
        if passed is None:
            verdict = "N/A"
        elif passed:
            verdict = "PASS"
        else:
            verdict = "FAIL"
            failures += 1
        print(f" {metric:<44}{value:<22}{target:<9}{verdict}")

    print("-" * 78)
    print(" Email status distribution (informational):")
    if status_rows:
        for status, count in status_rows:
            print(f"   {status or 'NULL':<15}{count}")
    else:
        print("   (no leads)")
    print(" Seniority distribution (informational):")
    if seniority_rows:
        for seniority, count in seniority_rows:
            print(f"   {seniority or 'NULL':<25}{count}")
    else:
        print("   (no seniority data)")
    print("=" * 78)

    if failures:
        print(f" RESULT: FAIL - {failures} metric(s) below target")
        return 1
    print(" RESULT: PASS - all applicable metrics meet targets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
