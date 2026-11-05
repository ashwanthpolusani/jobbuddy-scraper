import unittest
from unittest.mock import MagicMock
from scraper.config import DEFAULT_CONFIG
from scraper.filters.eligibility import is_eligible, get_compiled_rejection_patterns
from scraper.filters.pre_filter import (
    pre_filter_jobs, normalize_title_for_dedup, deduplicate_and_consolidate_roles
)
from scraper.filters.classifier import normalize_job_classification
from stage1 import process_site_jobs
from stage2 import score_job, make_role_fingerprint


class TestEligibility(unittest.TestCase):
    def setUp(self):
        self.cfg = DEFAULT_CONFIG

    def test_rejection_pattern_caching(self):
        """Verify regex patterns are cached and not recompiled every call."""
        pat1 = get_compiled_rejection_patterns(self.cfg)
        pat2 = get_compiled_rejection_patterns(self.cfg)
        self.assertIs(pat1, pat2)

    def test_india_locations(self):
        """Verify Indian tech hubs are accepted."""
        job = {"title": "Software Engineer", "location": "Bengaluru, Karnataka, India", "core_requirements": "Python, React"}
        ok, _ = is_eligible(self.cfg, job)
        self.assertTrue(ok)

        job_pune = {"title": "Full Stack Dev", "location": "Pune, India", "core_requirements": "Node.js"}
        ok, _ = is_eligible(self.cfg, job_pune)
        self.assertTrue(ok)

    def test_worldwide_remote(self):
        """Verify worldwide remote is accepted under default rules."""
        job = {"title": "Backend Engineer", "location": "Remote, Global", "core_requirements": "Go, Docker"}
        ok, _ = is_eligible(self.cfg, job)
        self.assertTrue(ok)

    def test_region_locked_remote_rejected(self):
        """Verify remote locked to US or restricted regions is rejected."""
        job = {"title": "Frontend Engineer", "location": "Remote - US Only", "core_requirements": "React"}
        ok, reason = is_eligible(self.cfg, job)
        self.assertFalse(ok)
        self.assertIn("Region-locked", reason)

    def test_foreign_country_remote_rejected(self):
        """Foreign country-locked remote postings (Poland, Nigeria, etc.) must be rejected."""
        poland_job = {"title": "Software Engineer", "location": "Warsaw, Poland (Remote)", "core_requirements": "Python"}
        ok, reason = is_eligible(self.cfg, poland_job)
        self.assertFalse(ok)
        self.assertIn("Region-locked", reason)

        nigeria_job = {"title": "Data Analyst", "location": "Lagos, Nigeria - Remote", "core_requirements": "SQL"}
        ok, reason = is_eligible(self.cfg, nigeria_job)
        self.assertFalse(ok)
        self.assertIn("Region-locked", reason)

    def test_foreign_without_visa_rejected(self):
        """Foreign domestic roles without sponsorship must be rejected."""
        job = {"title": "Java Developer", "location": "Chicago, IL, USA", "core_requirements": "Java, Spring"}
        ok, reason = is_eligible(self.cfg, job)
        self.assertFalse(ok)
        self.assertIn("Foreign domestic role", reason)

    def test_visa_sponsorship_accepted(self):
        """Foreign roles with explicit visa sponsorship must be accepted."""
        job = {
            "title": "Systems Engineer",
            "location": "Berlin, Germany",
            "core_requirements": "C++, Linux. Visa sponsorship provided for international applicants."
        }
        ok, _ = is_eligible(self.cfg, job)
        self.assertTrue(ok)

    def test_security_clearance_rejected(self):
        """Roles requiring security clearance must be rejected."""
        job = {
            "title": "Software Engineer",
            "location": "Bengaluru, India",
            "core_requirements": "Must hold active Top Secret security clearance."
        }
        ok, reason = is_eligible(self.cfg, job)
        self.assertFalse(ok)
        self.assertIn("security clearance", reason)

    def test_citizenship_only_rejected(self):
        """Roles requiring domestic citizenship must be rejected."""
        job = {
            "title": "Cloud Architect",
            "location": "Remote",
            "core_requirements": "Role requires US Citizen or Green Card only."
        }
        ok, reason = is_eligible(self.cfg, job)
        self.assertFalse(ok)
        self.assertIn("citizenship", reason)

    def test_foreign_language_tests_rejected(self):
        """Roles requiring foreign language certifications (JLPT, CEFR) must be rejected."""
        job = {
            "title": "Backend Developer",
            "location": "Tokyo, Japan",
            "core_requirements": "Requires JLPT N1 or N2 certification."
        }
        ok, reason = is_eligible(self.cfg, job)
        self.assertFalse(ok)
        self.assertIn("foreign language", reason.lower())

    def test_non_english_title_rejected(self):
        """Non-English titles must be rejected."""
        job = {
            "title": "ソフトウェアエンジニア",
            "location": "Tokyo, Japan",
            "core_requirements": "Python, React"
        }
        ok, reason = is_eligible(self.cfg, job)
        self.assertFalse(ok)
        self.assertIn("non-english", reason.lower())


