from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.models.lead import Lead
from app.schemas.lead import LeadCreateSchema

class LeadRepository:
    """
    Repository for Lead database operations, including atomic UPSERT
    on work_email and JSONB phone structure storage.
    """
    def upsert_lead(self, db: Session, company_id: UUID, schema: LeadCreateSchema) -> Lead:
        phones_json = [p.model_dump() for p in schema.phones]
        
        stmt = pg_insert(Lead).values(
            company_id=company_id,
            first_name=schema.first_name,
            last_name=schema.last_name,
            title=schema.title,
            work_email=schema.work_email,
            phones=phones_json,
            linkedin_url=schema.linkedin_url,
            email_verified=schema.email_verified,
            mx_valid=schema.mx_valid,
            disposable_flag=schema.disposable_flag
        ).on_conflict_do_update(
            index_elements=["work_email"],
            set_={
                "first_name": schema.first_name,
                "last_name": schema.last_name,
                "title": schema.title,
                "phones": phones_json,
                "linkedin_url": schema.linkedin_url,
                "email_verified": schema.email_verified,
                "mx_valid": schema.mx_valid,
                "disposable_flag": schema.disposable_flag
            }
        ).returning(Lead)
        
        lead = db.execute(stmt).scalar_one()
        db.commit()
        db.refresh(lead)
        return lead
