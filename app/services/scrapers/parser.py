import os
import re
import json
import logging
from pathlib import Path
from urllib.parse import urlparse, urljoin, parse_qs, urlencode
from typing import Dict, List, Optional, Tuple, Set
from bs4 import BeautifulSoup
import tldextract
from yarl import URL as YarlURL

from app.core.config import settings
from app.schemas.company import CompanyCreateSchema
from app.schemas.lead import LeadCreateSchema, PhoneSchema

logger = logging.getLogger(__name__)
PRIORITY_SUBPAGE_KEYWORDS = ["about", "team", "contact", "leadership", "management", "people", "executives", "staff", "company"]

# --- Dynamic Config Loading (Phase 1: Config Externalization) ---
_CONFIG_DIR = Path(__file__).resolve().parent.parent.parent.parent / "config"

def _build_blocklist_regex() -> re.Pattern:
    """Build blocklist regex from settings instead of hardcoded patterns."""
    patterns = settings.get_blocklist_patterns()
    escaped = [re.escape(p) for p in patterns]
    return re.compile(r"/(?:" + "|".join(escaped) + r")", re.IGNORECASE)

def _load_json_config(filename: str) -> dict:
    """Load a JSON config file from the config/ directory."""
    filepath = _CONFIG_DIR / filename
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"Config file not found: {filepath}. Using empty defaults.")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {filepath}: {e}. Using empty defaults.")
        return {}

# Load dynamic configs at module import time
BLOCKLIST_PATH_PATTERNS = _build_blocklist_regex()
BLOCKLIST_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".zip", ".tar", ".gz", ".css", ".js", ".ico", ".mp4", ".mp3", ".xml", ".json"}
TECH_SIGNATURES = _load_json_config("tech_signatures.json")
FIELD_MAPPINGS = _load_json_config("field_mappings.json")
DIRECTORY_PROFILES = _load_json_config("directory_profiles.json")

# Regular Expression Patterns
EMAIL_REGEX = re.compile(
    r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.(?:com|org|net|io|co|eu|dev|tech|info|biz|uk|us|ca|de|fr|au|in|agency|digital|systems|online|studio|solutions|company|global|[a-zA-Z]{2,10})\b",
    re.IGNORECASE
)
PHONE_REGEX = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
LINKEDIN_REGEX = re.compile(r"https?://(?:www\.)?linkedin\.com/(?:company|in)/[a-zA-Z0-9_-]+/?")

try:
    import phonenumbers
    from phonenumbers import PhoneNumberMatcher
    HAS_PHONENUMBERS = True
