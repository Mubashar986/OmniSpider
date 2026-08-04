import json
import logging
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import phonenumbers
import tldextract
from bs4 import BeautifulSoup, NavigableString, Tag
from nameparser import HumanName
from phonenumbers import PhoneNumberType

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
TWITTER_REGEX = re.compile(r"https?://(?:www\.)?(?:twitter\.com|x\.com)/([a-zA-Z0-9_]{2,15})/?(?:[?#][^\s\"']*)?", re.IGNORECASE)

FREE_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "hotmail.com",
    "outlook.com", "live.com", "msn.com", "icloud.com", "me.com", "aol.com",
    "proton.me", "protonmail.com", "gmx.com", "gmx.net", "mail.com",
    "seznam.cz", "web.de", "yandex.com", "zoho.com",
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
TWITTER_RESERVED_SLUGS = {"share", "intent", "home", "hashtag", "search", "i", "explore", "settings"}
CONTACT_SCOPE_TAGS = {"article", "li", "tr", "section", "address", "figure", "div", "p"}
MAX_PHONES_PER_SCOPE = 3
MAX_PERSONS_PER_PAGE = 25
TITLE_PATTERN = re.compile(
    r"\b(?:chief\s+(?:executive|technology|operating|financial|marketing|revenue)\s+officer|"
    r"ceo|cto|coo|cfo|cmo|founder|co-?founder|president|vice\s+president|vp|"
    r"director|manager|partner|owner|head\s+of\s+[a-z ]+)\b",
    re.IGNORECASE,
)
NAME_STOPWORDS = {
    "our", "team", "about", "contact", "leadership", "management", "company", "the",
    "and", "meet", "join", "work", "careers", "services", "service", "home", "blog",
    "get", "started", "learn", "more", "privacy", "terms", "why", "how", "what",
    "who", "we", "are", "us", "your", "their", "his", "her", "all", "view", "read",
    "story", "stories", "values", "mission", "vision", "news", "press", "faq",
}

DEFAULT_TECH_SIGNATURES = {
    "Next.js": {"category": "Framework", "patterns": [r"_next/static", r"__NEXT_DATA__"]},
    "React": {"category": "Framework", "patterns": [r"react\.production\.min\.js", r"react-dom"]},
    "Vue.js": {"category": "Framework", "patterns": [r"vue\.global\.js", r"v-attr"]},
    "WordPress": {"category": "CMS", "patterns": [r"wp-content", r"wp-includes"]},
    "Shopify": {"category": "Ecommerce", "patterns": [r"cdn\.shopify\.com", r"Shopify\.theme"]},
    "Cloudflare": {"category": "CDN & Security", "patterns": [r"cloudflare\.com", r"__cf_chl_opt"]},
    "Google Analytics": {"category": "Analytics", "patterns": [r"googletagmanager\.com", r"gtag"]},
    "Tailwind CSS": {"category": "CSS", "patterns": [r"tailwind", r"tw-"]},
    "Bootstrap": {"category": "CSS", "patterns": [r"bootstrap\.min\.css"]},
    "HubSpot": {"category": "Marketing", "patterns": [r"js\.hs-scripts\.com", r"hubspot"]},
    "Stripe": {"category": "Payments", "patterns": [r"js\.stripe\.com"]},
}


def _load_tech_signatures() -> Tuple[Dict[str, List[str]], Dict[str, str]]:
    """Load signatures supporting both legacy list format and categorized dict format."""
    raw = _load_json_config("tech_signatures.json") or DEFAULT_TECH_SIGNATURES
    patterns: Dict[str, List[str]] = {}
    categories: Dict[str, str] = {}
    for tech_name, spec in raw.items():
        if isinstance(spec, dict):
            patterns[tech_name] = [str(pattern) for pattern in spec.get("patterns", [])]
            categories[tech_name] = str(spec.get("category") or "Detected Stack")
        elif isinstance(spec, list):
            patterns[tech_name] = [str(pattern) for pattern in spec]
            categories[tech_name] = "Detected Stack"
    return patterns, categories


TECH_SIGNATURES, TECH_CATEGORY_MAP = _load_tech_signatures()
FIELD_MAPPINGS = _load_json_config("field_mappings.json")
DIRECTORY_PROFILES = _load_json_config("directory_profiles.json")


class PageType:
    """Routing decision for a fetched page: which extraction strategy applies."""
    DIRECTORY_LISTING = "directory_listing"
    DIRECTORY_PROFILE = "directory_profile"
    COMPANY_SITE = "company_site"


@dataclass
class PersonRecord:
    """A decision-maker discovered on a company site, with email candidates to verify."""
    first_name: str
    last_name: str
    title: Optional[str] = None
    seniority: Optional[str] = None
    department: Optional[str] = None
    linkedin_url: Optional[str] = None
    candidate_emails: List[str] = field(default_factory=list)


@dataclass
class ParsedPage:
    """Router-aware parse result consumed by the Celery pipeline."""
    page_type: str
    company: Optional[CompanyCreateSchema] = None
    leads: List[LeadCreateSchema] = field(default_factory=list)
    profile_links: List[str] = field(default_factory=list)
    pagination_links: List[str] = field(default_factory=list)
    target_website: Optional[str] = None
    persons: List[PersonRecord] = field(default_factory=list)


