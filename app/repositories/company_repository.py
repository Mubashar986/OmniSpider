from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import JSONB, insert as pg_insert
from sqlalchemy import cast, func
from app.core.config import settings
from app.models.company import Company
from app.models.technology import CompanyTechnology
from app.schemas.company import CompanyCreateSchema


class CompanyRepository:
    """
    Repository for Company database operations, including atomic UPSERT
    and technographic stack tracking. Updates are non-destructive:
    scalar fields coalesce, extra_metadata deep-merges at the top level,
    and updated_at always advances on conflict.
    """
    def upsert_company(self, db: Session, schema: CompanyCreateSchema) -> Company:
        # Identity invariant (issue N1): a company row may never be keyed to a
        # directory's own domain — that key would silently merge every unresolved
        # profile on that directory into a single corrupt record.
        domain = (schema.domain or "").lower()
        if any(domain == d or domain.endswith(f".{d}") for d in settings.get_directory_domains()):
            raise ValueError(f"Refusing to upsert company keyed to directory domain: {schema.domain!r}")
        stmt = pg_insert(Company).values(
            domain=schema.domain,
            name=schema.name,
            website_url=schema.website_url,
            industry=schema.industry,
            company_size=schema.company_size,
            hq_phone=schema.hq_phone,
            linkedin_url=schema.linkedin_url,
            twitter_url=schema.twitter_url,
            extra_metadata=schema.extra_metadata or {},
        )
        excluded = stmt.excluded
        empty_jsonb = cast("{}", JSONB)
        stmt = stmt.on_conflict_do_update(
            index_elements=["domain"],
            set_={
                "name": func.coalesce(excluded.name, Company.name),
                "website_url": func.coalesce(excluded.website_url, Company.website_url),
                "industry": func.coalesce(excluded.industry, Company.industry),
                "company_size": func.coalesce(excluded.company_size, Company.company_size),
                "hq_phone": func.coalesce(excluded.hq_phone, Company.hq_phone),
                "linkedin_url": func.coalesce(excluded.linkedin_url, Company.linkedin_url),
                "twitter_url": func.coalesce(excluded.twitter_url, Company.twitter_url),
                # Top-level JSONB merge: newly scraped keys win, old keys survive.
                "extra_metadata": func.coalesce(Company.extra_metadata, empty_jsonb).op("||")(
                    func.coalesce(excluded.extra_metadata, empty_jsonb)
                ),
                "updated_at": func.now(),
            }
        ).returning(Company)

        company = db.execute(stmt).scalar_one()

        # Save detected technographics with conflict guard (WBS 1.3)
        for tech_name in schema.detected_technologies:
            tech_stmt = pg_insert(CompanyTechnology).values(
                company_id=company.id,
                tech_name=tech_name,
                category=schema.tech_category_map.get(tech_name) or "Detected Stack",
            ).on_conflict_do_nothing(index_elements=["company_id", "tech_name"])
            db.execute(tech_stmt)

        db.commit()
        db.refresh(company)
        return company