class TestPreFilter(unittest.TestCase):
    def setUp(self):
        self.cfg = DEFAULT_CONFIG

    def test_senior_exclusion_for_fresher(self):
        """Verify senior roles are pre-filtered out for fresher profile."""
        jobs = [
            {"title": "Junior Software Engineer", "location": "Bengaluru"},
            {"title": "Senior Staff Software Engineer", "location": "Bengaluru"},
            {"title": "Principal Architect", "location": "Hyderabad"},
            {"title": "Software Development Engineer - Intern", "location": "Pune"},
            {"title": "Engineering Manager", "location": "Delhi"}
        ]
        filtered = pre_filter_jobs(self.cfg, jobs)
        titles = [j["title"] for j in filtered]
        self.assertIn("Junior Software Engineer", titles)
        self.assertIn("Software Development Engineer - Intern", titles)
        self.assertNotIn("Senior Staff Software Engineer", titles)
        self.assertNotIn("Principal Architect", titles)
        self.assertNotIn("Engineering Manager", titles)


class TestClassifier(unittest.TestCase):
    def setUp(self):
        self.cfg = DEFAULT_CONFIG

    def test_category_and_link_type_assignment(self):
        """Verify deterministic category and link type assignment."""
        job = {"title": "Data Scientist", "location": "Bengaluru", "link": "https://example.com/job/123"}
        normalize_job_classification(self.cfg, job)
        self.assertEqual(job["category"], "data_ml")
        self.assertEqual(job["link_type"], "direct_apply")

    def test_devops_and_security_categories(self):
        """Verify DevOps and Security classification."""
        devops_job = {"title": "Cloud / DevOps Engineer", "location": "Bengaluru"}
        normalize_job_classification(self.cfg, devops_job)
        self.assertEqual(devops_job["category"], "devops_cloud")

        sec_job = {"title": "Cybersecurity Analyst", "location": "Hyderabad"}
        normalize_job_classification(self.cfg, sec_job)
        self.assertEqual(sec_job["category"], "cybersecurity")

    def test_early_career_program_link_type(self):
        """Early career portal / graduate program pages should be marked as filtered_list."""
        program_job = {
            "title": "University Graduate Program 2026",
            "link": "https://example.com/careers/university-hiring"
        }
        normalize_job_classification(self.cfg, program_job)
        self.assertEqual(program_job["link_type"], "filtered_list")


class TestStage1Processing(unittest.TestCase):
    def setUp(self):
        self.cfg = DEFAULT_CONFIG

    def test_process_site_jobs_relative_urls(self):
        """Verify relative URLs in raw scraped jobs are resolved to absolute URLs."""
        raw_jobs = [
            {
                "title": "Junior Python Developer",
                "location": "Bengaluru, India",
                "link": "/jobs/detail/1001",
                "content": "Python, Django, PostgreSQL",
            }
        ]
        url = "https://boards.greenhouse.io/stripe"
        eligible = process_site_jobs(self.cfg, raw_jobs, url, "Stripe")

        self.assertEqual(len(eligible), 1)
        job = eligible[0]
        self.assertEqual(job["link"], "https://boards.greenhouse.io/jobs/detail/1001")
        self.assertEqual(job["company_name"], "Stripe")
        self.assertEqual(job["source_url"], url)
        self.assertEqual(job["category"], "software_engineering")
        self.assertEqual(job["experience_verdict"], "POSSIBLE")

    def test_process_site_jobs_filters_ineligible(self):
        """Ineligible jobs should not be returned by process_site_jobs."""
        raw_jobs = [
            {
                "title": "Software Engineer",
                "location": "Austin, TX, USA",
                "link": "https://example.com/job/1",
                "content": "Python",
            }
        ]
        eligible = process_site_jobs(self.cfg, raw_jobs, "https://example.com", "ExampleCo")
        self.assertEqual(len(eligible), 0)


class TestStage2Scoring(unittest.TestCase):
    def setUp(self):
        self.cfg = DEFAULT_CONFIG

    def test_score_job_success(self):
        """Verify score_job parses valid Gemini JSON."""
        mock_pool = MagicMock()
        mock_pool.generate.return_value = '{"experience_verdict": "SAFE", "verdict_reason": "0-1 YOE required", "core_requirements": "Python, SQL"}'

        result = score_job(self.cfg, "Looking for a fresher with 0-1 years of experience in Python.", mock_pool)
        self.assertIsNotNone(result)
        self.assertEqual(result["experience_verdict"], "SAFE")
        self.assertEqual(result["verdict_reason"], "0-1 YOE required")

    def test_score_job_empty_text(self):
        """Empty JD text returns None immediately without calling ModelPool."""
        mock_pool = MagicMock()
        result = score_job(self.cfg, "", mock_pool)
        self.assertIsNone(result)
        mock_pool.generate.assert_not_called()

    def test_score_job_gemini_failure_returns_none(self):
        """If ModelPool raises an exception or returns invalid JSON, score_job returns None gracefully."""
        mock_pool = MagicMock()
        mock_pool.generate.side_effect = RuntimeError("Quota exceeded")
        result = score_job(self.cfg, "Some JD text", mock_pool)
        self.assertIsNone(result)


