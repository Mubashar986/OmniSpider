from dataclasses import dataclass, field
from typing import Dict, Optional, Any

@dataclass
class ScrapeResult:
    """Standardized output container returned by all scraper tiers."""
    url: str
    status_code: int
    headers: Dict[str, str]
    html_content: str
    engine_used: str  # e.g., "curl_cffi" or "nodriver"
    is_blocked: bool
    error_message: Optional[str] = None
    extra_meta: Dict[str, Any] = field(default_factory=dict)
