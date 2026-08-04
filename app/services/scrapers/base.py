import re
from dataclasses import dataclass, field
from typing import Dict, Optional, Any

from bs4 import BeautifulSoup

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


# Soft-404 heuristics: pages that return 200 OK but are actually missing content.
# Strong title markers are trusted outright; weak markers require a thin page so
# legitimate content pages mentioning "not found" are not misclassified.
_SOFT_404_TITLE_STRONG = re.compile(r"\b404\b|page not found", re.IGNORECASE)
_SOFT_404_TITLE_WEAK = re.compile(r"not found|doesn'?t exist|no longer (?:available|exists)", re.IGNORECASE)
_SOFT_404_PHRASES = (
    "page not found",
    "page could not be found",
    "page you are looking for",
    "page you're looking for",
    "does not exist",
    "doesn't exist",
    "no longer available",
    "company not found",
    "profile not found",
)
_SOFT_404_THIN_CHARS = 2500


def detect_soft_404(html_content: str) -> bool:
    """Conservative soft-404 heuristic for 200-OK pages that are actually missing."""
    if not html_content:
        return False
    try:
        soup = BeautifulSoup(html_content, "html.parser")
    except Exception:
        return False

    title = (soup.title.string if soup.title and soup.title.string else "").strip()
    if _SOFT_404_TITLE_STRONG.search(title):
        return True

    # Next.js renders its error page with these markers.
    if soup.find("script", id="__NEXT_DATA__") and re.search(r'"page"\s*:\s*"/404', html_content):
        return True
    if soup.find(id="__next_error__"):
        return True

    text = soup.get_text(" ", strip=True).lower()
    if len(text) < _SOFT_404_THIN_CHARS and (
        _SOFT_404_TITLE_WEAK.search(title) or any(phrase in text for phrase in _SOFT_404_PHRASES)
    ):
        return True
    return False
