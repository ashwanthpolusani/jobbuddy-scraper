"""Tests for ATS routers, helpers, and utilities."""
import unittest
from scraper.db import make_job_id, slug_to_company
from scraper.ats.workday import extract_params


class TestATS(unittest.TestCase):
    def test_workday_extract_params(self):
        url = "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/India-Pune/Software-QA-Engineer_JR19854"
        params = extract_params(url)
        self.assertIsNotNone(params)
        tenant, domain, site = params
        self.assertEqual(tenant, "nvidia")
        self.assertEqual(site, "NVIDIAExternalCareerSite")

    def test_slug_to_company(self):
        gh_url = "https://boards-api.greenhouse.io/v1/boards/stripe/jobs"
        self.assertEqual(slug_to_company(gh_url), "Stripe")

        lever_url = "https://api.lever.co/v0/postings/palantir"
        self.assertEqual(slug_to_company(lever_url), "Palantir")

    def test_make_job_id_idempotency(self):
        id1 = make_job_id("Google", "Software Engineer", "https://careers.google.com/jobs/123")
        id2 = make_job_id("google", "software engineer ", "https://careers.google.com/jobs/123/")
        self.assertEqual(id1, id2)


if __name__ == "__main__":
    unittest.main()