class TestDeduplicationAndConsolidation(unittest.TestCase):
    def setUp(self):
        self.cfg = DEFAULT_CONFIG

    def test_normalize_title_for_dedup(self):
        """Verify title normalization strips location and remote qualifiers cleanly."""
        self.assertEqual(
            normalize_title_for_dedup("Software Engineer, AI Data - Austin, TX (Remote)"),
            "Software Engineer, AI Data"
        )
        self.assertEqual(
            normalize_title_for_dedup("Junior Python Developer (Bangalore)"),
            "Junior Python Developer"
        )
        self.assertEqual(
            normalize_title_for_dedup("Frontend Engineer | Remote"),
            "Frontend Engineer"
        )
        self.assertEqual(
            normalize_title_for_dedup("Data Analyst - Pune / Remote"),
            "Data Analyst"
        )

    def test_deduplicate_and_consolidate_multi_location_roles(self):
        """Verify identical roles across multiple locations are collapsed into 1 job with location preference."""
        shared_jd = "We are seeking a Software Engineer to build scalable distributed data pipelines. Python, SQL."
        raw_jobs = [
            {
                "title": "Software Engineer, AI Data - San Francisco (Remote)",
                "company_name": "Speechify",
                "location": "San Francisco, CA (Remote)",
                "content": shared_jd,
                "link": "https://boards.greenhouse.io/speechify/jobs/1"
            },
            {
                "title": "Software Engineer, AI Data - Bengaluru (Remote)",
                "company_name": "Speechify",
                "location": "Bengaluru, India (Remote)",
                "content": shared_jd,
                "link": "https://boards.greenhouse.io/speechify/jobs/2"
            },
            {
                "title": "Software Engineer, AI Data - London (Remote)",
                "company_name": "Speechify",
                "location": "London, UK (Remote)",
                "content": shared_jd,
                "link": "https://boards.greenhouse.io/speechify/jobs/3"
            },
            {
                "title": "Software Engineer, AI Data - Hyderabad (Remote)",
                "company_name": "Speechify",
                "location": "Hyderabad, India (Remote)",
                "content": shared_jd,
                "link": "https://boards.greenhouse.io/speechify/jobs/4"
            }
        ]

        consolidated = deduplicate_and_consolidate_roles(self.cfg, raw_jobs)
        # Should collapse all 4 postings to exactly 1 consolidated role
        self.assertEqual(len(consolidated), 1)

        job = consolidated[0]
        self.assertEqual(job["company_name"], "Speechify")
        # India tech hub (Bengaluru or Hyderabad) should be chosen as winner
        self.assertIn("India", job["location"])
        self.assertEqual(job["locations_count"], 4)
        self.assertEqual(len(job["other_locations"]), 3)

    def test_deduplication_preserves_distinct_roles(self):
        """Verify different roles with different descriptions from the same company are NOT merged."""
        raw_jobs = [
            {
                "title": "Backend Software Engineer",
                "company_name": "Acme",
                "location": "Bengaluru, India",
                "content": "Build high throughput backend microservices with Go, Kafka, and Kubernetes.",
                "link": "https://acme.com/jobs/1"
            },
            {
                "title": "Frontend Software Engineer",
                "company_name": "Acme",
                "location": "Bengaluru, India",
                "content": "Craft responsive web applications with TypeScript, React, Next.js, and Tailwind CSS.",
                "link": "https://acme.com/jobs/2"
            }
        ]

        consolidated = deduplicate_and_consolidate_roles(self.cfg, raw_jobs)
        self.assertEqual(len(consolidated), 2)
        titles = [j["title"] for j in consolidated]
        self.assertIn("Backend Software Engineer", titles)
        self.assertIn("Frontend Software Engineer", titles)

    def test_make_role_fingerprint(self):
        """Verify role fingerprint generates identical SHA-256 for same role across locations."""
        fp1 = make_role_fingerprint("Speechify", "Software Engineer, AI Data - San Francisco", "Python, SQL data pipelines")
        fp2 = make_role_fingerprint("Speechify", "Software Engineer, AI Data - Bengaluru", "Python, SQL data pipelines")
        fp_different = make_role_fingerprint("Speechify", "Product Designer", "Figma, UI/UX design")

        self.assertEqual(fp1, fp2)
        self.assertNotEqual(fp1, fp_different)


if __name__ == "__main__":
    unittest.main()
