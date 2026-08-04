import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.scrapers.parser import HTMLParserService

def test_target_company_identity_extraction():
    parser = HTMLParserService()
    
    # Mock HTML representing a Clutch profile page for OpenXcell
    mock_clutch_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": "OpenXcell",
            "url": "https://www.openxcell.com",
            "numberOfEmployees": "250-999"
        }
        </script>
    </head>
    <body>
        <h1>OpenXcell</h1>
        <div class="industry-name">Custom Software Development</div>
        <a class="website-link-a" href="https://clutch.co/redirect?url=https://www.openxcell.com" target="_blank">Visit Website</a>
        
        <div class="executive-bio">
            <span class="name">Jay Garg</span>
            <span class="person-title">CEO & Founder</span>
            <span class="email">jay@openxcell.com</span>
        </div>
    </body>
    </html>
    """
    
    directory_url = "https://clutch.co/profile/openxcell"
    company, leads = parser.parse_html(mock_clutch_html, directory_url)
    
    print(f"Target Company Domain: {company.domain}")
    print(f"Target Company Name: {company.name}")
    print(f"Website URL: {company.website_url}")
    print(f"Industry: {company.industry}")
    print(f"Company Size: {company.company_size}")
    print(f"Extracted Leads Count: {len(leads)}")
    
    # Assertions for Issue 2.1 (Company Identity)
    assert company.domain == "openxcell.com", f"Expected target domain 'openxcell.com', got '{company.domain}'"
    assert company.domain != "clutch.co", "CRITICAL BUG: Company domain is still being set to directory domain 'clutch.co'!"
    assert company.name == "OpenXcell", f"Expected target company name 'OpenXcell', got '{company.name}'"
    assert company.website_url == "https://www.openxcell.com/", f"Expected target website URL, got '{company.website_url}'"
    
    # Assertions for Issue 2.3 (Firmographics)
    assert company.industry == "Custom Software Development", f"Expected industry 'Custom Software Development', got '{company.industry}'"
    assert company.company_size == "250-999", f"Expected company size '250-999', got '{company.company_size}'"
    
    # Assertions for Issue 3.4 (Executive Designation)
    assert len(leads) > 0, "Expected at least 1 lead to be extracted!"
    lead = leads[0]
    print(f"Lead Name: {lead.first_name} {lead.last_name}")
    print(f"Lead Title: {lead.title}")
    assert lead.title is not None, "CRITICAL BUG: Executive designation lead.title is still NULL!"
    assert "Ceo" in lead.title or "CEO" in lead.title or "Founder" in lead.title, f"Expected executive title, got '{lead.title}'"

if __name__ == "__main__":
    print("Running Unit Tests for Task Pre-Phase 3.3 (Target Attribution & Executive Titles)...")
    test_target_company_identity_extraction()
    print("PASSED: Target Company Identity, Firmographics & Executive Title Extraction Test!")
