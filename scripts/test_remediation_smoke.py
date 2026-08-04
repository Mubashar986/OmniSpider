"""Smoke tests for the extraction-quality remediation (A1-N12 fixes)."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.scrapers.base import detect_soft_404
from app.services.scrapers.parser import HTMLParserService, PageType


GOODFIRMS_PROFILE_NO_WEBSITE = """
<html><head><title>TekRevol | GoodFirms</title></head>
<body>
  <h1>TekRevol</h1>
  <div class="info">Founded: 2012</div>
</body></html>
"""

GOODFIRMS_PROFILE_SAMEAS = """
<html><head><title>TekRevol | GoodFirms</title>
<script type="application/ld+json">
{"@type": "Organization", "name": "TekRevol",
 "sameAs": ["https://www.linkedin.com/company/tekrevol", "https://tekrevol.com"],
 "numberOfEmployees": {"@type": "QuantitativeValue", "minValue": 50, "maxValue": 249}}
</script></head>
<body>
  <h1>TekRevol</h1>
  <p>Contact: hello@tekrevol.com | Phone: +1 305 555 0100</p>
</body></html>
"""

LISTING_WITH_NEXT = """
<html><head><title>App Developers Miami | GoodFirms</title></head>
<body>
  <a href="https://www.goodfirms.co/company/tekrevol">TekRevol</a>
  <a href="https://www.goodfirms.co/company/acme">Acme</a>
  <a href="https://www.goodfirms.co/software/app-development?page=2" rel="next">Next</a>
  <a href="https://www.goodfirms.co/software/app-development?page=3">&raquo;</a>
</body></html>
"""


def test_fail_closed_profile():
    """N1: unresolved target website must not fabricate an identity."""
    parser = HTMLParserService()
    page = parser.parse_page(GOODFIRMS_PROFILE_NO_WEBSITE, "https://www.goodfirms.co/company/tekrevol")
    assert page.page_type == PageType.DIRECTORY_PROFILE
    assert page.company is None, f"Expected fail-closed, got {page.company}"
    print("PASSED: fail-closed directory profile (N1)")


def test_same_as_fallback_profile():
    """N1/A1: sameAs resolves website; QuantitativeValue employee flattens."""
    parser = HTMLParserService()
    page = parser.parse_page(GOODFIRMS_PROFILE_SAMEAS, "https://www.goodfirms.co/company/tekrevol")
    assert page.company is not None, "company should resolve via sameAs"
    assert page.company.domain == "tekrevol.com", page.company.domain
    assert page.company.company_size == "50-249", page.company.company_size
    assert any(lead.work_email == "hello@tekrevol.com" for lead in page.leads), page.leads
    print("PASSED: sameAs fallback + JSON-LD size (N1/A1)")


def test_pagination_links():
    """N4: rel=next pagination links are harvested on listings."""
    parser = HTMLParserService()
    page = parser.parse_page(LISTING_WITH_NEXT, "https://www.goodfirms.co/software/app-development?page=1")
    assert page.page_type == PageType.DIRECTORY_LISTING
    joined = "\n".join(page.pagination_links)
    assert "page=2" in joined, page.pagination_links
    assert "page=3" in joined, page.pagination_links
    # ?page=1 and ?page=2 must canonicalize to DIFFERENT keys now (issue N4).
    c1 = parser.canonicalize_url("https://www.goodfirms.co/software/app-development?page=1")
    c2 = parser.canonicalize_url("https://www.goodfirms.co/software/app-development?page=2")
    assert c1 != c2, f"pagination dedup broken: {c1} == {c2}"
    print(f"PASSED: pagination extraction + distinct dedup keys (N4): {page.pagination_links}")


def test_soft_404():
    """N10: 200-OK not-found pages are detected; real pages are not."""
    assert detect_soft_404("<html><head><title>404 Not Found</title></head><body><p>Sorry</p></body></html>")
    assert detect_soft_404('<html><body><script id="__next_error__"></script></body></html>')
    assert not detect_soft_404(GOODFIRMS_PROFILE_SAMEAS)
    print("PASSED: soft-404 detection (N10)")


def test_schema_length_caps():
    """N3: oversized fields are capped, not rejected or crash-worthy."""
    from app.schemas.company import CompanyCreateSchema

    company = CompanyCreateSchema(
        name="X", domain="x.com", industry="A" * 1000, company_size="B" * 500,
    )
    assert len(company.industry) == 250, len(company.industry)
    assert len(company.company_size) == 100, len(company.company_size)
    print("PASSED: schema field length caps (N3)")


def test_deobfuscation_and_cfemail():
    """N5: [at]/[dot] obfuscation and data-cfemail are decoded."""
    parser = HTMLParserService()
    obfuscated = "<div>Email us at sales [at] tekrevol [dot] com</div>"
    assert "sales@tekrevol.com" in parser.extract_emails(obfuscated, "tekrevol.com")
    # cfemail for 'hello@tekrevol.com' -> key 0x1b XOR payload (key byte first)
    payload = "1b" + "".join(f"{ord(c) ^ 0x1B:02x}" for c in "hello@tekrevol.com")
    cf = f'<div>Contact <a data-cfemail="{payload}" href="/cdn-cgi/l/email-protection"></a></div>'
    assert "hello@tekrevol.com" in parser.extract_emails(cf, "tekrevol.com")
    print("PASSED: email deobfuscation + cfemail decode (N5)")


if __name__ == "__main__":
    print("Running remediation smoke tests...")
    test_fail_closed_profile()
    test_same_as_fallback_profile()
    test_pagination_links()
    test_soft_404()
    test_schema_length_caps()
    test_deobfuscation_and_cfemail()
    print("ALL REMEDIATION SMOKE TESTS PASSED!")
