from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List

# See CompanyCreateSchema: cap extracted strings below the DB VARCHAR limits (N3).
_FIELD_CAPS = {
    "first_name": 150,
    "last_name": 150,
    "title": 255,
    "seniority": 50,
    "department": 100,
    "work_email": 255,
    "source_platform": 100,
    "linkedin_url": 2000,
}

EMAIL_STATUSES = ("verified", "catch_all", "unverified", "invalid", "disposable")
SENIORITY_LEVELS = ("c_level", "vp", "director", "manager", "individual_contributor")


class PhoneSchema(BaseModel):
    number: str
    type: str = "office"  # e.g., "office", "mobile", "toll_free"


class LeadCreateSchema(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    title: Optional[str] = None
    seniority: Optional[str] = None
    department: Optional[str] = None
    work_email: str
    email_status: str = "unverified"  # one of EMAIL_STATUSES
    email_verified_at: Optional[datetime] = None
    source_platform: Optional[str] = None
    phones: List[PhoneSchema] = Field(default_factory=list)
    linkedin_url: Optional[str] = None
    email_verified: bool = False
    mx_valid: bool = False
    disposable_flag: bool = False

    @field_validator(*_FIELD_CAPS, mode="before")
    @classmethod
    def _cap_length(cls, value, info):
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        return cleaned[: _FIELD_CAPS[info.field_name]] or None