except ImportError:
    HAS_PHONENUMBERS = False

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
        stripping fragments, trailing slashes, and removing directory filter/tracking params.
        """
        if not url:
            return ""
        parsed = urlparse(url.strip())
        scheme = parsed.scheme.lower() or "https"
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        # Remove default ports using yarl for RFC-compliant parsing (Issue #9)
        try:
            yurl = YarlURL(f"{scheme}://{netloc}{parsed.path}")
            netloc = yurl.host or netloc
            if yurl.explicit_port and (
                (scheme == "http" and yurl.port == 80) or
                (scheme == "https" and yurl.port == 443)
            ):
                pass  # yarl.host already strips default ports
        except Exception:
            # Fallback to manual splitting if yarl fails
            if ":" in netloc:
                host, port = netloc.split(":", 1)
                if (scheme == "http" and port == "80") or (scheme == "https" and port == "443"):
                    netloc = host
        path = (parsed.path.rstrip("/") if parsed.path != "/" else "/").lower()

        # For directory profile/company/entity detail pages, strip query strings completely
        # to ensure exact 1:1 Redis deduplication across parameter variants
        # Profile paths loaded from config/directory_profiles.json (Issue #8)
        all_profile_paths = set()
        for dir_config in DIRECTORY_PROFILES.values():
            all_profile_paths.update(dir_config.get("profile_paths", []))
        # Fallback defaults if config is empty
        all_profile_paths.update(["/profile/", "/company/", "/developer/", "/agency/", "/directory/"])
        if any(kw in path for kw in all_profile_paths):
            return f"{scheme}://{netloc}{path}"

        # Otherwise filter out tracking, filter, and pagination query params
        # Ignored params loaded from settings (Issue #4)
        cleaned_query = ""
        if parsed.query:
            qs = parse_qs(parsed.query)
            ignored = settings.get_ignored_query_params()
            filtered = {
                k: v for k, v in qs.items() 
                if not k.lower().startswith(ignored) and k.lower() not in ignored
            }
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
        valid_emails = set()
        for match in EMAIL_REGEX.finditer(html):
            email_lower = match.group(0).lower().strip()
            
            # Fix Issue #14: Split on @ first, validate domain part independently
            if "@" not in email_lower:
                continue
            local_part, domain_part = email_lower.rsplit("@", 1)
            
            # Use tldextract to cleanly identify TLD boundary (Issue #5)
            try:
                ext = tldextract.extract(domain_part)
                if ext.domain and ext.suffix:
                    # Reconstruct clean domain from tldextract parts
                    clean_domain = f"{ext.domain}.{ext.suffix}"
                    if ext.subdomain:
                        clean_domain = f"{ext.subdomain}.{clean_domain}"
                    email_lower = f"{local_part}@{clean_domain}"
                else:
                    continue  # Invalid domain, skip
            except Exception:
                continue  # tldextract failed, skip this email

            # Ignore common image file extensions falsely matched by regex
            if not any(email_lower.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp"]):
                valid_emails.add(email_lower)
        return valid_emails

    def extract_phones(self, html: str, default_region: str = "US") -> List[PhoneSchema]:
        phones = []
        seen = set()
        # Multi-region parallel scan (Issue #10)
        regions = [default_region] + [r for r in ["US", "GB", "DE", "IN", "AU"] if r != default_region]

        if HAS_PHONENUMBERS:
            try:
                for region in regions:
                    for match in PhoneNumberMatcher(html, region):
                        num_obj = match.number
                        if phonenumbers.is_valid_number(num_obj) or phonenumbers.is_possible_number(num_obj):
                            num_str = phonenumbers.format_number(num_obj, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
                            if num_str not in seen:
                                seen.add(num_str)
                                # Use phonenumbers.number_type() for accurate classification (Issue #11)
                                pn_type = phonenumbers.number_type(num_obj)
                                type_map = {
                                    phonenumbers.PhoneNumberType.MOBILE: "mobile",
                                    phonenumbers.PhoneNumberType.FIXED_LINE: "office",
                                    phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE: "office",
                                    phonenumbers.PhoneNumberType.TOLL_FREE: "toll_free",
                                    phonenumbers.PhoneNumberType.VOIP: "voip",
                                }
                                phone_type = type_map.get(pn_type, "office")
                                phones.append(PhoneSchema(number=num_str, type=phone_type))
                                if len(phones) >= 5:
                                    break
                    if len(phones) >= 5:
                        break
            except Exception as e:
                logger.debug(f"phonenumbers extraction error: {e}")

        # Fallback to regex finditer if phonenumbers unavailable or yielded nothing
        if not phones:
            for match in PHONE_REGEX.finditer(html):
                num_str = match.group(0).strip()
                if len(num_str) >= 10 and num_str not in seen:
                    seen.add(num_str)
                    phone_type = "office"  # Default to office for regex fallback
                    phones.append(PhoneSchema(number=num_str, type=phone_type))
                    if len(phones) >= 5:
                        break

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

    def extract_target_company_info(self, html_content: str, page_url: str) -> Tuple[str, str, str, Optional[str], Optional[str]]:
        """
        Hybrid target extraction: Isolates the true Target Company Identity,
        Firmographics (industry, size), and official website URL from directory profiles.
        """
        page_domain = self.extract_domain(page_url)
        # Directory domains loaded from settings (Issue #6)
        directory_domains = settings.get_directory_domains()
        is_directory = any(dir_domain in page_domain for dir_domain in directory_domains)
        
        target_website = None
        target_name = None
        industry = None
        company_size = None

        if is_directory:
            soup = BeautifulSoup(html_content, "html.parser")
            
            # Pass 1: JSON-LD Organization Schema Parsing with Domain-Exclusion Scoring (Bug P-1 Fix)
            # Instead of first-match-wins, score ALL JSON-LD blocks and pick the best one
            candidates = []
            org_types = {"Organization", "Corporation", "LocalBusiness", "ProfessionalService",
                         "MedicalOrganization", "EducationalOrganization", "Store", "GovernmentOrganization"}
            
            for raw_json in re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html_content, re.DOTALL | re.IGNORECASE):
                try:
                    data = json.loads(raw_json.strip())
                    items = data if isinstance(data, list) else [data]
                    # Handle @graph arrays
                    for item in items:
                        if isinstance(item, dict) and "@graph" in item:
                            items.extend(item["@graph"])
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        item_type = item.get("@type", "")
                        if isinstance(item_type, list):
                            item_type = item_type[0] if item_type else ""
                        if item_type not in org_types:
                            continue
                        
                        # Score this block
                        score = 0
                        item_url = item.get("url") or item.get("sameAs") or ""
                        item_domain = self.extract_domain(item_url) if item_url else ""
                        
                        # +10 if URL domain differs from page_domain (this is the actual target company!)
                        if item_domain and item_domain != page_domain:
                            score += 10
                        # +5 for specific business subtypes (LocalBusiness is more specific than Organization)
                        if item_type in ("LocalBusiness", "ProfessionalService", "Corporation"):
                            score += 5
                        # +3 if has employee count (directory headers rarely have this)
                        if any(item.get(k) for k in ["numberOfEmployees", "employees", "employeeCount"]):
                            score += 3
                        
                        candidates.append({"item": item, "score": score, "domain": item_domain})
                except Exception as e:
                    logger.debug(f"JSON-LD parsing error: {e}")
                    continue
            
            # Pick highest-scoring candidate
            if candidates:
                candidates.sort(key=lambda c: c["score"], reverse=True)
                best = candidates[0]["item"]
                
                # Use configurable field mappings (Issue #12)
                name_keys = FIELD_MAPPINGS.get("company_name", ["name"])
                website_keys = FIELD_MAPPINGS.get("website", ["url", "sameAs"])
                industry_keys = FIELD_MAPPINGS.get("industry", ["knowsAbout", "genre"])
                size_keys = FIELD_MAPPINGS.get("company_size", ["numberOfEmployees", "employees", "employeeCount"])

                for nk in name_keys:
                    if not target_name and best.get(nk):
                        target_name = best.get(nk)
                        break
                for wk in website_keys:
                    if not target_website and best.get(wk):
                        target_website = best.get(wk)
                        break
                for ik in industry_keys:
                    if not industry and best.get(ik):
                        industry = best.get(ik)
                        break
                for sk in size_keys:
                    num_emp = best.get(sk)
                    if num_emp and not company_size:
                        company_size = str(num_emp.get("value")) if isinstance(num_emp, dict) else str(num_emp)
                        break

            # Pass 2: Outbound Website Link Heuristics
            if not target_website:
                for a_tag in soup.find_all("a", href=True):
                    href = a_tag["href"].strip()
                    # Handle redirect params like clutch.co/redirect?url=https://www.openxcell.com
                    if "redirect" in href and "url=" in href:
                        qs = parse_qs(urlparse(href).query)
                        if "url" in qs:
                            href = qs["url"][0]

                    if href.startswith("http"):
                        ext_domain = self.extract_domain(href)
                        if ext_domain and ext_domain != page_domain and not any(d in ext_domain for d in ["linkedin.com", "facebook.com", "twitter.com", "instagram.com"]):
                            target_website = href
                            break

            # Pass 3: CSS Selectors for Company Name, Industry, Size
            if not target_name:
                h1_tag = soup.find("h1")
                if h1_tag:
                    target_name = h1_tag.get_text(strip=True)

            # Industry selector (Clutch / GoodFirms tags)
            # Industry selector (Issue 13 Fix: Semantic HTML + Microdata + Class fallback)
            if not industry:
                # 1. Standard Microdata itemprop="knowsAbout" or "genre"
                ind_elem = soup.find(attrs={"itemprop": re.compile(r"knowsAbout|genre|industry|category", re.I)})
                if ind_elem:
                    industry = ind_elem.get_text(strip=True)
                else:
                    # 2. CSS class fallback
                    ind_tag = soup.find(class_=re.compile(r"industry|field-service|category-name|sector", re.I))
                    if ind_tag:
                        industry = ind_tag.get_text(strip=True)

            # Company Size selector
            if not company_size:
                # Exclude script and style tags
                for script_or_style in soup(["script", "style"]):
                    script_or_style.decompose()
                size_tag = soup.find(text=re.compile(r"\d+\s*[-–]\s*\d+|\d+\s*\+", re.I))
                if size_tag:
                    company_size = size_tag.strip()

        # Fallback for direct company sites or missing directory target website
        if not target_website or self.extract_domain(target_website) == page_domain:
            target_website = page_url if page_url.startswith("http") else f"https://{page_url}"
            target_domain = page_domain
        else:
            target_domain = self.extract_domain(target_website)

        if not target_name:
            target_name = target_domain.split(".")[0].capitalize()

        return target_domain, target_name, target_website, industry, company_size

    def extract_executive_titles(self, html_content: str) -> Dict[str, str]:
        """
        Extracts executive job designations (CEO, CTO, VP, Founder, Director) from profile HTML
        using Microdata, ARIA tags, and Semantic HTML structures (Issue 13 Fix).
        """
        soup = BeautifulSoup(html_content, "html.parser")
        titles = {}
        title_keywords = re.compile(r"\b(?:CEO|CTO|CFO|COO|Founder|Co-Founder|President|Vice President|VP|Director|Managing Director|Head of \w+|Partner)\b", re.I)

        # 1. Microdata itemprop="jobTitle" or "title"
        for title_elem in soup.find_all(attrs={"itemprop": re.compile(r"jobTitle|title", re.I)}):
            text = title_elem.get_text(separator=" ", strip=True)
            match = title_keywords.search(text)
            if match:
                title = match.group(0).title()
                titles[title.lower()] = title

        # 2. Search team / leadership / bio blocks & article cards
        for block in soup.find_all(["article", "figure", "div", "section"], class_=re.compile(r"person|team|executive|leader|profile|bio|member|staff|card", re.I)):
            text = block.get_text(separator=" ", strip=True)
            match = title_keywords.search(text)
            if match:
                title = match.group(0).title()
                titles[title.lower()] = title

        return titles

    def parse_html(self, html_content: str, url: str) -> Tuple[CompanyCreateSchema, List[LeadCreateSchema]]:
        # 1. Extract Target Company Identity & Firmographics (Issues 2.1 & 2.3)
        domain, company_name, website_url, industry, company_size = self.extract_target_company_info(html_content, url)
        detected_tech = self.detect_technologies(html_content)
        
        company = CompanyCreateSchema(
            domain=domain,
            name=company_name,
            website_url=website_url,
            industry=industry,
            company_size=company_size,
            detected_technologies=detected_tech
        )

        # 2. Extract Lead Contacts, Phones & Executive Titles (Issue 3.4)
        emails = self.extract_emails(html_content, domain)
        phones = self.extract_phones(html_content)
        linkedin_urls = self.extract_linkedin_urls(html_content)
        executive_titles = self.extract_executive_titles(html_content)

        # Infer default executive designation if found
        default_title = list(executive_titles.values())[0] if executive_titles else None

        leads = []
        for idx, email in enumerate(emails):
            prefix = email.split("@")[0]
            first_name, last_name = self.split_full_name(prefix.replace(".", " ").replace("_", " ").title())
            
            lead = LeadCreateSchema(
                first_name=first_name,
                last_name=last_name,
                title=default_title,  # Populates lead.title designation!
                work_email=email,
                phones=phones if idx == 0 else [],  # Associate phone batch with primary lead
                linkedin_url=linkedin_urls[idx] if idx < len(linkedin_urls) else None
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

        # Issue 1 (A4): Semantic HTML link prioritization
        # Check nav/footer containers, aria-label, itemprop, and URL keywords
        priority_links = []
        other_links = []

        # Find all priority anchor elements in soup for semantic attribute checks
        semantic_priority_urls = set()
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            aria_label = (a_tag.get("aria-label") or "").lower()
            title_attr = (a_tag.get("title") or "").lower()
            rel_attr = (a_tag.get("rel") or "")
            itemprop = (a_tag.get("itemprop") or "")
            
            # Check semantic HTML signals (aria-label, itemprop, rel, parent nav/footer)
            is_semantic_priority = (
                any(kw in aria_label for kw in PRIORITY_SUBPAGE_KEYWORDS) or
                any(kw in title_attr for kw in PRIORITY_SUBPAGE_KEYWORDS) or
                "author" in rel_attr or "member" in itemprop or
                (a_tag.find_parent(["nav", "footer"]) is not None and any(kw in a_tag.get_text().lower() for kw in PRIORITY_SUBPAGE_KEYWORDS))
            )
            if is_semantic_priority:
                full_url = urljoin(base_url, href)
                clean_url = self.canonicalize_url(full_url)
                if clean_url:
                    semantic_priority_urls.add(clean_url)

        for link in found_links:
            if link in semantic_priority_urls or any(kw in link.lower() for kw in PRIORITY_SUBPAGE_KEYWORDS):
                priority_links.append(link)
            else:
                other_links.append(link)

        ordered = priority_links + other_links
        return ordered[:max_links]
