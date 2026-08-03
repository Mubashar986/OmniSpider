import re
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.lead import Lead
from app.schemas.lead import LeadCreateSchema

MAX_PHONES_PER_LEAD = 5


def _phone_key(number: str) -> str:
    return re.sub(r"\D", "", number or "")


def merge_phones(existing: List[Dict[str, Any]], new: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Union of phone dicts keyed on digits, existing entries first, capped."""
    merged: List[Dict[str, Any]] = []
    seen = set()
    for phone in [*existing, *new]:
        key = _phone_key(str(phone.get("number", "")))
        if len(key) < 10 or key in seen:
            continue
        seen.add(key)
        merged.append({"number": phone.get("number"), "type": phone.get("type", "office")})
        if len(merged) >= MAX_PHONES_PER_LEAD:
            break
    return merged


class LeadRepository:
    """
    Repository for Lead database operations with non-destructive UPSERT
    semantics: re-attributes company, merges phones, and never erases a
    previously known value with a NULL.
    """
    def upsert_lead(self, db: Session, company_id: UUID, schema: LeadCreateSchema) -> Lead:
        phones_json = [p.model_dump() for p in schema.phones]
        existing = db.query(Lead).filter(Lead.work_email == schema.work_email).one_or_none()

        if existing is None:
            lead = Lead(
                company_id=company_id,
                first_name=schema.first_name,
                last_name=schema.last_name,
                title=schema.title,
                seniority=schema.seniority,
                department=schema.department,
                work_email=schema.work_email,
                email_status=schema.email_status,
                email_verified_at=schema.email_verified_at,
                source_platform=schema.source_platform,
                phones=phones_json,
                linkedin_url=schema.linkedin_url,
                email_verified=schema.email_verified,
                mx_valid=schema.mx_valid,
                disposable_flag=schema.disposable_flag,
            )
            db.add(lead)
            db.commit()
            db.refresh(lead)
            return lead

        # Re-attribution: a lead first seen under a wrong company must move.
        existing.company_id = company_id
        # Non-destructive scalar updates: only overwrite with real values.
        if schema.first_name:
            existing.first_name = schema.first_name
        if schema.last_name:
            existing.last_name = schema.last_name
        if schema.title:
            existing.title = schema.title
        if schema.seniority:
            existing.seniority = schema.seniority
        if schema.department:
            existing.department = schema.department
        if schema.linkedin_url:
            existing.linkedin_url = schema.linkedin_url
        if schema.source_platform:
            existing.source_platform = schema.source_platform
        existing.phones = merge_phones(existing.phones or [], phones_json)
        # Verification fields always refresh: they describe the email, not the page.
        existing.email_status = schema.email_status
        existing.email_verified = schema.email_verified
        existing.mx_valid = schema.mx_valid
        existing.disposable_flag = schema.disposable_flag
        if schema.email_verified_at is not None:
            existing.email_verified_at = schema.email_verified_at
        existing.updated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(existing)
        return existing
