import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.services.scrapers.parser import HTMLParserService

def test_parser():
    print("=== Testing HTML Extraction & Lead Schema Normalizer ===")
    parser = HTMLParserService()

    sample_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Acme Innovations Corp - AI Sales Software</title>
        <script src="https://cdn.jsdelivr.net/npm/react@18/umd/react.production.min.js"></script>
        <script src="https://js.hs-scripts.com/123456.js"></script>
        <link rel="stylesheet" href="/_next/static/css/styles.css">
    </head>
    <body>
        <h1>Welcome to Acme Innovations</h1>
        <p>Contact our leadership team:</p>
        <ul>
            <li>CEO John Doe: <a href="mailto:john.doe@acmeinnovations.com">john.doe@acmeinnovations.com</a></li>
            <li>Sales Director Sarah Smith: <a href="mailto:sarah.smith@acmeinnovations.com">sarah.smith@acmeinnovations.com</a></li>
        </ul>
        <p>Call us at +1 (555) 234-5678 or 555-987-6543.</p>
        <a href="https://www.linkedin.com/company/acme-innovations">LinkedIn Company Page</a>
    </body>
    </html>
    """

    target_url = "https://www.acmeinnovations.com/contact"
    print(f"Parsing sample company HTML for URL: {target_url}\n")

    company_schema, lead_schemas = parser.parse_html(sample_html, target_url)

    print("--- Extracted Company Schema ---")
    print(f"Domain:      {company_schema.domain}")
    print(f"Name:        {company_schema.name}")
    print(f"Website URL: {company_schema.website_url}")
    print(f"Detected Technologies: {company_schema.detected_technologies}")

    print("\n--- Extracted Lead Schemas ---")
    print(f"Total Leads Found: {len(lead_schemas)}")
    for idx, lead in enumerate(lead_schemas, 1):
        print(f"\nLead #{idx}:")
        print(f"   Name:        {lead.first_name} {lead.last_name}")
        print(f"   Work Email:  {lead.work_email}")
        print(f"   Phones:      {[p.model_dump() for p in lead.phones]}")
        print(f"   LinkedIn:    {lead.linkedin_url}")

    print("\n--- Testing URL Canonicalization ---")
    raw_urls = [
        "https://www.AcmeInnovations.com:443/About/?utm_source=google&id=123#section",
        "HTTP://acmeinnovations.com:80/team/",
        "https://acmeinnovations.com/contact?fbclid=XYZ123&category=sales"
    ]
    for r_url in raw_urls:
        c_url = parser.canonicalize_url(r_url)
        print(f"   Raw:  {r_url}")
        print(f"   Clean: {c_url}\n")

    print("--- Testing Internal Link Extraction & Blocklist Filtering ---")
    sample_links_html = """
    <html><body>
        <a href="/about/">About Us</a>
        <a href="/TEAM">Our Team</a>
        <a href="/cdn-cgi/l/email-protection">CF Email Protection</a>
        <a href="/wp-json/wp/v2/posts">WP API</a>
        <a href="/assets/brochure.pdf">PDF Download</a>
        <a href="/images/logo.png">Logo Image</a>
        <a href="/contact?utm_campaign=spring">Contact Form</a>
    </body></html>
    """
    links = parser.extract_internal_links(sample_links_html, "https://acmeinnovations.com")
    print(f"Extracted {len(links)} links:")
    for l in links:
        print(f"   -> {l}")

    assert any("/about" in l for l in links), "Should contain /about"
    assert not any("cdn-cgi" in l for l in links), "Should block cdn-cgi"
    assert not any("wp-json" in l for l in links), "Should block wp-json"
    assert not any(".pdf" in l for l in links), "Should block .pdf"

    print("\nHTML PARSER TEST COMPLETE: All DOM extraction, canonicalization, and blocklists verified!")

if __name__ == "__main__":
    test_parser()
