import json
import logging
import os
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, NavigableString, Tag
import tldextract

from app.core.config import settings
from app.schemas.company import CompanyCreateSchema
from app.schemas.lead import LeadCreateSchema, PhoneSchema

logger = logging.getLogger(__name__)

PRIORITY_SUBPAGE_KEYWORDS = ["about", "team", "contact", "leadership", "management", "people", "executives", "staff", "company"]
_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def _load_json_config(filename: str) -> Dict[str, object]:
    try:
        with (_CONFIG_DIR / filename).open(encoding="utf-8") as config_file:
            return json.load(config_file)
    except (OSError, json.JSONDecodeError) as error:
        logger.warning("Unable to load parser config %s: %s", filename, error)
        return {}


def _build_blocklist_regex() -> re.Pattern:
    patterns = [re.escape(pattern) for pattern in settings.get_blocklist_patterns()]
    return re.compile(r"/(?:" + "|".join(patterns) + r")", re.IGNORECASE) if patterns else re.compile(r"$^")


BLOCKLIST_PATH_PATTERNS = _build_blocklist_regex()
BLOCKLIST_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".zip", ".tar", ".gz", ".css", ".js", ".ico", ".mp4", ".mp3", ".xml", ".json"}

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_REGEX = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
LINKEDIN_REGEX = re.compile(r"https?://(?:[a-z]{2,3}\.)?(?:www\.)?linkedin\.com/(?:company|in)/[a-zA-Z0-9_-]+/?", re.IGNORECASE)

FREE_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "hotmail.com",
    "outlook.com", "live.com", "msn.com", "icloud.com", "me.com", "aol.com",
    "proton.me", "protonmail.com", "gmx.com", "mail.com",
}
PLACEHOLDER_EMAILS = {
    "you@work.com", "name@domain.com", "email@example.com", "user@example.com",
    "test@example.com", "john.doe@example.com", "your@email.com",
}
SOCIAL_OR_UTILITY_DOMAINS = {
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "tiktok.com", "pinterest.com", "wa.me", "whatsapp.com",
    "google.com", "maps.google.com", "apple.com", "play.google.com",
}
CONTACT_SCOPE_TAGS = {"article", "li", "tr", "section", "address", "figure", "div", "p"}
TITLE_PATTERN = re.compile(
    r"\b(?:chief\s+(?:executive|technology|operating|financial|marketing|revenue)\s+officer|"
    r"ceo|cto|coo|cfo|cmo|founder|co-?founder|president|vice\s+president|vp|"
    r"director|manager|partner|owner|head\s+of\s+[a-z ]+)\b",
    re.IGNORECASE,
)

DEFAULT_TECH_SIGNATURES = {
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
    "Stripe": [r"js\.stripe\.com"],
}
TECH_SIGNATURES = _load_json_config("tech_signatures.json") or DEFAULT_TECH_SIGNATURES
FIELD_MAPPINGS = _load_json_config("field_mappings.json")
DIRECTORY_PROFILES = _load_json_config("directory_profiles.json")


