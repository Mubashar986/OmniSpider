from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


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
