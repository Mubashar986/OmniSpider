import os
import re
import logging
from urllib.parse import urlparse, urljoin, parse_qs, urlencode
from typing import Dict, List, Optional, Tuple, Set
from bs4 import BeautifulSoup

from app.schemas.company import CompanyCreateSchema
from app.schemas.lead import LeadCreateSchema, PhoneSchema

logger = logging.getLogger(__name__)
PRIORITY_SUBPAGE_KEYWORDS = ["about", "team", "contact", "leadership", "management", "people", "executives", "staff", "company"]

# Blocklist Patterns & Static Media Extensions (WBS 1.4)
BLOCKLIST_PATH_PATTERNS = re.compile(r"/(?:cdn-cgi|wp-json|wp-admin|wp-includes|feed|xmlrpc\.php)", re.IGNORECASE)
BLOCKLIST_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".zip", ".tar", ".gz", ".css", ".js", ".ico", ".mp4", ".mp3", ".xml", ".json"}

# Regular Expression Patterns
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_REGEX = re.compile(r"(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
LINKEDIN_REGEX = re.compile(r"https?://(?:www\.)?linkedin\.com/(?:company|in)/[a-zA-Z0-9_-]+/?")

TECH_SIGNATURES = {
    "Next.js": [r"_next/static", r"__NEXT_DATA__"],
    "React": [r"react\.production\.min\.js", r"react-dom"],
    "Vue.js": [r"vue\.global\.js", r"v-attr"],
    "WordPress": [r"wp-content", r"wp-includes"],
    "Shopify": [r"cdn\.shopify\.com", r"Shopify\.theme"],
    "Cloudflare": [r"cloudflare\.com", r"__cf_chl_opt"],
    "Google Analytics": [r"googletagmanager\.com", r"gtag"],
    "Tailwind CSS": [r"tailwind", r"tw-"],
    "Bootstrap": [r"bootstrap\.min\.css"],
    "HubSpot": [r"js\.hs-scripts\.com", r"hubspot"],
    "Stripe": [r"js\.stripe\.com"]
}

class HTMLParserService:
    """
    Service for parsing unstructured HTML content, extracting contact information,
    normalizing lead schemas, and detecting technographic stacks.
    """

    @staticmethod
    def extract_domain(url: str) -> str:
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path
        if domain.startswith("www."):
            domain = domain[4:]
        return domain.lower().strip()

    @staticmethod
    def canonicalize_url(url: str) -> str:
        """
        Normalizes URL by lowercasing scheme/host, removing default ports,
        stripping fragments, trailing slashes, and tracking query params.
        """
        if not url:
            return ""
        parsed = urlparse(url.strip())
        scheme = parsed.scheme.lower() or "https"
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        # Remove default ports
        if ":" in netloc:
            host, port = netloc.split(":", 1)
            if (scheme == "http" and port == "80") or (scheme == "https" and port == "443"):
                netloc = host
        path = (parsed.path.rstrip("/") if parsed.path != "/" else "/").lower()
        # Filter out tracking query params
        cleaned_query = ""
        if parsed.query:
            qs = parse_qs(parsed.query)
            filtered = {k: v for k, v in qs.items() if not k.lower().startswith(("utm_", "fbclid", "gclid"))}
            if filtered:
                cleaned_query = "?" + urlencode(filtered, doseq=True)
        return f"{scheme}://{netloc}{path}{cleaned_query}"

    @staticmethod
    def split_full_name(full_name: str) -> Tuple[Optional[str], Optional[str]]:
        if not full_name:
            return None, None
        parts = full_name.strip().split()
        if len(parts) == 1:
            return parts[0], None
        return parts[0], " ".join(parts[1:])

    def extract_emails(self, html: str, domain: str) -> Set[str]:
        raw_matches = EMAIL_REGEX.findall(html)
        valid_emails = set()
        for email in raw_matches:
            email_lower = email.lower().strip()
            # Ignore common image file extensions falsely matched by regex
            if not any(email_lower.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp"]):
                valid_emails.add(email_lower)
        return valid_emails

    def extract_phones(self, html: str) -> List[PhoneSchema]:
        raw_matches = PHONE_REGEX.findall(html)
        phones = []
        seen = set()
        for match in raw_matches:
            num_str = "".join(match).strip()
            if len(num_str) >= 10 and num_str not in seen:
                seen.add(num_str)
                phone_type = "mobile" if num_str.startswith("+") else "office"
                phones.append(PhoneSchema(number=num_str, type=phone_type))
        return phones

    def extract_linkedin_urls(self, html: str) -> List[str]:
        matches = LINKEDIN_REGEX.findall(html)
        return list(set(matches))

    def detect_technologies(self, html: str) -> List[str]:
        detected = []
        for tech, patterns in TECH_SIGNATURES.items():
            if any(re.search(pat, html, re.IGNORECASE) for pat in patterns):
                detected.append(tech)
        return detected

    def parse_html(self, html_content: str, url: str) -> Tuple[CompanyCreateSchema, List[LeadCreateSchema]]:
        domain = self.extract_domain(url)
        
        # 1. Extract Company Info & Technographics
        detected_tech = self.detect_technologies(html_content)
        
        company = CompanyCreateSchema(
            domain=domain,
            name=domain.split(".")[0].capitalize(),
            website_url=url if url.startswith("http") else f"https://{url}",
            detected_technologies=detected_tech
        )

        # 2. Extract Lead Contacts & Phones
        emails = self.extract_emails(html_content, domain)
        phones = self.extract_phones(html_content)
        linkedin_urls = self.extract_linkedin_urls(html_content)

        leads = []
        for idx, email in enumerate(emails):
            prefix = email.split("@")[0]
            first_name, last_name = self.split_full_name(prefix.replace(".", " ").replace("_", " ").title())
            
            lead = LeadCreateSchema(
                first_name=first_name,
                last_name=last_name,
                work_email=email,
                phones=phones if idx == 0 else [],  # Associate phone batch with primary lead
                linkedin_url=linkedin_urls[0] if linkedin_urls else None
            )
            leads.append(lead)

        return company, leads

    def extract_internal_links(self, html_content: str, base_url: str, max_links: int = 10) -> List[str]:
        """
        Parses <a href="..."> tags, isolates internal domain subpages,
        and prioritizes high-value contact/about/team pages.
        """
        domain = self.extract_domain(base_url)
        soup = BeautifulSoup(html_content, "html.parser")
        found_links = set()

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
                
            full_url = urljoin(base_url, href)
            parsed = urlparse(full_url)
            
            # Must match target domain and not be root/anchor only
            if self.extract_domain(full_url) == domain and parsed.path not in ("", "/"):
                # Filter system paths and static file extensions (WBS 1.4)
                if BLOCKLIST_PATH_PATTERNS.search(parsed.path):
                    continue
                ext = os.path.splitext(parsed.path)[1].lower()
                if ext in BLOCKLIST_EXTENSIONS:
                    continue
                
                clean_url = self.canonicalize_url(full_url)
                if clean_url:
                    found_links.add(clean_url)

        priority_links = []
        other_links = []

        for link in found_links:
            if any(kw in link.lower() for kw in PRIORITY_SUBPAGE_KEYWORDS):
                priority_links.append(link)
            else:
                other_links.append(link)

        ordered = priority_links + other_links
        return ordered[:max_links]
