from datetime import timezone
import unittest
from scraper.db import make_job_id, slug_to_company, now_utc
from scraper.ats import process_url
from scraper.ats.greenhouse import extract_slug as gh_extract_slug
from scraper.ats.lever import extract_slug as lever_extract_slug
from scraper.ats.ashby import extract_slug as ashby_extract_slug
from scraper.ats.smartrecruiters import extract_token as sr_extract_token
from scraper.ats.workable import extract_slug as workable_extract_slug
from scraper.ats.workday import extract_params as workday_extract_params
from scraper.ats.eightfold import normalize_eightfold_url


class TestATS(unittest.TestCase):
    # -- Slug / Parameter Extractors -----------------------------------------

    def test_greenhouse_extract_slug(self):
        self.assertEqual(gh_extract_slug("https://boards-api.greenhouse.io/v1/boards/stripe/jobs"), "stripe")
        self.assertEqual(gh_extract_slug("https://boards-api.eu.greenhouse.io/v1/boards/miro/jobs"), "miro")
        self.assertEqual(gh_extract_slug("https://boards.greenhouse.io/airbnb"), "airbnb")
        self.assertEqual(gh_extract_slug("https://boards.greenhouse.io/embed/job_board?for=figma"), "figma")
        self.assertIsNone(gh_extract_slug("https://example.com/careers"))

    def test_lever_extract_slug(self):
        self.assertEqual(lever_extract_slug("https://api.lever.co/v0/postings/palantir"), "palantir")
        self.assertEqual(lever_extract_slug("https://jobs.lever.co/netflix"), "netflix")
        self.assertEqual(lever_extract_slug("https://jobs.lever.co/openai/"), "openai")
        self.assertIsNone(lever_extract_slug("https://example.com/jobs"))

    def test_ashby_extract_slug(self):
        self.assertEqual(ashby_extract_slug("https://api.ashbyhq.com/posting-api/job-board/ramp"), "ramp")
        self.assertEqual(ashby_extract_slug("https://jobs.ashbyhq.com/retool"), "retool")
        self.assertIsNone(ashby_extract_slug("https://example.com"))

    def test_smartrecruiters_extract_token(self):
        self.assertEqual(sr_extract_token("https://jobs.smartrecruiters.com/Square"), "Square")
        self.assertEqual(sr_extract_token("https://smartrecruiters.com/v1/companies/Visa"), "Visa")
        self.assertIsNone(sr_extract_token("https://smartrecruiters.com/jobs"))

    def test_workable_extract_slug(self):
        self.assertEqual(workable_extract_slug("https://apply.workable.com/invideo/"), "invideo")
        self.assertEqual(workable_extract_slug("https://acme.workable.com"), "acme")
        self.assertIsNone(workable_extract_slug("https://workable.com/jobs"))

    def test_workday_extract_params(self):
        url = "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/India-Pune/Software-QA-Engineer_JR19854"
        params = workday_extract_params(url)
        self.assertIsNotNone(params)
        tenant, domain, site = params
        self.assertEqual(tenant, "nvidia")
        self.assertEqual(domain, "nvidia.wd5.myworkdayjobs.com")
        self.assertEqual(site, "NVIDIAExternalCareerSite")

        invalid_url = "https://nvidia.wd5.myworkdayjobs.com/en-US/login"
        self.assertIsNone(workday_extract_params(invalid_url))

    def test_eightfold_normalize_url(self):
        self.assertEqual(
            normalize_eightfold_url("https://micron.eightfold.ai/careers?domain=micron.com"),
            "https://micron.eightfold.ai/api/apply/v2/jobs"
        )
        self.assertEqual(
            normalize_eightfold_url("https://micron.eightfold.ai/api/apply/v2/jobs"),
            "https://micron.eightfold.ai/api/apply/v2/jobs"
        )

    # -- Routing Dispatcher --------------------------------------------------

    def test_process_url_routing(self):
        from unittest.mock import patch
        with patch("scraper.ats.greenhouse.process", return_value=(True, [], "Greenhouse")) as mock_gh:
            _, _, name = process_url("https://boards-api.greenhouse.io/v1/boards/test/jobs")
            self.assertEqual(name, "Greenhouse")
            mock_gh.assert_called_once()

        with patch("scraper.ats.lever.process", return_value=(True, [], "Lever")) as mock_lever:
            _, _, name = process_url("https://api.lever.co/v0/postings/test")
            self.assertEqual(name, "Lever")
            mock_lever.assert_called_once()

        with patch("scraper.ats.ashby.process", return_value=(True, [], "Ashby")) as mock_ashby:
            _, _, name = process_url("https://jobs.ashbyhq.com/test")
            self.assertEqual(name, "Ashby")
            mock_ashby.assert_called_once()

        with patch("scraper.ats.smartrecruiters.process", return_value=(True, [], "SmartRecruiters")) as mock_sr:
            _, _, name = process_url("https://careers.smartrecruiters.com/test")
            self.assertEqual(name, "SmartRecruiters")
            mock_sr.assert_called_once()

        with patch("scraper.ats.workable.process", return_value=(True, [], "Workable")) as mock_workable:
            _, _, name = process_url("https://test.workable.com")
            self.assertEqual(name, "Workable")
            mock_workable.assert_called_once()

        # Unknown domain returns False and "Unknown"
        is_api, jobs, name = process_url("https://careers.google.com/jobs/results")
        self.assertFalse(is_api)
        self.assertEqual(jobs, [])
        self.assertEqual(name, "Unknown")

    # -- Utility Functions ----------------------------------------------------

    def test_slug_to_company(self):
        self.assertEqual(slug_to_company("https://boards-api.greenhouse.io/v1/boards/stripe/jobs"), "Stripe")
        self.assertEqual(slug_to_company("https://api.lever.co/v0/postings/palantir"), "Palantir")
        self.assertEqual(slug_to_company("https://jobs.ashbyhq.com/retool"), "Retool")
        self.assertEqual(slug_to_company("https://apply.workable.com/invideo/"), "Invideo")

    def test_make_job_id_idempotency(self):
        id1 = make_job_id("Google", "Software Engineer", "https://careers.google.com/jobs/123")
        id2 = make_job_id("google", "software engineer ", "https://careers.google.com/jobs/123/")
        self.assertEqual(id1, id2)

    def test_make_job_id_uniqueness(self):
        id1 = make_job_id("Google", "Software Engineer", "https://careers.google.com/jobs/123")
        id2 = make_job_id("Google", "Data Scientist", "https://careers.google.com/jobs/124")
        self.assertNotEqual(id1, id2)

    def test_now_utc(self):
        """Verify now_utc returns timezone-aware UTC datetime."""
        dt = now_utc()
        self.assertIsNotNone(dt.tzinfo)
        self.assertEqual(dt.tzinfo, timezone.utc)


if __name__ == "__main__":
    unittest.main()