class HTMLParserService:
    """Extract company and contact data without crossing DOM-card boundaries."""

    @staticmethod
    def extract_domain(url: str) -> str:
        """Return a normalized host, including correct handling of ports and IPv6."""
        if not url:
            return ""
        parsed = urlsplit(url if "://" in url else f"//{url}")
        return (parsed.hostname or "").lower().removeprefix("www.")

    @staticmethod
    def canonicalize_url(url: str) -> str:
        """Normalize host/default ports and remove fragments and common tracking params."""
        if not url:
            return ""
        parsed = urlsplit(url.strip() if "://" in url else f"https://{url.strip()}")
        if not parsed.hostname:
            return ""
        scheme = parsed.scheme.lower() or "https"
        host = parsed.hostname.lower().removeprefix("www.")
        if ":" in host:  # urlsplit().hostname removes IPv6 brackets.
            host = f"[{host}]"
        try:
            port = parsed.port
        except ValueError:
            return ""
        netloc = host if port in (None, 80 if scheme == "http" else 443 if scheme == "https" else None) else f"{host}:{port}"
        path = parsed.path.rstrip("/") or "/"
        profile_paths = {
            profile_path.lower()
            for profile in DIRECTORY_PROFILES.values()
            if isinstance(profile, dict)
            for profile_path in profile.get("profile_paths", [])
        }
        if any(profile_path in path.lower() for profile_path in profile_paths):
            query = ""
        else:
            ignored = settings.get_ignored_query_params()
            query = urlencode(
                [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                 if key.lower() not in ignored and not key.lower().startswith(ignored)],
                doseq=True,
            )
        return urlunsplit((scheme, netloc, path, query, ""))

    @staticmethod
    def split_full_name(full_name: str) -> Tuple[Optional[str], Optional[str]]:
        parts = full_name.strip().split() if full_name else []
        return (parts[0], " ".join(parts[1:]) or None) if parts else (None, None)

    @staticmethod
    def _soup(html: str) -> BeautifulSoup:
        soup = BeautifulSoup(html or "", "html.parser")
        for tag in soup(["script", "style", "template", "noscript"]):
            # JSON-LD is structured company metadata, not visible contact text.
            if tag.name == "script" and tag.get("type", "").lower() == "application/ld+json":
                continue
            tag.decompose()
        return soup

    @staticmethod
    def _visible_text(element: Tag) -> str:
        return " ".join(
            text.strip() for text in element.find_all(string=True)
            if text.strip() and text.parent and text.parent.name not in {"script", "style", "template", "noscript"}
        )

    @staticmethod
    def _clean_email(value: str) -> Optional[str]:
        email = value.strip().lower().strip("<>[](){}.,;:'\"")
        if not EMAIL_REGEX.fullmatch(email):
            return None
        local_part, domain = email.rsplit("@", 1)
        extracted = tldextract.extract(domain)
        if not extracted.domain or not extracted.suffix:
            return None
        clean_domain = ".".join(part for part in (extracted.subdomain, extracted.domain, extracted.suffix) if part)
        return f"{local_part}@{clean_domain}"

    @classmethod
    def is_business_email(cls, email: str) -> bool:
        cleaned = cls._clean_email(email)
        if not cleaned or cleaned in PLACEHOLDER_EMAILS:
            return False
        local_part, domain = cleaned.rsplit("@", 1)
        if domain in FREE_EMAIL_DOMAINS:
            return False
        return local_part not in {"you", "name", "email", "user", "example", "test"}

    @classmethod
    def _emails_in_text(cls, text: str) -> Set[str]:
        return {
            email for match in EMAIL_REGEX.findall(text or "")
            if (email := cls._clean_email(match)) and cls.is_business_email(email)
        }

    @classmethod
    def _emails_in_element(cls, element: Tag) -> Set[str]:
        emails = cls._emails_in_text(cls._visible_text(element))
        for link in element.select('a[href^="mailto:"]'):
            emails.update(cls._emails_in_text(link.get("href", "")[7:].split("?", 1)[0]))
        return emails

    def extract_emails(self, html: str, domain: str = "") -> Set[str]:
        """Extract only visible, non-placeholder business email addresses."""
        return self._emails_in_element(self._soup(html))

    @staticmethod
    def _normalise_phone(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip(" .,-")

    @classmethod
    def _phones_in_element(cls, element: Tag) -> List[PhoneSchema]:
        candidates = PHONE_REGEX.findall(cls._visible_text(element))
        candidates.extend(link.get("href", "")[4:].split("?", 1)[0] for link in element.select('a[href^="tel:"]'))
        phones: List[PhoneSchema] = []
        seen = set()
        for candidate in candidates:
            number = cls._normalise_phone(candidate)
            key = re.sub(r"\D", "", number)
            if len(key) < 10 or key in seen:
                continue
            seen.add(key)
            phones.append(PhoneSchema(number=number, type="mobile" if number.startswith("+") else "office"))
        return phones

    def extract_phones(self, html: str) -> List[PhoneSchema]:
        return self._phones_in_element(self._soup(html))

    @staticmethod
    def _linkedin_urls_in_element(element: Tag, profile_only: bool = False) -> List[str]:
        urls = []
        for link in element.find_all("a", href=True):
            match = LINKEDIN_REGEX.search(link["href"])
            if match:
                candidate = match.group(0).rstrip("/")
                if not profile_only or "/in/" in candidate.lower():
                    urls.append(candidate)
        return list(dict.fromkeys(urls))

    def extract_linkedin_urls(self, html: str) -> List[str]:
        return self._linkedin_urls_in_element(self._soup(html))

    def detect_technologies(self, html: str) -> List[str]:
        return [tech for tech, patterns in TECH_SIGNATURES.items() if any(re.search(pattern, html, re.IGNORECASE) for pattern in patterns)]

    @classmethod
    def _contact_scope(cls, source: Tag) -> Tag:
        """Find the closest meaningful card that does not contain many contacts."""
        fallback = source.parent if source.parent and isinstance(source.parent, Tag) else source
        for ancestor in [source, *source.parents]:
            if not isinstance(ancestor, Tag) or ancestor.name not in CONTACT_SCOPE_TAGS:
                continue
            if len(cls._emails_in_element(ancestor)) <= 3:
                return ancestor
        return fallback

    @staticmethod
    def _name_from_email(email: str) -> Tuple[Optional[str], Optional[str]]:
        local = email.split("@", 1)[0].split("+", 1)[0]
        local = re.sub(r"\d+$", "", local)
        tokens = [token for token in re.split(r"[._-]+", local) if token and token.isalpha()]
        if len(tokens) == 1:
            # A doubled boundary character is a common joined-name pattern: aminaameer -> Amina Ameer.
            joined = re.fullmatch(r"([a-z]{2,}?)([a-z])\2([a-z]{2,})", tokens[0].lower())
            if joined:
                tokens = [joined.group(1) + joined.group(2), joined.group(2) + joined.group(3)]
        if not tokens or tokens[0] in {"info", "contact", "sales", "support", "hello", "admin", "team"}:
            return None, None
        return HTMLParserService.split_full_name(" ".join(token.capitalize() for token in tokens))

    @staticmethod
    def _title_from_text(text: str) -> Optional[str]:
        match = TITLE_PATTERN.search(text)
        return re.sub(r"\s+", " ", match.group(0)).title() if match else None

    def _lead_records(self, soup: BeautifulSoup) -> Iterable[Tuple[str, Tag]]:
        """Yield each email once with its smallest useful DOM scope, in document order."""
        records: Dict[str, Tag] = {}
        for node in soup.find_all(string=True):
            if not isinstance(node, NavigableString) or not node.parent or node.parent.name in {"script", "style", "template", "noscript"}:
                continue
            for email in self._emails_in_text(str(node)):
                scope = self._contact_scope(node.parent)
                previous = records.get(email)
                if previous is None or len(scope.get_text(" ", strip=True)) < len(previous.get_text(" ", strip=True)):
                    records[email] = scope
        for link in soup.select('a[href^="mailto:"]'):
            for email in self._emails_in_text(link.get("href", "")[7:].split("?", 1)[0]):
                scope = self._contact_scope(link)
                previous = records.get(email)
                if previous is None or len(scope.get_text(" ", strip=True)) < len(previous.get_text(" ", strip=True)):
                    records[email] = scope
        return records.items()

    @staticmethod
    def _unwrap_redirect(url: str) -> str:
        parsed = urlsplit(url)
        for key, value in parse_qsl(parsed.query):
            if key.lower() in {"url", "u", "target", "destination", "redirect", "redirect_url"} and value.startswith(("http://", "https://")):
                return value
        return url

    @staticmethod
    def _is_external(candidate_url: str, page_domain: str) -> bool:
        candidate_domain = HTMLParserService.extract_domain(candidate_url)
        return bool(candidate_domain and candidate_domain != page_domain and not candidate_domain.endswith(f".{page_domain}"))

    def extract_target_website(self, soup: BeautifulSoup, page_url: str) -> Optional[str]:
        """Select a labelled external company site, never an arbitrary page-level link."""
        page_domain = self.extract_domain(page_url)
        if not any(directory_domain == page_domain or page_domain.endswith(f".{directory_domain}") for directory_domain in settings.get_directory_domains()):
            return None
        candidates: List[Tuple[int, str]] = []
        for link in soup.find_all("a", href=True):
            candidate = self._unwrap_redirect(urljoin(page_url, link["href"].strip()))
            if not candidate.startswith(("http://", "https://")) or not self._is_external(candidate, page_domain):
                continue
            candidate_domain = self.extract_domain(candidate)
            if any(candidate_domain == blocked or candidate_domain.endswith(f".{blocked}") for blocked in SOCIAL_OR_UTILITY_DOMAINS):
                continue
            context = " ".join(filter(None, [link.get_text(" ", strip=True), link.get("aria-label"), link.get("title"), link.parent.get_text(" ", strip=True) if link.parent else ""])).lower()
            score = 0
            if any(keyword in context for keyword in ("website", "visit site", "visit website", "company site", "official site")):
                score += 100
            if link.get("rel") and "nofollow" not in link.get("rel", []):
                score += 5
            path = urlsplit(candidate).path.rstrip("/")
            if not path:
                score += 10
            if score >= 100:
                candidates.append((score, candidate))
        if not candidates:
            return None
        _, best = max(candidates, key=lambda item: item[0])
        parsed = urlsplit(best)
        return urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))

    @staticmethod
    def clean_company_size(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        normalized = re.sub(r"\s+", " ", value).strip()
        if not re.search(r"\b(?:employees?|staff|team|people|personnel)\b", normalized, re.IGNORECASE):
            return None
        match = re.search(r"(?<!\d)(\d+\s*(?:[-\u2013]|to)\s*\d+|\d+\s*\+?)(?!\d)", normalized)
        return re.sub(r"\s+", "", match.group(1)).replace("\u2013", "-") if match else None

    @staticmethod
    def clean_industry(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        cleaned = re.sub(r"\s*-?\s*\d+(?:\.\d+)?\s*%", "", value)
        cleaned = re.sub(r"\b(?:industry|industry\s+focus)\b\s*:?", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", cleaned)
        parts = [re.sub(r"\s+", " ", part).strip(" -|,;") for part in re.split(r"[|;\n]", cleaned)]
        return "; ".join(dict.fromkeys(part for part in parts if len(part) > 1)) or None

    @classmethod
    def _labelled_value(cls, soup: BeautifulSoup, labels: Tuple[str, ...]) -> Optional[str]:
        """Get compact, visible text around a field label without scanning page navigation."""
        for node in soup.find_all(string=True):
            if not node.parent or node.parent.name in {"script", "style", "template", "noscript"}:
                continue
            if not any(label in node.strip().lower() for label in labels):
                continue
            for ancestor in [node.parent, *list(node.parents)[:3]]:
                if not isinstance(ancestor, Tag):
                    continue
                value = cls._visible_text(ancestor)
                if 0 < len(value) <= 350:
                    return value
        return None

    def _json_ld_organizations(self, soup: BeautifulSoup, page_domain: str) -> List[Tuple[int, Dict[str, object]]]:
        organizations: List[Tuple[int, Dict[str, object]]] = []
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                payload = json.loads(script.string or script.get_text())
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            stack = payload if isinstance(payload, list) else [payload]
            while stack:
                item = stack.pop()
                if isinstance(item, dict) and isinstance(item.get("@graph"), list):
                    stack.extend(item["@graph"])
                if not isinstance(item, dict):
                    continue
                types = item.get("@type", [])
                types = [types] if isinstance(types, str) else types
                if not any(str(type_).lower() in {"organization", "corporation", "localbusiness", "professionalservice"} for type_ in types):
                    continue
                score = 0
                official_url = str(item.get("url", ""))
                if self._is_external(official_url, page_domain):
                    score += 50
                if item.get("name"):
                    score += 10
                organizations.append((score, item))
        return organizations

    @staticmethod
    def _mapped_value(record: Dict[str, object], mapping_name: str, defaults: Tuple[str, ...]) -> Optional[object]:
        mapping = FIELD_MAPPINGS.get(mapping_name, defaults)
        keys = mapping if isinstance(mapping, list) else defaults
        return next((record[key] for key in keys if record.get(key)), None)

    def extract_target_company_info(self, html_content: str, page_url: str) -> Dict[str, Optional[str]]:
        """Extract directory-aware company metadata and a safely canonicalized website."""
        soup = self._soup(html_content)
        page_domain = self.extract_domain(page_url)
        external_website = self.extract_target_website(soup, page_url)
        orgs = self._json_ld_organizations(soup, page_domain)
        best_org = max(orgs, key=lambda item: item[0])[1] if orgs else {}
        json_website_value = self._mapped_value(best_org, "website", ("url", "sameAs", "mainEntityOfPage")) if best_org else ""
        if isinstance(json_website_value, list):
            json_website_value = next((value for value in json_website_value if isinstance(value, str) and value.startswith(("http://", "https://"))), "")
        json_website = str(json_website_value or "")
        website = external_website or (self.canonicalize_url(json_website) if self._is_external(json_website, page_domain) else None)
        if website:
            parsed = urlsplit(website)
            website = urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))
        else:
            parsed = urlsplit(self.canonicalize_url(page_url))
            website = urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))

        directory_profile = DIRECTORY_PROFILES.get(page_domain, {})
        name_selector = directory_profile.get("company_name_selector") if isinstance(directory_profile, dict) else None
        industry_selector = directory_profile.get("industry_selector") if isinstance(directory_profile, dict) else None
        profile_name = soup.select_one(name_selector).get_text(" ", strip=True) if name_selector and soup.select_one(name_selector) else None
        profile_industry = soup.select_one(industry_selector).get_text(" | ", strip=True) if industry_selector and soup.select_one(industry_selector) else None
        h1 = soup.find("h1")
        name_value = self._mapped_value(best_org, "company_name", ("name", "legalName", "alternateName")) if best_org else None
        name = str(name_value or profile_name or (h1.get_text(" ", strip=True) if h1 else "") or page_domain.split(".")[0]).strip()
        industry = self._mapped_value(best_org, "industry", ("industry", "knowsAbout", "genre")) if best_org else None
        if isinstance(industry, list):
            industry = " | ".join(map(str, industry))
        industry = industry or profile_industry or self._labelled_value(soup, ("industry", "industry focus", "industries"))
        size = self._mapped_value(best_org, "company_size", ("numberOfEmployees", "employees", "employeeCount")) if best_org else None
        if isinstance(size, dict):
            size = size.get("value") or size.get("minValue")
        size = size or self._labelled_value(soup, ("company size", "team size", "employees", "employee count"))
        return {
            "domain": self.extract_domain(website),
            "name": name or None,
            "website_url": website,
            "industry": self.clean_industry(str(industry)) if industry else None,
            "company_size": self.clean_company_size(str(size)) if size else None,
        }

    def parse_html(self, html_content: str, url: str) -> Tuple[CompanyCreateSchema, List[LeadCreateSchema]]:
        company_info = self.extract_target_company_info(html_content, url)
        soup = self._soup(html_content)
        company = CompanyCreateSchema(**company_info, detected_technologies=self.detect_technologies(html_content))

        leads: List[LeadCreateSchema] = []
        source_domain = self.extract_domain(url)
        is_directory = any(directory_domain == source_domain or source_domain.endswith(f".{directory_domain}") for directory_domain in settings.get_directory_domains())
        for email, scope in self._lead_records(soup):
            if is_directory and self.extract_domain(f"https://{email.rsplit('@', 1)[1]}") != company.domain:
                continue
            text = self._visible_text(scope)
            first_name, last_name = self._name_from_email(email)
            leads.append(LeadCreateSchema(
                first_name=first_name,
                last_name=last_name,
                title=self._title_from_text(text),
                work_email=email,
                phones=self._phones_in_element(scope),
                linkedin_url=next(iter(self._linkedin_urls_in_element(scope, profile_only=True)), None),
            ))
        return company, leads

    def extract_internal_links(self, html_content: str, base_url: str, max_links: int = 10) -> List[str]:
        """Return unique crawlable same-host links, with high-value pages first."""
        domain = self.extract_domain(base_url)
        found_links = set()
        for a_tag in self._soup(html_content).find_all("a", href=True):
            href = a_tag["href"].strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            full_url = urljoin(base_url, href)
            parsed = urlsplit(full_url)
            if self.extract_domain(full_url) != domain or parsed.path in ("", "/"):
                continue
            if BLOCKLIST_PATH_PATTERNS.search(parsed.path) or os.path.splitext(parsed.path)[1].lower() in BLOCKLIST_EXTENSIONS:
                continue
            if clean_url := self.canonicalize_url(full_url):
                found_links.add(clean_url)
        return sorted(found_links, key=lambda link: (not any(keyword in link.lower() for keyword in PRIORITY_SUBPAGE_KEYWORDS), link))[:max_links]
