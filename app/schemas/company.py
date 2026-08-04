from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any

# Hard caps keep a single over-long extracted value from crashing the whole page's
# persistence at the PostgreSQL VARCHAR boundary (issue N3). Empty becomes None.
_FIELD_CAPS = {
    "name": 250,
    "industry": 250,
    "company_size": 100,
    "hq_phone": 50,
    "linkedin_url": 500,
    "twitter_url": 500,
    "website_url": 2000,
}


class CompanyCreateSchema(BaseModel):
    domain: str
    name: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    website_url: Optional[str] = None
    hq_phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    twitter_url: Optional[str] = None
    detected_technologies: List[str] = Field(default_factory=list)
    tech_category_map: Dict[str, str] = Field(default_factory=dict)
    extra_metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator(*_FIELD_CAPS, mode="before")
    @classmethod
    def _cap_length(cls, value, info):
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        return cleaned[: _FIELD_CAPS[info.field_name]] or None
