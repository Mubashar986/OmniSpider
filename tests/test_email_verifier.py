import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import aiosmtplib

from app.services.scrapers.email_verifier import EmailVerifierService


class EmailVerifierServiceTests(unittest.TestCase):
    @patch("app.services.scrapers.email_verifier.get_redis_client")
    @patch("app.services.scrapers.email_verifier.dns.resolver.Resolver")
    def test_mx_records_use_local_then_shared_cache(self, resolver_class, redis_client_factory):
        redis_client = MagicMock()
        redis_client.get.return_value = None
        redis_client_factory.return_value = redis_client
        resolver = resolver_class.return_value
        answer = MagicMock()
        answer.exchange = "mail.example.com."
        resolver.resolve.return_value = [answer]
        verifier = EmailVerifierService()

        self.assertEqual(verifier.get_mx_records("example.com"), ["mail.example.com"])
        self.assertEqual(verifier.get_mx_records("example.com"), ["mail.example.com"])

        self.assertEqual(resolver.resolve.call_count, 1)
        redis_client.setex.assert_called_once_with("mx:example.com", 86400, '["mail.example.com"]')

    @patch("app.services.scrapers.email_verifier.get_redis_client")
    def test_shared_cache_is_used_before_a_dns_lookup(self, redis_client_factory):
        redis_client = MagicMock()
        redis_client.get.return_value = '["mx1.example.com"]'
        redis_client_factory.return_value = redis_client
        verifier = EmailVerifierService()

        self.assertEqual(verifier.get_mx_records("example.com"), ["mx1.example.com"])
        redis_client.setex.assert_not_called()


class SMTVerificationStageTests(unittest.TestCase):
    """Stage 4 (SMTP RCPT TO) behaviour with a mocked SMTP server."""

    def _make_verifier(self):
        redis_client = MagicMock()
        redis_client.get.return_value = None
        verifier = EmailVerifierService()
        verifier.get_mx_records = MagicMock(return_value=["mx.example.com"])
        return verifier, redis_client

    def _smtp_factory(self, rcpt_behaviour):
        """Build an aiosmtplib.SMTP mock whose rcpt() follows rcpt_behaviour(recipient)->code."""
        client = MagicMock()
        client.connect = AsyncMock()
        client.ehlo = AsyncMock()
        client.mail = AsyncMock()
        client.quit = AsyncMock()

        async def _rcpt(recipient):
            code = rcpt_behaviour(recipient)
            if 200 <= code < 300:
                return code, "OK"
            raise aiosmtplib.SMTPResponseException(code, "rejected")

        client.rcpt = AsyncMock(side_effect=_rcpt)
        factory = MagicMock(return_value=client)
        return factory, client

    @patch("app.services.scrapers.email_verifier.get_redis_client")
    @patch("app.services.scrapers.email_verifier.aiosmtplib.SMTP")
    def test_verified_when_real_accepted_and_probe_rejected(self, smtp_factory, redis_factory):
        verifier, _ = self._make_verifier()
        redis_factory.return_value.get.return_value = None
        smtp_factory.side_effect = lambda **_: self._smtp_factory(lambda r: 250 if "probe" not in r else 550)[1]

        result = verifier.verify_email("jane.doe@example.com")

        self.assertEqual(result.status, "verified")
        self.assertTrue(result.is_deliverable)
        self.assertTrue(result.smtp_checked)
        self.assertFalse(result.is_catch_all)

    @patch("app.services.scrapers.email_verifier.get_redis_client")
    @patch("app.services.scrapers.email_verifier.aiosmtplib.SMTP")
    def test_catch_all_when_probe_also_accepted(self, smtp_factory, redis_factory):
        verifier, _ = self._make_verifier()
        redis_factory.return_value.get.return_value = None
        smtp_factory.side_effect = lambda **_: self._smtp_factory(lambda r: 250)[1]

        result = verifier.verify_email("jane.doe@example.com")

        self.assertEqual(result.status, "catch_all")
        self.assertTrue(result.is_catch_all)
        self.assertFalse(result.is_deliverable)

    @patch("app.services.scrapers.email_verifier.get_redis_client")
    @patch("app.services.scrapers.email_verifier.aiosmtplib.SMTP")
    def test_invalid_when_real_rejected_permanently(self, smtp_factory, redis_factory):
        verifier, _ = self._make_verifier()
        redis_factory.return_value.get.return_value = None
        smtp_factory.side_effect = lambda **_: self._smtp_factory(lambda r: 550)[1]

        result = verifier.verify_email("ghost@example.com")

        self.assertEqual(result.status, "invalid")
        self.assertFalse(result.is_deliverable)

    @patch("app.services.scrapers.email_verifier.get_redis_client")
    @patch("app.services.scrapers.email_verifier.aiosmtplib.SMTP")
    def test_unverified_on_transient_greylisting_response(self, smtp_factory, redis_factory):
        verifier, _ = self._make_verifier()
        redis_factory.return_value.get.return_value = None
        smtp_factory.side_effect = lambda **_: self._smtp_factory(lambda r: 450)[1]

        result = verifier.verify_email("jane.doe@example.com")

        self.assertEqual(result.status, "unverified")
        self.assertIn("450", result.error_message)

    @patch("app.services.scrapers.email_verifier.get_redis_client")
    @patch("app.services.scrapers.email_verifier.aiosmtplib.SMTP")
    def test_unreachable_marks_domain_and_skips_next_time(self, smtp_factory, redis_factory):
        verifier, _ = self._make_verifier()
        verifier.get_mx_records = MagicMock(return_value=["mx1.example.com", "mx2.example.com"])
        redis_factory.return_value.get.return_value = None
        client = MagicMock()
        client.connect = AsyncMock(side_effect=aiosmtplib.SMTPConnectError("connection refused"))
        client.quit = AsyncMock()
        smtp_factory.return_value = client

        first = verifier.verify_email("a@example.com")
        second = verifier.verify_email("b@example.com")

        self.assertEqual(first.status, "unverified")
        self.assertFalse(first.smtp_checked)
        self.assertEqual(second.status, "unverified")
        self.assertEqual(second.error_message, "smtp_skipped")
        self.assertEqual(client.connect.await_count, 2)  # 2 MX attempts for first, 0 for second

    @patch("app.services.scrapers.email_verifier.get_redis_client")
    def test_disposable_short_circuits_before_smtp(self, redis_factory):
        verifier, _ = self._make_verifier()
        redis_factory.return_value.get.return_value = None

        result = verifier.verify_email("x@mailinator.com")

        self.assertEqual(result.status, "disposable")
        self.assertFalse(result.is_deliverable)

    @patch("app.services.scrapers.email_verifier.get_redis_client")
    def test_batch_verification_returns_result_per_email(self, redis_factory):
        verifier, _ = self._make_verifier()
        redis_factory.return_value.get.return_value = None
        verifier.smtp_check = AsyncMock(return_value=("verified", False, True, None))

        results = verifier.verify_emails(["a@example.com", "b@example.com", "bad-email"])

        self.assertEqual(results["a@example.com"].status, "verified")
        self.assertEqual(results["bad-email"].status, "invalid")


if __name__ == "__main__":
    unittest.main()
