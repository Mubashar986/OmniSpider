import unittest

from app.services.scrapers.parser import HTMLParserService


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


if __name__ == "__main__":
    unittest.main()
