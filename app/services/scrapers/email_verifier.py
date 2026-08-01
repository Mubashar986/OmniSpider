import re
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional
import dns.resolver

from app.core.config import settings

logger = logging.getLogger(__name__)

# Standard RFC 5322 Email Regex
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

DISPOSABLE_DOMAINS = {
    "mailinator.com", "tempmail.com", "guerrillamail.com", "10minutemail.com",
    "trashmail.com", "yopmail.com", "getnada.com", "throwawaymail.com",
    "sharklasers.com", "dispostable.com", "temp-mail.org", "fakeinbox.com"
}

@dataclass
class EmailVerificationResult:
    email: str
    domain: str
    is_valid_syntax: bool
    has_mx_records: bool
    is_disposable: bool
    is_deliverable: bool
    mx_records: List[str]
    error_message: Optional[str] = None

class EmailVerifierService:
    """
    Service for validating B2B emails via Syntax Regex,
    Disposable Domain check, and DNS MX record lookup.
    """
    def __init__(self, dns_timeout: float = 3.0):
        self.dns_timeout = dns_timeout
        self._mx_cache: Dict[str, List[str]] = {}

    def is_syntax_valid(self, email: str) -> bool:
        if not email or not isinstance(email, str):
            return False
        return bool(EMAIL_REGEX.match(email.strip()))

    def is_disposable(self, domain: str) -> bool:
        return domain.lower().strip() in DISPOSABLE_DOMAINS

    def get_mx_records(self, domain: str) -> List[str]:
        domain_clean = domain.lower().strip()
        
        # Tier 1: Process-local in-memory cache
        if domain_clean in self._mx_cache:
            return self._mx_cache[domain_clean]

        # Tier 2: Redis shared cache (Issue 22 Fix)
        try:
            from app.core.redis import get_redis_client
            import json
            r = get_redis_client()
            cached_val = r.get(f"mx:{domain_clean}")
            if cached_val:
                mx_hosts = json.loads(cached_val)
                self._mx_cache[domain_clean] = mx_hosts
                return mx_hosts
        except Exception:
            pass  # Fallback to direct DNS lookup if Redis unavailable

        # Tier 3: Direct DNS lookup
        try:
            resolver = dns.resolver.Resolver()
            resolver.nameservers = settings.get_dns_servers()
            resolver.lifetime = self.dns_timeout
            resolver.timeout = self.dns_timeout
            
            answers = resolver.resolve(domain_clean, 'MX')
            mx_hosts = [str(r.exchange).rstrip('.') for r in answers]
            self._mx_cache[domain_clean] = mx_hosts

            # Write back to Redis shared cache with 24h TTL (86400s)
            try:
                from app.core.redis import get_redis_client
                import json
                r = get_redis_client()
                r.setex(f"mx:{domain_clean}", 86400, json.dumps(mx_hosts))
            except Exception:
                pass

            return mx_hosts
        except Exception as e:
            logger.debug(f"DNS MX Lookup failed for domain {domain_clean}: {e}")
            self._mx_cache[domain_clean] = []
            return []

    def verify_email(self, email: str) -> EmailVerificationResult:
        email_clean = email.strip() if email else ""
        
        # 1. Syntax Check
        if not self.is_syntax_valid(email_clean):
            return EmailVerificationResult(
                email=email_clean,
                domain="",
                is_valid_syntax=False,
                has_mx_records=False,
                is_disposable=False,
                is_deliverable=False,
                mx_records=[],
                error_message="Invalid email syntax format"
            )

        domain = email_clean.split("@")[-1].lower()

        # 2. Disposable Check
        if self.is_disposable(domain):
            return EmailVerificationResult(
                email=email_clean,
                domain=domain,
                is_valid_syntax=True,
                has_mx_records=False,
                is_disposable=True,
                is_deliverable=False,
                mx_records=[],
                error_message="Disposable / temporary email domain detected"
            )

        # 3. DNS MX Record Lookup
        mx_records = self.get_mx_records(domain)
        has_mx = len(mx_records) > 0

        return EmailVerificationResult(
            email=email_clean,
            domain=domain,
            is_valid_syntax=True,
            has_mx_records=has_mx,
            is_disposable=False,
            is_deliverable=has_mx,
            mx_records=mx_records,
            error_message=None if has_mx else "No MX records found for domain"
        )
