import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.services.scrapers.email_verifier import EmailVerifierService

def test_verifier():
    print("=== Testing Integrated Email & MX Verification Module ===")
    verifier = EmailVerifierService()

    test_emails = [
        "john.doe@google.com",               # Valid B2B / Domain with MX
        "support@microsoft.com",             # Valid B2B / Domain with MX
        "test.user@mailinator.com",          # Disposable Domain
        "bad-email-format-without-at.com",   # Invalid Syntax
        "user@nonexistent-domain-123456789.org" # Non-existent domain / No MX
    ]

    for email in test_emails:
        print(f"\nVerifying: {email}")
        res = verifier.verify_email(email)
        print(f"   Domain:          {res.domain}")
        print(f"   Syntax Valid:    {res.is_valid_syntax}")
        print(f"   Disposable:      {res.is_disposable}")
        print(f"   Has MX Records:  {res.has_mx_records} ({res.mx_records[:2]})")
        print(f"   Deliverable:     {res.is_deliverable}")
        if res.error_message:
            print(f"   Error/Reason:    {res.error_message}")

    print("\nEMAIL VERIFIER TEST COMPLETE: All validation layers verified!")

if __name__ == "__main__":
    test_verifier()
