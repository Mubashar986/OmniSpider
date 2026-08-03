import re
import unittest

from app.services.scrapers.parser import HTMLParserService, PageType


class HTMLParserServiceTests(unittest.TestCase):
    def setUp(self):
        self.parser = HTMLParserService()

    def test_leads_stay_within_their_contact_cards(self):
        html = """
        <script>const seed = 'developer@fixtures.com';</script>
        <form><input placeholder="you@work.com"></form>
        <article class="profile-card">
          <a href="mailto:aminaameer177@acme.com">Email Amina</a>
          <a href="tel:+1 (555) 111-2222">Call</a>
          <a href="https://www.linkedin.com/in/amina-ameer">Profile</a>
        </article>
        <article class="profile-card">
          <a href="mailto:john.doe@acme.com">Email John</a>
          <a href="tel:+1 (555) 333-4444">Call</a>
          <a href="https://www.linkedin.com/in/john-doe">Profile</a>
        </article>
        <a href="https://linkedin.com/company/acme">Company LinkedIn</a>
        <p>reviewer@gmail.com name@domain.com</p>
        """

        _, leads = self.parser.parse_html(html, "https://acme.com/directory-listing")
        by_email = {lead.work_email: lead for lead in leads}

        self.assertEqual(set(by_email), {"aminaameer177@acme.com", "john.doe@acme.com"})
        self.assertEqual((by_email["aminaameer177@acme.com"].first_name, by_email["aminaameer177@acme.com"].last_name), ("Amina", "Ameer"))
        self.assertEqual(by_email["aminaameer177@acme.com"].linkedin_url, "https://www.linkedin.com/in/amina-ameer")
        self.assertEqual(by_email["john.doe@acme.com"].linkedin_url, "https://www.linkedin.com/in/john-doe")
        self.assertEqual([phone.number for phone in by_email["aminaameer177@acme.com"].phones], ["+1 (555) 111-2222"])
        self.assertEqual([phone.number for phone in by_email["john.doe@acme.com"].phones], ["+1 (555) 333-4444"])

    def test_directory_website_requires_a_labelled_external_link(self):
        html = """
        <h1>Paycom</h1>
        <a href="https://goodfirms.co/software/paycom">Internal software page</a>
        <a href="https://www.linkedin.com/company/paycom">LinkedIn</a>
        <a href="https://www.paycom.com/pricing?utm_source=directory">Visit Website</a>
        <script type="application/ld+json">{
          "@type": "Organization", "name": "Paycom", "url": "https://www.paycom.com",
          "industry": "Financial & Payments-20%Healthcare & Medical-20%",
          "numberOfEmployees": "51-200 employees"
        }</script>
        """

        company, _ = self.parser.parse_html(html, "https://goodfirms.co/company/paycom")

        self.assertEqual(company.domain, "paycom.com")
        self.assertEqual(company.website_url, "https://www.paycom.com/")
        self.assertEqual(company.name, "Paycom")
        self.assertEqual(company.company_size, "51-200")
        self.assertEqual(company.industry, "Financial & Payments Healthcare & Medical")

    def test_directory_pages_only_keep_emails_on_the_target_domain(self):
        html = """
        <h1>Paycom</h1>
        <a href="https://www.paycom.com">Visit Website</a>
        <article><a href="mailto:sales@paycom.com">Sales</a></article>
        <article><a href="mailto:reviewer@agency.com">Reviewer</a></article>
        """

        _, leads = self.parser.parse_html(html, "https://goodfirms.co/company/paycom")

        self.assertEqual([lead.work_email for lead in leads], ["sales@paycom.com"])

    def test_canonicalization_preserves_path_case_and_handles_ipv6(self):
        self.assertEqual(
            self.parser.canonicalize_url("https://[2001:db8::1]:443/CaseSensitive/?utm_source=x&id=7#section"),
            "https://[2001:db8::1]/CaseSensitive?id=7",
        )

    def test_company_size_rejects_navigation_numbers_without_context(self):
        self.assertIsNone(self.parser.clean_company_size("Browse all 60+ services"))
        self.assertEqual(self.parser.clean_company_size("Team size: 60+ employees"), "60+")


