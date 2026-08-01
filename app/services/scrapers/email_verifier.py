import re
import logging
import json
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import dns.resolver

from app.core.redis import get_redis_client

logger = logging.getLogger(__name__)

# Standard RFC 5322 Email Regex
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

DISPOSABLE_DOMAINS = {
    "mailinator.com", "tempmail.com", "guerrillamail.com", "10minutemail.com",
    "trashmail.com", "yopmail.com", "getnada.com", "throwawaymail.com",
    "sharklasers.com", "dispostable.com", "temp-mail.org", "fakeinbox.com"
}
MX_CACHE_TTL_SECONDS = 24 * 60 * 60
SHARED_CACHE_RETRY_SECONDS = 60

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
        self._mx_cache: Dict[str, Tuple[float, List[str]]] = {}
        self._shared_cache_retry_at = 0.0

    def is_syntax_valid(self, email: str) -> bool:
        if not email or not isinstance(email, str):
            return False
        return bool(EMAIL_REGEX.match(email.strip()))

    def is_disposable(self, domain: str) -> bool:
        return domain.lower().strip() in DISPOSABLE_DOMAINS

    def get_mx_records(self, domain: str) -> List[str]:
        domain_clean = domain.lower().strip()
        now = time.monotonic()
        cached = self._mx_cache.get(domain_clean)
        if cached and cached[0] > now:
            return cached[1]
        self._mx_cache.pop(domain_clean, None)

        cache_key = f"mx:{domain_clean}"
        if now >= self._shared_cache_retry_at:
            try:
                redis_value = get_redis_client().get(cache_key)
                if redis_value is not None:
                    records = json.loads(redis_value)
                    if isinstance(records, list) and all(isinstance(record, str) for record in records):
                        self._mx_cache[domain_clean] = (now + MX_CACHE_TTL_SECONDS, records)
                        return records
            except Exception as cache_error:
                # A down Redis instance must not add its connection timeout to every lead.
                self._shared_cache_retry_at = now + SHARED_CACHE_RETRY_SECONDS
                logger.debug("Shared MX cache unavailable for %s: %s", domain_clean, cache_error)

        try:
            resolver = dns.resolver.Resolver()
            resolver.lifetime = self.dns_timeout
            resolver.timeout = self.dns_timeout
            
            answers = resolver.resolve(domain_clean, 'MX')
            mx_hosts = [str(r.exchange).rstrip('.') for r in answers]
            self._store_mx_cache(domain_clean, mx_hosts, now)
            return mx_hosts
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer) as error:
            logger.debug("No MX records for domain %s: %s", domain_clean, error)
            self._store_mx_cache(domain_clean, [], now)
            return []
        except Exception as error:
            # Do not cache resolver outages: a future lead deserves a retry.
            logger.debug("DNS MX lookup failed for domain %s: %s", domain_clean, error)
            return []

    def _store_mx_cache(self, domain: str, records: List[str], now: Optional[float] = None) -> None:
        self._mx_cache[domain] = ((now if now is not None else time.monotonic()) + MX_CACHE_TTL_SECONDS, records)
        current_time = now if now is not None else time.monotonic()
        if current_time < self._shared_cache_retry_at:
            return
        try:
            get_redis_client().setex(f"mx:{domain}", MX_CACHE_TTL_SECONDS, json.dumps(records))
        except Exception as cache_error:
            self._shared_cache_retry_at = current_time + SHARED_CACHE_RETRY_SECONDS
            logger.debug("Could not store shared MX cache for %s: %s", domain, cache_error)

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
