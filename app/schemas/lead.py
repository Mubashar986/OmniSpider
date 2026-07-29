from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class PhoneSchema(BaseModel):
    number: str
    type: str = "office"  # e.g., "office", "mobile", "direct"

class LeadCreateSchema(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    title: Optional[str] = None
    work_email: str
    phones: List[PhoneSchema] = Field(default_factory=list)
    linkedin_url: Optional[str] = None
    email_verified: bool = False
    mx_valid: bool = False
    disposable_flag: bool = False
