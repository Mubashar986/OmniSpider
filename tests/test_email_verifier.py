import unittest
from unittest.mock import MagicMock, patch

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


if __name__ == "__main__":
    unittest.main()