class PageTypeRouterTests(unittest.TestCase):
    def setUp(self):
        self.parser = HTMLParserService()

    def test_classifies_directory_listing_profile_and_company_site(self):
        self.assertEqual(self.parser.classify_page("https://goodfirms.co/software/project-management"), PageType.DIRECTORY_LISTING)
        self.assertEqual(self.parser.classify_page("https://goodfirms.co/company/paycom"), PageType.DIRECTORY_PROFILE)
        self.assertEqual(self.parser.classify_page("https://clutch.co/profile/acme"), PageType.DIRECTORY_PROFILE)
        self.assertEqual(self.parser.classify_page("https://openxcell.com/about"), PageType.COMPANY_SITE)

    def test_listing_page_harvests_only_profile_links(self):
        html = """
        <a href="https://goodfirms.co/company/acme-dev">Acme</a>
        <a href="https://goodfirms.co/company/beta-soft?sort_by=rating">Beta</a>
        <a href="https://goodfirms.co/about-us">About GoodFirms</a>
        <a href="https://goodfirms.co/blog/top-software">Blog</a>
        <a href="https://external.com/company/evil">External</a>
        """
        page = self.parser.parse_page(html, "https://goodfirms.co/software/custom-software")

        self.assertEqual(page.page_type, PageType.DIRECTORY_LISTING)
        self.assertIsNone(page.company)
        self.assertEqual(page.profile_links, [
            "https://goodfirms.co/company/acme-dev",
            "https://goodfirms.co/company/beta-soft",
        ])

    def test_profile_page_routes_target_website_for_second_hop(self):
        html = """
        <h1>Paycom</h1>
        <a href="https://www.paycom.com">Visit Website</a>
        <article><a href="mailto:sales@paycom.com">Sales</a></article>
        """
        page = self.parser.parse_page(html, "https://goodfirms.co/company/paycom")

        self.assertEqual(page.page_type, PageType.DIRECTORY_PROFILE)
        self.assertEqual(page.company.domain, "paycom.com")
        self.assertEqual(page.target_website, "https://www.paycom.com/")
        self.assertEqual([lead.work_email for lead in page.leads], ["sales@paycom.com"])


class CompanySiteExtractionTests(unittest.TestCase):
    def setUp(self):
        self.parser = HTMLParserService()

    def test_company_site_extracts_firmographics_socials_and_domain_leads(self):
        html = """
        <html><head><title>Acme Software | Custom Development</title>
        <script type="application/ld+json">{
          "@type": "Organization", "name": "Acme Software",
          "description": "Custom software development agency",
          "foundingDate": "2012", "numberOfEmployees": "51-200 employees",
          "address": {"addressLocality": "Austin", "addressCountry": "US"}
        }</script></head><body>
        <a href="tel:+1 415 555 0130">Call us</a>
        <a href="https://www.linkedin.com/company/acme-software">LinkedIn</a>
        <a href="https://twitter.com/acmesoft">Twitter</a>
        <a href="https://www.linkedin.com/in/jane-doe">Jane</a>
        <article><a href="mailto:jane.doe@acme.com">Jane</a><a href="tel:+1 415 555 0101">Call Jane</a></article>
        <article><a href="mailto:partner@otherfirm.com">External partner</a></article>
        <p>Reach reviewer123@gmail.com for nothing</p>
        </body></html>
        """
        page = self.parser.parse_page(html, "https://acme.com/contact")

        self.assertEqual(page.page_type, PageType.COMPANY_SITE)
        company = page.company
        self.assertEqual(company.domain, "acme.com")
        self.assertEqual(company.name, "Acme Software")
        self.assertEqual(company.website_url, "https://acme.com/")
        self.assertEqual(company.company_size, "51-200")
        self.assertEqual(company.hq_phone, "+1 415 555 0130")
        self.assertEqual(company.linkedin_url, "https://www.linkedin.com/company/acme-software")
        self.assertEqual(company.twitter_url, "https://twitter.com/acmesoft")
        self.assertEqual(company.extra_metadata.get("founded_year"), "2012")
        self.assertEqual(company.extra_metadata.get("headquarters"), "Austin, US")
        # Only same-domain business emails become leads.
        self.assertEqual([lead.work_email for lead in page.leads], ["jane.doe@acme.com"])
        self.assertEqual([phone.number for phone in page.leads[0].phones], ["+1 415 555 0101"])

    def test_person_cards_yield_email_candidates_and_seniority(self):
        html = """
        <h2>Our Leadership Team</h2>
        <div class="team-grid">
          <div class="card"><h3>Jane Doe</h3><p>Chief Executive Officer</p>
            <a href="https://www.linkedin.com/in/jane-doe">LinkedIn</a></div>
          <div class="card"><h3>John Smith</h3><p>VP of Engineering</p></div>
          <div class="card"><h3>Services</h3><p>What we do</p></div>
        </div>
        """
        page = self.parser.parse_page(html, "https://acme.com/about")

        self.assertEqual(len(page.persons), 2)
        jane, john = page.persons
        self.assertEqual((jane.first_name, jane.last_name), ("Jane", "Doe"))
        self.assertEqual(jane.seniority, "c_level")
        self.assertEqual(jane.linkedin_url, "https://www.linkedin.com/in/jane-doe")
        self.assertEqual(jane.candidate_emails[0], "jane.doe@acme.com")
        self.assertIn("jane@acme.com", jane.candidate_emails)
        self.assertEqual(john.seniority, "vp")
        self.assertEqual(john.department, "Engineering")

    def test_phone_junk_filtering_and_caps(self):
        html = """
        <article>
          <a href="tel:+1 415 555 0147">Call</a>
          <p>0000000000 1005000000000 +1 415 555 0147</p>
        </article>
        """
        phones = self.parser.extract_phones(html)
        numbers = [phone.number for phone in phones]
        self.assertIn("+1 415 555 0147", numbers)
        self.assertNotIn("0000000000", numbers)
        self.assertNotIn("1005000000000", numbers)
        self.assertEqual(len(numbers), len(set(re.sub(r"\D", "", n) for n in numbers)))


if __name__ == "__main__":
    unittest.main()
