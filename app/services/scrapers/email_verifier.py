import asyncio
import re
import logging
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import aiosmtplib
import dns.resolver

from app.core.config import settings
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
CATCH_ALL_CACHE_TTL_SECONDS = 24 * 60 * 60
SMTP_DOWN_RETRY_SECONDS = 60 * 60
SHARED_CACHE_RETRY_SECONDS = 60
MAX_CONCURRENT_VERIFICATIONS = 10

STATUS_VERIFIED = "verified"
STATUS_CATCH_ALL = "catch_all"
STATUS_UNVERIFIED = "unverified"
STATUS_INVALID = "invalid"
STATUS_DISPOSABLE = "disposable"


@dataclass
class EmailVerificationResult:
    email: str
    domain: str
    is_valid_syntax: bool
    has_mx_records: bool
    is_disposable: bool
    is_deliverable: bool
    mx_records: List[str] = field(default_factory=list)
    status: str = STATUS_UNVERIFIED
    is_catch_all: bool = False
    smtp_checked: bool = False
    error_message: Optional[str] = None


class EmailVerifierService:
    """
    Multi-stage B2B email verification (SRS section 4):
    1. RFC 5322 syntax check
    2. Disposable domain filtering
    3. DNS MX record lookup (local + Redis shared cache)
    4. Non-sending SMTP RCPT TO handshake with catch-all probing
    """
    def __init__(self, dns_timeout: float = 3.0):
        self.dns_timeout = dns_timeout
        self._mx_cache: Dict[str, Tuple[float, List[str]]] = {}
        self._catch_all_cache: Dict[str, Tuple[float, bool]] = {}
        self._smtp_down_until: Dict[str, float] = {}
        self._shared_cache_retry_at = 0.0

    # ------------------------------------------------------------------
    # Stage 1-2: syntax & disposable
    # ------------------------------------------------------------------
    def is_syntax_valid(self, email: str) -> bool:
        if not email or not isinstance(email, str):
            return False
        return bool(EMAIL_REGEX.match(email.strip()))

    def is_disposable(self, domain: str) -> bool:
        return domain.lower().strip() in DISPOSABLE_DOMAINS

    # ------------------------------------------------------------------
    # Stage 3: DNS MX lookup with layered caching
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Stage 4: SMTP RCPT TO handshake (non-sending)
    # ------------------------------------------------------------------
    def _smtp_blocked_for(self, domain: str) -> bool:
        until = self._smtp_down_until.get(domain, 0.0)
        return time.monotonic() < until

    def _known_catch_all(self, domain: str) -> Optional[bool]:
        cached = self._catch_all_cache.get(domain)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        try:
            value = get_redis_client().get(f"smtpca:{domain}")
            if value is not None:
                result = value == "1"
                self._catch_all_cache[domain] = (time.monotonic() + CATCH_ALL_CACHE_TTL_SECONDS, result)
                return result
        except Exception:
            pass
        return None

    def _store_catch_all(self, domain: str, is_catch_all: bool) -> None:
        self._catch_all_cache[domain] = (time.monotonic() + CATCH_ALL_CACHE_TTL_SECONDS, is_catch_all)
        try:
            get_redis_client().setex(f"smtpca:{domain}", CATCH_ALL_CACHE_TTL_SECONDS, "1" if is_catch_all else "0")
        except Exception:
            pass

    async def _smtp_rcpt(self, mx_host: str, recipient: str) -> Tuple[Optional[int], Optional[aiosmtplib.SMTP]]:
        """Open one SMTP session and RCPT-probe a single recipient. Returns (code, client)."""
        client = aiosmtplib.SMTP(
            hostname=mx_host,
            port=settings.SMTP_PORT,
            timeout=settings.SMTP_TIMEOUT,
            source_address=None,
        )
        await client.connect()
        await client.ehlo(settings.SMTP_HELO_DOMAIN)
        await client.mail(settings.SMTP_MAIL_FROM)
        try:
            code, _ = await client.rcpt(recipient)
            return code, client
        except aiosmtplib.SMTPResponseException as exc:
            return exc.code, client

    async def smtp_check(self, email: str, mx_records: List[str]) -> Tuple[str, bool, bool, Optional[str]]:
        """
        Probe the recipient and a random catch-all probe address.
        Returns (status, is_catch_all, smtp_checked, error_message).
        """
        domain = email.rsplit("@", 1)[1].lower()
        if not mx_records:
            return STATUS_INVALID, False, False, "No MX records found for domain"
        if not settings.SMTP_VERIFY_ENABLED or self._smtp_blocked_for(domain):
            return STATUS_UNVERIFIED, False, False, "smtp_skipped"

        known_catch_all = self._known_catch_all(domain)
        probe_address = f"omnispider-probe-{uuid.uuid4().hex[:12]}@{domain}"
        last_error: Optional[str] = None

        for mx_host in mx_records[:2]:
            client: Optional[aiosmtplib.SMTP] = None
            try:
                real_code, client = await self._smtp_rcpt(mx_host, email)

                if real_code == 250:
                    if known_catch_all is True:
                        return STATUS_CATCH_ALL, True, True, None
                    if known_catch_all is False:
                        return STATUS_VERIFIED, False, True, None
                    probe_code, client = await self._smtp_rcpt_reuse(client, probe_address)
                    if probe_code == 250:
                        self._store_catch_all(domain, True)
                        return STATUS_CATCH_ALL, True, True, None
                    if probe_code is not None and 500 <= probe_code < 600:
                        self._store_catch_all(domain, False)
                        return STATUS_VERIFIED, False, True, None
                    return STATUS_UNVERIFIED, False, True, "catch_all_probe_inconclusive"

                if real_code is not None and 500 <= real_code < 600:
                    return STATUS_INVALID, False, True, f"RCPT rejected with {real_code}"

                # 4xx: greylisting / rate limiting — retry later, not a verdict.
                return STATUS_UNVERIFIED, False, True, f"transient SMTP response {real_code}"
            except (aiosmtplib.SMTPConnectError, aiosmtplib.SMTPServerDisconnected, TimeoutError, OSError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.debug("SMTP probe to %s for %s failed: %s", mx_host, domain, last_error)
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.debug("Unexpected SMTP error for %s via %s: %s", domain, mx_host, last_error)
            finally:
                if client is not None:
                    try:
                        await client.quit()
                    except Exception:
                        pass

        # Every MX host was unreachable: back off this domain for an hour.
        self._smtp_down_until[domain] = time.monotonic() + SMTP_DOWN_RETRY_SECONDS
        return STATUS_UNVERIFIED, False, False, last_error or "smtp_unreachable"

    async def _smtp_rcpt_reuse(self, client: aiosmtplib.SMTP, recipient: str) -> Tuple[Optional[int], aiosmtplib.SMTP]:
        try:
            code, _ = await client.rcpt(recipient)
            return code, client
        except aiosmtplib.SMTPResponseException as exc:
            return exc.code, client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def _preflight(self, email: str) -> Tuple[Optional[EmailVerificationResult], str, List[str]]:
        """Stages 1-3. Returns (terminal_result_or_None, domain, mx_records)."""
        if not self.is_syntax_valid(email):
            return EmailVerificationResult(
                email=email, domain="", is_valid_syntax=False, has_mx_records=False,
                is_disposable=False, is_deliverable=False, status=STATUS_INVALID,
                error_message="Invalid email syntax format",
            ), "", []

        domain = email.split("@")[-1].lower()
        if self.is_disposable(domain):
            return EmailVerificationResult(
                email=email, domain=domain, is_valid_syntax=True, has_mx_records=False,
                is_disposable=True, is_deliverable=False, status=STATUS_DISPOSABLE,
                error_message="Disposable / temporary email domain detected",
            ), domain, []

        mx_records = self.get_mx_records(domain)
        if not mx_records:
            return EmailVerificationResult(
                email=email, domain=domain, is_valid_syntax=True, has_mx_records=False,
                is_disposable=False, is_deliverable=False, status=STATUS_INVALID,
                mx_records=[], error_message="No MX records found for domain",
            ), domain, []
        return None, domain, mx_records

    async def verify_email_async(self, email: str) -> EmailVerificationResult:
        email_clean = email.strip() if email else ""
        # _preflight does blocking DNS/Redis I/O; run it in a thread so concurrent
        # batch verification is not serialized behind the event loop (issue N8).
        terminal, domain, mx_records = await asyncio.to_thread(self._preflight, email_clean)
        if terminal is not None:
            return terminal

        status, is_catch_all, smtp_checked, smtp_error = await self.smtp_check(email_clean, mx_records)
        return EmailVerificationResult(
            email=email_clean,
            domain=domain,
            is_valid_syntax=True,
            has_mx_records=True,
            is_disposable=False,
            is_deliverable=status == STATUS_VERIFIED,
            mx_records=mx_records,
            status=status,
            is_catch_all=is_catch_all,
            smtp_checked=smtp_checked,
            error_message=smtp_error,
        )

    def verify_email(self, email: str) -> EmailVerificationResult:
        """Synchronous single-email wrapper (keeps existing call sites working)."""
        return asyncio.run(self.verify_email_async(email))

    def verify_emails(self, emails: List[str]) -> Dict[str, EmailVerificationResult]:
        """
        Batch verification with bounded concurrency (issue N8): SMTP probing is
        latency-bound, so emails are probed in parallel under a semaphore while
        MX/catch-all caches dedupe per domain. Order and crash-guards preserved.
        """
        unique = list(dict.fromkeys(e for e in emails if e))
        if not unique:
            return {}

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_VERIFICATIONS)

        async def _verify_one(email: str) -> EmailVerificationResult:
            async with semaphore:
                try:
                    return await self.verify_email_async(email)
                except Exception as exc:
                    logger.debug("Verification crashed for %s: %s", email, exc)
                    return EmailVerificationResult(
                        email=email, domain="", is_valid_syntax=False, has_mx_records=False,
                        is_disposable=False, is_deliverable=False, status=STATUS_UNVERIFIED,
                        error_message=str(exc),
                    )

        async def _run() -> Dict[str, EmailVerificationResult]:
            results = await asyncio.gather(*(_verify_one(email) for email in unique))
            return dict(zip(unique, results))

        return asyncio.run(_run())