class HTMLParserService:
    """Extract company and contact data without crossing DOM-card boundaries."""

    # ------------------------------------------------------------------
    # URL helpers
    # ------------------------------------------------------------------
    @staticmethod
    def extract_domain(url: str) -> str:
        """Return a normalized host, including correct handling of ports and IPv6."""
        if not url:
            return ""
        parsed = urlsplit(url if "://" in url else f"//{url}")
        return (parsed.hostname or "").lower().removeprefix("www.")

    @staticmethod
    def _registered_domain(host: str) -> str:
        extracted = tldextract.extract(host or "")
        return ".".join(part for part in (extracted.domain, extracted.suffix) if part)

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
    def _smart_case(name: str) -> str:
        """Title-case only when the source lost casing; repair Mc/Mac prefixes (issue N12)."""
        if not name:
            return name
        fixed = name.title() if (name.islower() or name.isupper()) else name
        return re.sub(r"\bMc([a-z])", lambda match: "Mc" + match.group(1).upper(), fixed)

    # ------------------------------------------------------------------
    # Page classification & listing harvest (two-hop pipeline, WBS P0-B)
    # ------------------------------------------------------------------
    @classmethod
    def _directory_profile_paths(cls, domain: str) -> List[str]:
        profile = DIRECTORY_PROFILES.get(domain, {})
        if not isinstance(profile, dict):
            return []
        return [str(path).lower() for path in profile.get("profile_paths", [])]

    @classmethod
    def classify_page(cls, url: str) -> str:
        """Decide which extraction strategy applies to a URL."""
        domain = cls.extract_domain(url)
        path = urlsplit(url if "://" in url else f"//{url}").path.lower()
        directory_domains = settings.get_directory_domains()
        is_directory = any(domain == d or domain.endswith(f".{d}") for d in directory_domains)
        if not is_directory:
            return PageType.COMPANY_SITE
        for directory_domain in directory_domains:
            if domain == directory_domain or domain.endswith(f".{directory_domain}"):
                if any(profile_path in path for profile_path in cls._directory_profile_paths(directory_domain)):
                    return PageType.DIRECTORY_PROFILE
        return PageType.DIRECTORY_LISTING

    def extract_profile_links(self, html_content: str, base_url: str, max_links: int = 25) -> List[str]:
        """Harvest directory profile links from a listing page (the only links worth crawling there)."""
        domain = self.extract_domain(base_url)
        profile_paths: Set[str] = set()
        for directory_domain in settings.get_directory_domains():
            if domain == directory_domain or domain.endswith(f".{directory_domain}"):
                profile_paths.update(self._directory_profile_paths(directory_domain))
        if not profile_paths:
            return []
        self_url = self.canonicalize_url(base_url)
        found: Set[str] = set()
        for a_tag in self._soup(html_content).find_all("a", href=True):
            href = a_tag["href"].strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            full_url = urljoin(base_url, href)
            if self.extract_domain(full_url) != domain:
                continue
            if not any(profile_path in urlsplit(full_url).path.lower() for profile_path in profile_paths):
                continue
            clean_url = self.canonicalize_url(full_url)
            if clean_url and clean_url != self_url:
                found.add(clean_url)
        return sorted(found)[:max_links]

    def extract_pagination_links(self, html_content: str, base_url: str, max_links: int = 2) -> List[str]:
        """Harvest 'next page' links on directory listings (rel=next / Next-labelled).

        Session-level dedup plus per-page chaining means each listing page dispatches
        only its immediate successor, so coverage walks the full listing one page at
        a time instead of stopping at page 1 (issue N4).
        """
        domain = self.extract_domain(base_url)
        self_url = self.canonicalize_url(base_url)
        found: Set[str] = set()
        for a_tag in self._soup(html_content).find_all("a", href=True):
            href = a_tag["href"].strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            rel = " ".join(a_tag.get("rel", [])).lower()
            classes = " ".join(a_tag.get("class", [])).lower()
            label = " ".join(filter(None, [a_tag.get_text(" ", strip=True), a_tag.get("aria-label"), a_tag.get("title")])).lower()
            is_next = (
                "next" in rel
                or "next" in classes
                or label in {"next", "next page", "next ›", "next »", "›", "»", "→"}
                or label.startswith("next ")
            )
            if not is_next:
                continue
            full_url = urljoin(base_url, href)
            if self.extract_domain(full_url) != domain:
                continue
            if BLOCKLIST_PATH_PATTERNS.search(urlsplit(full_url).path):
                continue
            clean_url = self.canonicalize_url(full_url)
            if clean_url and clean_url != self_url:
                found.add(clean_url)
        return sorted(found)[:max_links]

    # ------------------------------------------------------------------
    # Soup & text helpers
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Email extraction
    # ------------------------------------------------------------------
    @staticmethod
    def _is_public_suffix(label: str) -> bool:
        """True when the label is itself nothing but a public suffix ('com', 'co.uk')."""
        probe = tldextract.extract(label)
        return bool(probe.suffix) and not probe.domain and not probe.subdomain

    @staticmethod
    def _clean_email(value: str) -> Optional[str]:
        email = value.strip().lower().strip("<>[](){}.,;:'\"")
        if not EMAIL_REGEX.fullmatch(email):
            return None
        local_part, domain = email.rsplit("@", 1)
        candidate = domain.rstrip(".")

        def _acceptable(host: str) -> Optional[str]:
            extracted = tldextract.extract(host)
            if extracted.suffix and extracted.domain and not HTMLParserService._is_public_suffix(extracted.domain):
                return ".".join(part for part in (extracted.subdomain, extracted.domain, extracted.suffix) if part)
            return None

        # Page text often fuses trailing words onto the TLD. Two trim passes:
        # 1) segment-wise: "dotlogics.com.read" -> "dotlogics.com"
        host = candidate
        while host and "." in host:
            cleaned = _acceptable(host)
            if cleaned:
                return f"{local_part}@{cleaned}"
            host = host.rsplit(".", 1)[0]
        # 2) char-wise for intra-segment fusion: "jploft.comphone" -> "jploft.com"
        host = candidate
        while host and "." in host:
            cleaned = _acceptable(host)
            if cleaned:
                return f"{local_part}@{cleaned}"
            host = host[:-1].rstrip(".")
        return None

    @classmethod
    def is_business_email(cls, email: str) -> bool:
        cleaned = cls._clean_email(email)
        if not cleaned or cleaned in PLACEHOLDER_EMAILS:
            return False
        local_part, domain = cleaned.rsplit("@", 1)
        if domain in FREE_EMAIL_DOMAINS:
            return False
        return local_part not in {"you", "name", "email", "user", "example", "test"}

    _AT_OBFUSCATION = re.compile(r"\s*(?:\[|\()\s*at\s*(?:\]|\))\s*", re.IGNORECASE)
    _DOT_OBFUSCATION = re.compile(r"\s*(?:\[|\()\s*dot\s*(?:\]|\))\s*", re.IGNORECASE)

    @staticmethod
    def _decode_cfemail(encoded: str) -> Optional[str]:
        """Decode a Cloudflare data-cfemail XOR-obfuscated address (issue N5)."""
        try:
            key = int(encoded[:2], 16)
            decoded = "".join(chr(int(encoded[i:i + 2], 16) ^ key) for i in range(2, len(encoded), 2))
            return decoded or None
        except (ValueError, IndexError):
            return None

    @classmethod
    def _deobfuscate_text(cls, text: str) -> str:
        """Reveal 'name [at] domain [dot] com' style addresses when no plain @ exists."""
        if not text or "@" in text:
            return text or ""
        text = cls._AT_OBFUSCATION.sub("@", text)
        return cls._DOT_OBFUSCATION.sub(".", text) if "@" in text else text

    @classmethod
    def _emails_in_text(cls, text: str) -> Set[str]:
        return {
            email for match in EMAIL_REGEX.findall(cls._deobfuscate_text(text or ""))
            if (email := cls._clean_email(match)) and cls.is_business_email(email)
        }

    @classmethod
    def _emails_in_element(cls, element: Tag) -> Set[str]:
        emails = cls._emails_in_text(cls._visible_text(element))
        for link in element.find_all("a", href=lambda value: isinstance(value, str) and value.lower().startswith("mailto:")):
            emails.update(cls._emails_in_text(link.get("href", "")[7:].split("?", 1)[0]))
        for protected in element.select("[data-cfemail]"):
            decoded = cls._decode_cfemail(protected.get("data-cfemail", ""))
            if decoded:
                emails.update(cls._emails_in_text(decoded))
        return emails

    def extract_emails(self, html: str, domain: str = "") -> Set[str]:
        """Extract only visible, non-placeholder business email addresses."""
        return self._emails_in_element(self._soup(html))

    # ------------------------------------------------------------------
    # Phone extraction (context-scoped, junk-filtered, phonenumbers-typed)
    # ------------------------------------------------------------------
    @staticmethod
    def _normalise_phone(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip(" .,-")

    @staticmethod
    def _classify_phone(number: str) -> str:
        try:
            parsed = phonenumbers.parse(number, settings.PHONE_DEFAULT_REGION)
            number_type = phonenumbers.number_type(parsed)
            if number_type in (PhoneNumberType.MOBILE, PhoneNumberType.VOIP, PhoneNumberType.PAGER):
                return "mobile"
            if number_type in (PhoneNumberType.TOLL_FREE, PhoneNumberType.SHARED_COST):
                return "toll_free"
        except phonenumbers.NumberParseException:
            pass
        return "mobile" if number.startswith("+") else "office"

    @classmethod
    def _phones_in_element(cls, element: Tag) -> List[PhoneSchema]:
        """Extract validated phone numbers via libphonenumber's matcher.

        PhoneNumberMatcher handles international groupings the legacy NANP regex
        missed (issue N6); tel: links remain an explicit high-trust source.
        """
        text = cls._visible_text(element)
        candidates = [match.raw_string for match in phonenumbers.PhoneNumberMatcher(text, settings.PHONE_DEFAULT_REGION)]
        candidates.extend(
            link.get("href", "")[4:].split("?", 1)[0]
            for link in element.find_all("a", href=lambda value: isinstance(value, str) and value.lower().startswith("tel:"))
        )
        phones: List[PhoneSchema] = []
        seen = set()
        for candidate in candidates:
            number = cls._normalise_phone(candidate)
            key = re.sub(r"\D", "", number)
            # Tracking IDs and timestamps are typically 13+ digits and never carry a '+'.
            if len(key) < 10 or len(key) > 15 or (len(key) > 12 and not number.startswith("+")) or key in seen:
                continue
            if len(set(key)) == 1:  # 0000000000-style junk
                continue
            seen.add(key)
            phones.append(PhoneSchema(number=number, type=cls._classify_phone(number)))
            if len(phones) >= MAX_PHONES_PER_SCOPE:
                break
        return phones

    def extract_phones(self, html: str) -> List[PhoneSchema]:
        return self._phones_in_element(self._soup(html))

    # ------------------------------------------------------------------
    # Social links
    # ------------------------------------------------------------------
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

    @classmethod
    def _extract_socials(cls, element: Tag) -> Tuple[Optional[str], Optional[str]]:
        """Company-level LinkedIn (/company/) and Twitter/X handle URL."""
        linkedin = next((url for url in cls._linkedin_urls_in_element(element) if "/company/" in url.lower()), None)
        twitter = None
        for link in element.find_all("a", href=True):
            match = TWITTER_REGEX.search(link["href"])
            if match and match.group(1).lower() not in TWITTER_RESERVED_SLUGS:
                twitter = match.group(0).split("?", 1)[0].split("#", 1)[0].rstrip("/")
                break
        return linkedin, twitter

    @classmethod
    def _socials_from_same_as(cls, best_org: Dict[str, object]) -> Tuple[Optional[str], Optional[str]]:
        """Company socials from JSON-LD sameAs — covers JS-rendered footers Tier 1 never sees (issue A4)."""
        linkedin = twitter = None
        for url in cls._same_as_urls(best_org):
            if linkedin is None:
                match = LINKEDIN_REGEX.search(url)
                if match and "/company/" in match.group(0).lower():
                    linkedin = match.group(0).rstrip("/")
            if twitter is None:
                match = TWITTER_REGEX.search(url)
                if match and match.group(1).lower() not in TWITTER_RESERVED_SLUGS:
                    twitter = match.group(0).split("?", 1)[0].split("#", 1)[0].rstrip("/")
        return linkedin, twitter

    @staticmethod
    def _json_ld_telephone(best_org: Dict[str, object]) -> Optional[str]:
        """HQ phone from schema.org contactPoint/telephone (issue A4)."""
        if not best_org:
            return None
        candidates: List[object] = []
        contact_points = best_org.get("contactPoint") or best_org.get("contactPoints")
        if isinstance(contact_points, dict):
            contact_points = [contact_points]
        if isinstance(contact_points, list):
            candidates.extend(point.get("telephone") for point in contact_points if isinstance(point, dict))
        candidates.append(best_org.get("telephone"))
        for candidate in candidates:
            if candidate and len(re.sub(r"\D", "", str(candidate))) >= 10:
                return str(candidate)
        return None

    # ------------------------------------------------------------------
    # Technographics (categorized)
    # ------------------------------------------------------------------
    @staticmethod
    def _tech_evidence(html: str) -> str:
        """Structural evidence only: asset URLs, inline scripts, element markers.

        Visible prose and anchor targets are excluded so a page merely *mentioning*
        Tailwind/HubSpot in text or outbound links can no longer trigger a
        technographic detection (issue N9).
        """
        soup = BeautifulSoup(html or "", "html.parser")
        parts: List[str] = []
        for tag in soup.find_all(True):
            if tag.name == "a":
                continue
            parts.append(tag.name)
            parts.extend(str(attribute) for attribute in tag.attrs.keys())
            for attribute in ("src", "href", "content", "id", "name", "class"):
                value = tag.get(attribute)
                if isinstance(value, str):
                    parts.append(value)
                elif isinstance(value, (list, tuple)):
                    parts.extend(str(item) for item in value)
            if tag.name == "script":
                inline = tag.string or tag.get_text()
                if inline:
                    parts.append(inline)
        return "\n".join(parts)

    @classmethod
    def _detect_tech_map(cls, html: str) -> Dict[str, str]:
        evidence = cls._tech_evidence(html)
        return {
            tech: TECH_CATEGORY_MAP.get(tech, "Detected Stack")
            for tech, patterns in TECH_SIGNATURES.items()
            if any(re.search(pattern, evidence, re.IGNORECASE) for pattern in patterns)
        }

    def detect_technologies(self, html: str) -> List[str]:
        return list(self._detect_tech_map(html))

    # ------------------------------------------------------------------
    # Contact scoping & lead records
    # ------------------------------------------------------------------
    @classmethod
    def _contact_scope(cls, source: Tag) -> Tag:
        """Find the closest meaningful card, preferring single-contact scopes.

        A scope holding exactly one email guarantees that titles, phones and socials
        read from it belong to that contact (issue N7); multi-contact scopes are only
        a fallback so the email itself is still captured.
        """
        fallback = source.parent if source.parent and isinstance(source.parent, Tag) else source
        candidates = [
            ancestor for ancestor in [source, *source.parents]
            if isinstance(ancestor, Tag) and ancestor.name in CONTACT_SCOPE_TAGS
        ]
        for ancestor in candidates:
            if len(cls._emails_in_element(ancestor)) == 1:
                return ancestor
        for ancestor in candidates:
            if len(cls._emails_in_element(ancestor)) <= 3:
                return ancestor
        return fallback

    # Role/department local-parts never identify a person.
    ROLE_LOCAL_PARTS = {
        "info", "contact", "sales", "support", "hello", "admin", "team", "office",
        "mail", "enquiries", "enquiry", "careers", "jobs", "hr", "marketing", "press",
        "media", "billing", "accounts", "legal", "privacy", "help", "service",
        "services", "inquiry", "inquiries", "connect", "hi", "hey", "welcome",
        "noreply", "no-reply",
    }
    # Single-token local-parts are only accepted as a person's name when the token is
    # a known given name; otherwise guessing would fabricate data (issue N12).
    COMMON_FIRST_NAMES = {
        "james", "john", "robert", "michael", "david", "william", "richard", "joseph",
        "thomas", "charles", "daniel", "matthew", "anthony", "mark", "paul", "steven",
        "andrew", "joshua", "kevin", "brian", "george", "edward", "ryan", "jacob",
        "nicholas", "eric", "jonathan", "justin", "brandon", "adam", "nathan", "peter",
        "luke", "alex", "alexander", "ben", "benjamin", "sam", "samuel", "tom", "joe",
        "chris", "christopher", "max", "leo", "henry", "jack", "oliver", "harry",
        "charlie", "jake", "callum", "mary", "patricia", "jennifer", "linda",
        "elizabeth", "barbara", "susan", "jessica", "sarah", "karen", "nancy", "lisa",
        "margaret", "betty", "sandra", "ashley", "dorothy", "kimberly", "emily",
        "michelle", "amanda", "stephanie", "carol", "laura", "rebecca", "sharon",
        "anna", "emma", "olivia", "ava", "mia", "sophia", "isabella", "charlotte",
        "amelia", "grace", "chloe", "zoe", "lily", "hannah", "ella", "scarlett",
        "maria", "fatima", "aisha", "amina", "zainab", "priya", "anita", "pooja",
        "rahul", "arjun", "raj", "vikram", "sanjay", "deepak", "amit", "rohit",
        "ali", "ahmed", "omar", "hassan", "hussain", "muhammad", "usman", "bilal",
        "hamza", "farhan", "imran", "sara", "carlos", "juan", "luis", "diego",
        "sofia", "lucas", "mateo", "leon", "felix", "oscar", "hugo", "liam", "noah",
        "ethan", "mason", "logan", "lucas", "mia", "evelyn", "harper",
    }

    @staticmethod
    def _name_from_email(email: str) -> Tuple[Optional[str], Optional[str]]:
        local = email.split("@", 1)[0].split("+", 1)[0]
        local = re.sub(r"\d+$", "", local)
        tokens = [token for token in re.split(r"[._-]+", local) if token and token.isalpha()]
        if not tokens or tokens[0].lower() in HTMLParserService.ROLE_LOCAL_PARTS:
            return None, None
        if len(tokens) == 1:
            # A doubled boundary character is a common joined-name pattern: aminaameer -> Amina Ameer.
            joined = re.fullmatch(r"([a-z]{2,}?)([a-z])\2([a-z]{2,})", tokens[0].lower())
            if joined:
                tokens = [joined.group(1) + joined.group(2), joined.group(2) + joined.group(3)]
            elif tokens[0].lower() in HTMLParserService.COMMON_FIRST_NAMES:
                return tokens[0].capitalize(), None
            else:
                # A single unknown token ("johnsmith"): guessing would fabricate a name.
                return None, None
        return HTMLParserService.split_full_name(" ".join(token.capitalize() for token in tokens))

    @staticmethod
    def _title_from_text(text: str) -> Optional[str]:
        match = TITLE_PATTERN.search(text)
        return re.sub(r"\s+", " ", match.group(0)).title() if match else None

    @staticmethod
    def _seniority_from_title(title: Optional[str]) -> Optional[str]:
        if not title:
            return None
        lowered = title.lower()
        if re.search(r"chief|c[eoifoatm]o\b|founder|president|owner|partner|managing\s+director", lowered):
            return "c_level"
        if re.search(r"\bvp\b|vice\s+president", lowered):
            return "vp"
        if re.search(r"director|head\s+of", lowered):
            return "director"
        if re.search(r"manager|lead\b|supervisor", lowered):
            return "manager"
        return "individual_contributor"

    @staticmethod
    def _department_from_title(title: Optional[str]) -> Optional[str]:
        if not title:
            return None
        lowered = title.lower()
        for keyword, department in (
            ("engineer", "Engineering"), ("developer", "Engineering"), ("tech", "Engineering"),
            ("product", "Product"), ("design", "Design"), ("data", "Data"),
            ("sales", "Sales"), ("revenue", "Sales"), ("marketing", "Marketing"),
            ("growth", "Marketing"), ("finance", "Finance"), ("accounting", "Finance"),
            ("hr", "HR"), ("human resources", "HR"), ("people", "HR"),
            ("operations", "Operations"), ("support", "Support"), ("legal", "Legal"),
        ):
            if keyword in lowered:
                return department
        return None

    def _lead_records(self, soup: BeautifulSoup) -> Iterable[Tuple[str, Tag]]:
        """Yield each email once with its smallest useful DOM scope, in document order."""
        records: Dict[str, Tag] = {}

        def _record(email: str, source: Tag) -> None:
            scope = self._contact_scope(source)
            previous = records.get(email)
            if previous is None or len(scope.get_text(" ", strip=True)) < len(previous.get_text(" ", strip=True)):
                records[email] = scope

        for node in soup.find_all(string=True):
            if not isinstance(node, NavigableString) or not node.parent or node.parent.name in {"script", "style", "template", "noscript"}:
                continue
            for email in self._emails_in_text(str(node)):
                _record(email, node.parent)
        for link in soup.find_all("a", href=lambda value: isinstance(value, str) and value.lower().startswith("mailto:")):
            for email in self._emails_in_text(link.get("href", "")[7:].split("?", 1)[0]):
                _record(email, link)
        for protected in soup.select("[data-cfemail]"):
            decoded = self._decode_cfemail(protected.get("data-cfemail", ""))
            for email in self._emails_in_text(decoded or ""):
                _record(email, protected)
        return records.items()

    def _extract_leads(self, soup: BeautifulSoup, allowed_domain: str) -> List[LeadCreateSchema]:
        """Card-scoped lead extraction guarded to emails on the allowed registered domain."""
        allowed_registered = self._registered_domain(allowed_domain)
        leads: List[LeadCreateSchema] = []
        for email, scope in self._lead_records(soup):
            email_domain = email.rsplit("@", 1)[1]
            if allowed_registered and self._registered_domain(email_domain) != allowed_registered:
                continue
            text = self._visible_text(scope)
            first_name, last_name = self._name_from_email(email)
            title = self._title_from_text(text)
            leads.append(LeadCreateSchema(
                first_name=first_name,
                last_name=last_name,
                title=title,
                seniority=self._seniority_from_title(title),
                department=self._department_from_title(title),
                work_email=email,
                phones=self._phones_in_element(scope),
                linkedin_url=next(iter(self._linkedin_urls_in_element(scope, profile_only=True)), None),
            ))
        return leads

    # ------------------------------------------------------------------
    # Directory profile target-company extraction
    # ------------------------------------------------------------------
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

    @staticmethod
    def _same_as_urls(record: Dict[str, object]) -> List[str]:
        same_as = record.get("sameAs") if isinstance(record, dict) else None
        urls = same_as if isinstance(same_as, list) else [same_as]
        return [str(url) for url in urls if isinstance(url, str) and url.startswith(("http://", "https://"))]

    def _website_from_same_as(self, best_org: Dict[str, object], page_domain: str) -> Optional[str]:
        """Directory JSON-LD often lists the company site in sameAs alongside socials."""
        for url in self._same_as_urls(best_org):
            if not self._is_external(url, page_domain):
                continue
            candidate_domain = self.extract_domain(url)
            if any(candidate_domain == blocked or candidate_domain.endswith(f".{blocked}") for blocked in SOCIAL_OR_UTILITY_DOMAINS):
                continue
            canonical = self.canonicalize_url(url)
            if canonical:
                parsed = urlsplit(canonical)
                return urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))
        return None

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

    _SIZE_RANGE = re.compile(r"(?<![\d.])(\d{1,7})\s*(?:[-–—]|to)\s*(\d{1,7})(?![\d.])")
    _SIZE_PLUS = re.compile(r"(?<![\d.])(\d{1,7})\s*\+(?![\d.])")
    _SIZE_INT = re.compile(r"(?<![\d.])(\d{1,7})(?![\d.])")
    _SIZE_KEYWORD = re.compile(r"\b(?:employees?|staff|team|people|personnel|headcount|members?|size)\b", re.IGNORECASE)
    _SIZE_JUNK = re.compile(
        r"\b(?:services?|projects?|reviews?|clients?|years?|ratings?|portfolio|products?|apps?|"
        r"awards?|countries|locations?|offices?|cases?|industries)\b|[%$€£]",
        re.IGNORECASE,
    )
    _SIZE_BARE = re.compile(r"\d{1,7}(?:\s*(?:[-–—]|to)\s*\d{1,7}|\s*\+?)")
    MAX_HEADCOUNT = 10_000_000

    @staticmethod
    def clean_company_size(value: Optional[str]) -> Optional[str]:
        """Normalize an employee-count expression, or None when the value is not a size.

        Accepted: label/keyword context ("Team size: 60+ employees"), and bare values
        that are *entirely* a size expression ("10-49", "250", "60+") as produced by
        JSON-LD numberOfEmployees or definition-list values. Rejected: numbers embedded
        in unrelated prose ("Browse all 60+ services", "4.9 rating", "Founded 2012").
        """
        if not value:
            return None
        normalized = re.sub(r"\s+", " ", str(value)).strip()
        if not normalized:
            return None
        has_keyword = bool(HTMLParserService._SIZE_KEYWORD.search(normalized))
        is_bare = bool(HTMLParserService._SIZE_BARE.fullmatch(normalized))
        if not has_keyword:
            if not is_bare or HTMLParserService._SIZE_JUNK.search(normalized):
                return None
        range_match = HTMLParserService._SIZE_RANGE.search(normalized)
        if range_match:
            low, high = int(range_match.group(1)), int(range_match.group(2))
            if 0 < low < high <= HTMLParserService.MAX_HEADCOUNT:
                return f"{low}-{high}"
            return None
        plus_match = HTMLParserService._SIZE_PLUS.search(normalized)
        if plus_match:
            count = int(plus_match.group(1))
            return f"{count}+" if 0 < count <= HTMLParserService.MAX_HEADCOUNT else None
        int_match = HTMLParserService._SIZE_INT.search(normalized)
        if int_match and (has_keyword or is_bare):
            count = int(int_match.group(1))
            return str(count) if 0 < count <= HTMLParserService.MAX_HEADCOUNT else None
        return None

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
        """Get the *value* attached to a field label, not the label's whole block.

        Resolution order (issue N2): the compact text node itself when it carries
        more than the bare label ("Company Size: 10-49"), then the value sibling
        (dt→dd, th→td, label→span), and only then the old ancestor-text fallback.
        """
        for node in soup.find_all(string=True):
            if not node.parent or not node.parent.name in {"script", "style", "template", "noscript"}:
                continue
            text = " ".join(str(node).split())
            if not text:
                continue
            lowered = text.lower()
            label_hit = next((label for label in labels if label in lowered), None)
            if label_hit is None:
                continue
            remainder = lowered.replace(label_hit, "", 1).strip(" :|-–—•·")
            if remainder and len(text) <= 120:
                return text
            sibling = node.parent.find_next_sibling()
            if isinstance(sibling, Tag):
                sibling_text = cls._visible_text(sibling)
                if 0 < len(sibling_text) <= 200:
                    return sibling_text
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

    @staticmethod
    def _json_ld_size(value: Optional[object]) -> Optional[str]:
        """Flatten schema.org numberOfEmployees shapes into a clean_company_size input."""
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return str(int(value))
        if isinstance(value, dict):
            low, high = value.get("minValue"), value.get("maxValue")
            if isinstance(low, (int, float)) and isinstance(high, (int, float)):
                return f"{int(low)}-{int(high)}"
            scalar = value.get("value") or low or high
            return str(int(scalar)) if isinstance(scalar, (int, float)) else (str(scalar) if scalar else None)
        if isinstance(value, list):
            return next((flattened for item in value if (flattened := HTMLParserService._json_ld_size(item))), None)
        return str(value)

    @staticmethod
    def _json_ld_extra_metadata(best_org: Dict[str, object]) -> Dict[str, object]:
        """Long-tail company facts that have no dedicated column live in extra_metadata."""
        metadata: Dict[str, object] = {}
        if not best_org:
            return metadata
        description = HTMLParserService._mapped_value(best_org, "description", ("description", "about", "summary"))
        if description:
            metadata["description"] = str(description)[:1000]
        founded = HTMLParserService._mapped_value(best_org, "founded_year", ("foundingDate", "dateCreated"))
        if founded:
            metadata["founded_year"] = str(founded)[:10]
        headquarters = HTMLParserService._mapped_value(best_org, "headquarters", ("address", "location", "areaServed"))
        if isinstance(headquarters, dict):
            parts = [headquarters.get(key) for key in ("addressLocality", "addressRegion", "addressCountry")]
            headquarters = ", ".join(str(part) for part in parts if part)
        if headquarters:
            metadata["headquarters"] = str(headquarters)[:200]
        return metadata

    def extract_target_company_info(self, html_content: str, page_url: str) -> Dict[str, Optional[str]]:
        """Extract directory-aware company metadata and a safely canonicalized website."""
        soup = self._soup(html_content)
        page_domain = self.extract_domain(page_url)
        external_website = self.extract_target_website(soup, page_url)
        orgs = self._json_ld_organizations(soup, page_domain)
        best_org = max(orgs, key=lambda item: item[0])[1] if orgs else {}
        # sameAs stays out of this tuple: it needs social-domain filtering, which
        # _website_from_same_as applies below (taking the raw list would key the
        # company to e.g. linkedin.com).
        json_website_value = self._mapped_value(best_org, "website", ("url", "mainEntityOfPage")) if best_org else ""
        if isinstance(json_website_value, list):
            json_website_value = next((value for value in json_website_value if isinstance(value, str) and value.startswith(("http://", "https://"))), "")
        json_website = str(json_website_value or "")
        website = external_website or (self.canonicalize_url(json_website) if self._is_external(json_website, page_domain) else None)
        if not website and best_org:
            website = self._website_from_same_as(best_org, page_domain)
        if website:
            parsed = urlsplit(website)
            website = urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))
        # Fail-closed: when the target's own site cannot be resolved, website/domain
        # stay None. Falling back to the directory page here would key the company row
        # to the directory's domain and silently merge unrelated companies (issue N1).
        return_domain = self.extract_domain(website) if website else None

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
        if not industry:
            # Generic directory markup marks the industry by class ("industry-name",
            # "category-industry"). Bounded: short text, no numeric junk.
            for element in soup.select("[class*=industry]"):
                text = element.get_text(" | ", strip=True)
                if text and len(text) <= 120 and not self._SIZE_JUNK.search(text):
                    industry = text
                    break
        size = self._json_ld_size(self._mapped_value(best_org, "company_size", ("numberOfEmployees", "employees", "employeeCount"))) if best_org else None
        size = size or self._labelled_value(soup, ("company size", "team size", "employees", "employee count"))

        # Socials scoped to the company-name block so directory footer socials never leak in.
        social_scope: Tag = h1.parent if h1 and isinstance(h1.parent, Tag) else soup
        linkedin_url, twitter_url = self._extract_socials(social_scope)
        if not linkedin_url or not twitter_url:
            ld_linkedin, ld_twitter = self._socials_from_same_as(best_org)
            linkedin_url = linkedin_url or ld_linkedin
            twitter_url = twitter_url or ld_twitter

        return {
            "domain": return_domain,
            "name": name or None,
            "website_url": website,
            "industry": self.clean_industry(str(industry)) if industry else None,
            "company_size": self.clean_company_size(str(size)) if size else None,
            "linkedin_url": linkedin_url,
            "twitter_url": twitter_url,
            "extra_metadata": self._json_ld_extra_metadata(best_org),
        }

    # ------------------------------------------------------------------
    # Company-site extraction (second hop: the company's own website)
    # ------------------------------------------------------------------
    def _company_site_info(self, soup: BeautifulSoup, url: str) -> Dict[str, Optional[str]]:
        page_domain = self.extract_domain(url)
        orgs = self._json_ld_organizations(soup, page_domain)
        best_org = max(orgs, key=lambda item: item[0])[1] if orgs else {}

        name_value = self._mapped_value(best_org, "company_name", ("name", "legalName", "alternateName")) if best_org else None
        if not name_value:
            og_site = soup.find("meta", property="og:site_name")
            name_value = og_site.get("content", "").strip() if og_site and og_site.get("content") else None
        if not name_value and soup.title and soup.title.string:
            name_value = re.split(r"[|–—-]", soup.title.string)[0].strip()
        name = str(name_value or page_domain.split(".")[0]).strip()

        industry = self._mapped_value(best_org, "industry", ("industry", "knowsAbout", "genre")) if best_org else None
        if isinstance(industry, list):
            industry = " | ".join(map(str, industry))
        size = self._json_ld_size(self._mapped_value(best_org, "company_size", ("numberOfEmployees", "employees", "employeeCount"))) if best_org else None

        hq_phone = None
        for link in soup.find_all("a", href=lambda value: isinstance(value, str) and value.lower().startswith("tel:")):
            candidate = self._normalise_phone(link.get("href", "")[4:].split("?", 1)[0])
            if len(re.sub(r"\D", "", candidate)) >= 10:
                hq_phone = candidate
                break
        hq_phone = hq_phone or self._json_ld_telephone(best_org)

        linkedin_url, twitter_url = self._extract_socials(soup)
        if not linkedin_url or not twitter_url:
            ld_linkedin, ld_twitter = self._socials_from_same_as(best_org)
            linkedin_url = linkedin_url or ld_linkedin
            twitter_url = twitter_url or ld_twitter

        parsed = urlsplit(self.canonicalize_url(url))
        return {
            "domain": page_domain,
            "name": name or None,
            "website_url": urlunsplit((parsed.scheme, parsed.netloc, "/", "", "")),
            "industry": self.clean_industry(str(industry)) if industry else None,
            "company_size": self.clean_company_size(str(size)) if size else None,
            "hq_phone": hq_phone,
            "linkedin_url": linkedin_url,
            "twitter_url": twitter_url,
            "extra_metadata": self._json_ld_extra_metadata(best_org),
        }

    # ------------------------------------------------------------------
    # Decision-maker discovery (person cards + email pattern candidates)
    # ------------------------------------------------------------------
    @classmethod
    def _looks_like_person_name(cls, text: str) -> bool:
        if not text or not 5 <= len(text) <= 40:
            return False
        tokens = text.split()
        if not 2 <= len(tokens) <= 4:
            return False
        if TITLE_PATTERN.search(text):
            return False
        for token in tokens:
            if not re.fullmatch(r"[A-Za-z][A-Za-z.'-]*", token):
                return False
            if token.lower().strip(".',-") in NAME_STOPWORDS:
                return False
        if not any(token[0].isupper() for token in tokens):
            return False
        parsed = HumanName(text)
        return bool(parsed.first and parsed.last)

    @staticmethod
    def _email_candidates(first_name: str, last_name: str, domain: str) -> List[str]:
        first = re.sub(r"[^a-z]", "", (first_name or "").lower())
        last = re.sub(r"[^a-z]", "", (last_name or "").lower())
        if not first or not last or not domain:
            return []
        return [
            f"{first}.{last}@{domain}",
            f"{first}{last}@{domain}",
            f"{first[0]}{last}@{domain}",
            f"{first}@{domain}",
        ]

    def _extract_persons(self, soup: BeautifulSoup, company_domain: str) -> List[PersonRecord]:
        """Discover decision-makers from team/about page person cards."""
        persons: List[PersonRecord] = []
        seen_names = set()
        for element in soup.find_all(["h2", "h3", "h4", "h5", "strong", "b"]):
            name_text = element.get_text(" ", strip=True)
            if not self._looks_like_person_name(name_text):
                continue
            parsed_name = HumanName(name_text)
            dedupe_key = (parsed_name.first.lower(), parsed_name.last.lower())
            if dedupe_key in seen_names:
                continue
            # Find the smallest ancestor card that carries this person's title.
            card: Optional[Tag] = None
            for ancestor in [element, *list(element.parents)[:4]]:
                if not isinstance(ancestor, Tag):
                    continue
                card_text = self._visible_text(ancestor)
                if 20 <= len(card_text) <= 400 and TITLE_PATTERN.search(card_text):
                    card = ancestor
                    break
            if card is None:
                continue
            # Prefer the full title line inside the card ("VP of Engineering"),
            # falling back to the bare keyword match.
            title = None
            for text_bit in card.find_all(string=True):
                bit = " ".join(str(text_bit).split())
                if not bit or bit == name_text or len(bit) > 100:
                    continue
                if TITLE_PATTERN.search(bit):
                    title = bit
                    break
            if title is None:
                title = self._title_from_text(self._visible_text(card).replace(name_text, " ", 1))
            seen_names.add(dedupe_key)
            persons.append(PersonRecord(
                first_name=self._smart_case(parsed_name.first),
                last_name=self._smart_case(parsed_name.last),
                title=title,
                seniority=self._seniority_from_title(title),
                department=self._department_from_title(title),
                linkedin_url=next(iter(self._linkedin_urls_in_element(card, profile_only=True)), None),
                candidate_emails=self._email_candidates(parsed_name.first, parsed_name.last, company_domain),
            ))
            if len(persons) >= MAX_PERSONS_PER_PAGE:
                break
        return persons

    # ------------------------------------------------------------------
    # Page-type routed parsing
    # ------------------------------------------------------------------
    def parse_page(self, html_content: str, url: str) -> ParsedPage:
        page_type = self.classify_page(url)
        soup = self._soup(html_content)

        if page_type == PageType.DIRECTORY_LISTING:
            return ParsedPage(
                page_type=page_type,
                profile_links=self.extract_profile_links(html_content, url),
                pagination_links=self.extract_pagination_links(html_content, url),
            )

        if page_type == PageType.DIRECTORY_PROFILE:
            company_info = self.extract_target_company_info(html_content, url)
            if not company_info.get("domain"):
                # Fail-closed (issue N1): an unresolved target identity must never
                # become a company row keyed to the directory's own domain, and the
                # directory's own emails must never be saved as that "company's" leads.
                logger.warning("Directory profile target website unresolved; nothing persisted: %s", url)
                return ParsedPage(page_type=page_type)
            company = CompanyCreateSchema(**company_info)
            leads = self._extract_leads(soup, company.domain)
            source_domain = self.extract_domain(url)
            target_website = company.website_url if company.domain and company.domain != source_domain else None
            return ParsedPage(page_type=page_type, company=company, leads=leads, target_website=target_website)

        company_info = self._company_site_info(soup, url)
        tech_map = self._detect_tech_map(html_content)
        company = CompanyCreateSchema(
            **company_info,
            detected_technologies=list(tech_map),
            tech_category_map=tech_map,
        )
        leads = self._extract_leads(soup, company.domain)
        persons = self._extract_persons(soup, company.domain)
        return ParsedPage(page_type=PageType.COMPANY_SITE, company=company, leads=leads, persons=persons)

    def parse_html(self, html_content: str, url: str) -> Tuple[CompanyCreateSchema, List[LeadCreateSchema]]:
        """Backwards-compatible wrapper returning (company, leads)."""
        page = self.parse_page(html_content, url)
        return page.company, page.leads

    # ------------------------------------------------------------------
    # Recursive crawl link extraction (company sites)
    # ------------------------------------------------------------------
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
