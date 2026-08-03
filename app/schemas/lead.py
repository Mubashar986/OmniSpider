from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional, List

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
