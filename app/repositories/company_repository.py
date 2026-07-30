from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.models.company import Company
from app.models.technology import CompanyTechnology
from app.schemas.company import CompanyCreateSchema

class CompanyRepository:
    """
    Repository for Company database operations, including atomic UPSERT
    and technographic stack tracking.
    """
    def upsert_company(self, db: Session, schema: CompanyCreateSchema) -> Company:
        stmt = pg_insert(Company).values(
            domain=schema.domain,
            name=schema.name,
            website_url=schema.website_url
        ).on_conflict_do_update(
            index_elements=["domain"],
            set_={
                "name": schema.name,
                "website_url": schema.website_url,
            }
        ).returning(Company)
        
        company = db.execute(stmt).scalar_one()
        
        # Save detected technographics with conflict guard (WBS 1.3)
        for tech_name in schema.detected_technologies:
            tech_stmt = pg_insert(CompanyTechnology).values(
                company_id=company.id,
                tech_name=tech_name,
                category="Scraped Stack"
            ).on_conflict_do_nothing(index_elements=["company_id", "tech_name"])
            db.execute(tech_stmt)
            
        db.commit()
        db.refresh(company)
        return company
