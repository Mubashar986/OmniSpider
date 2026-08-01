import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.scrapers.parser import HTMLParserService, BLOCKLIST_PATH_PATTERNS

def test_canonicalize_url_profile_pages():
    parser = HTMLParserService()
    
    # Test 1: Profile pages with query parameters must strip query strings completely
    url1 = "https://clutch.co/profile/openxcell?sort_by=rating_asc&page=2&verified=true"
    url2 = "https://clutch.co/profile/openxcell?location=US"
    url3 = "https://www.goodfirms.co/company/jploft?filter_by_service=software_dev"
    
    c1 = parser.canonicalize_url(url1)
    c2 = parser.canonicalize_url(url2)
    c3 = parser.canonicalize_url(url3)
    
    print(f"URL 1 Canonical: {c1}")
    print(f"URL 2 Canonical: {c2}")
    print(f"URL 3 Canonical: {c3}")
    
    assert c1 == "https://clutch.co/profile/openxcell", f"Expected clean profile URL, got {c1}"
    assert c2 == "https://clutch.co/profile/openxcell", f"Expected clean profile URL, got {c2}"
    assert c1 == c2, "Profile URLs with different query params must canonicalize to identical key for Redis dedup!"
    assert c3 == "https://goodfirms.co/company/jploft", f"Expected clean company URL, got {c3}"

def test_blocklist_path_patterns():
    # Utility paths that MUST be blocked
    junk_paths = [
        "/cdn-cgi/l/email-protection",
        "/wp-admin/admin-ajax.php",
        "/privacy-policy",
        "/terms-of-service",
        "/advertise-with-us",
        "/get-listed",
        "/press-releases/2026",
        "/blog/best-software-companies",
        "/careers/apply"
    ]
    
    # Lead paths that MUST NOT be blocked
    valid_paths = [
        "/profile/openxcell",
        "/company/jploft",
        "/about-us",
        "/contact",
        "/team"
    ]
    
    for path in junk_paths:
        matched = bool(BLOCKLIST_PATH_PATTERNS.search(path))
        print(f"Junk Path '{path}': Blocked = {matched}")
        assert matched, f"Expected junk path '{path}' to be blocked!"
        
    for path in valid_paths:
        matched = bool(BLOCKLIST_PATH_PATTERNS.search(path))
        print(f"Valid Path '{path}': Blocked = {matched}")
        assert not matched, f"Expected lead path '{path}' NOT to be blocked!"

if __name__ == "__main__":
    print("Running Unit Tests for Pre-Phase 3.2 URL Dedup & Blocklist Fixes...")
    test_canonicalize_url_profile_pages()
    print("PASSED: Profile URL Canonicalization test.")
    test_blocklist_path_patterns()
    print("PASSED: Blocklist Path Patterns test.")
    print("ALL PRE-PHASE 3.2 TESTS PASSED SUCCESSFULLY!")
