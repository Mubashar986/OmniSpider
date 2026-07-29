from pydantic import BaseModel
from typing import Optional, List

class CompanyCreateSchema(BaseModel):
    domain: str
    name: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    website_url: Optional[str] = None
    detected_technologies: List[str] = []
