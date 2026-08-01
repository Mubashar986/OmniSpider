import sys
import os

# Add root directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.scrapers.parser import HTMLParserService

def test_extract_emails():
    parser = HTMLParserService()
    
    dirty_html = """
    <div>Contact Us: sales@jploft.comphone: +1 (415) 555-0123</div>
    <div>Agency: hi@goodface.agency</div>
    <div>Dot Suffix: contact@dotlogics.com.read</div>
    <div>Valid: contact@openxcell.com</div>
    """
    emails = parser.extract_emails(dirty_html, "jploft.com")
    print(f"Extracted Emails: {emails}")
    
    assert "sales@jploft.com" in emails, "Failed to extract clean email before 'phone:'"
    assert "hi@goodface.agency" in emails, "Failed to extract long TLD email '.agency'"
    assert "contact@dotlogics.com" in emails, "Failed dot-suffix cleanup for '.com.read'"
    assert "contact@dotlogics.com.read" not in emails, "Dot-suffix '.com.read' was improperly retained!"
    assert "contact@openxcell.com" in emails

def test_extract_phones():
    parser = HTMLParserService()
    
    dirty_html = """
    <p>Call our US office at +1 (415) 555-0123 or direct line 415-555-0199.</p>
    <p>UK office: +44 20 8366 1177</p>
    """
    phones = parser.extract_phones(dirty_html)
    print(f"Extracted Phones: {phones}")
    
    assert len(phones) >= 2, f"Expected at least 2 phone numbers, got {len(phones)}"
    phone_numbers = [p.number for p in phones]
    print(f"Phone Numbers: {phone_numbers}")

if __name__ == "__main__":
    print("Running Unit Tests for Extractor Fixes...")
    test_extract_emails()
    print("PASSED: Email extraction test.")
    test_extract_phones()
    print("PASSED: Phone extraction test.")
    print("ALL TESTS PASSED SUCCESSFULLY!")
