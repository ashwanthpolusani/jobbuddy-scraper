"""Tests for pre_filter, eligibility, and classifier modules."""
import unittest
from scraper.config import DEFAULT_CONFIG, deep_merge
from scraper.filters.eligibility import is_eligible, get_compiled_rejection_patterns
from scraper.filters.pre_filter import pre_filter_jobs
from scraper.filters.classifier import normalize_job_classification


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
        ok, reason = is_eligible(self.cfg, job)
        self.assertTrue(ok)

        job_pune = {"title": "Full Stack Dev", "location": "Pune, India", "core_requirements": "Node.js"}
        ok, reason = is_eligible(self.cfg, job_pune)
        self.assertTrue(ok)

    def test_worldwide_remote(self):
        """Verify worldwide remote is accepted under default rules."""
        job = {"title": "Backend Engineer", "location": "Remote, Global", "core_requirements": "Go, Docker"}
        ok, reason = is_eligible(self.cfg, job)
        self.assertTrue(ok)

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
        ok, reason = is_eligible(self.cfg, job)
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


class TestPreFilter(unittest.TestCase):
    def setUp(self):
        self.cfg = DEFAULT_CONFIG

    def test_senior_exclusion_for_fresher(self):
        """Verify senior roles are pre-filtered out for fresher profile."""
        jobs = [
            {"title": "Junior Software Engineer", "location": "Bengaluru"},
            {"title": "Senior Staff Software Engineer", "location": "Bengaluru"},
            {"title": "Principal Architect", "location": "Hyderabad"},
            {"title": "Software Development Engineer - Intern", "location": "Pune"}
        ]
        filtered = pre_filter_jobs(self.cfg, jobs)
        titles = [j["title"] for j in filtered]
        self.assertIn("Junior Software Engineer", titles)
        self.assertIn("Software Development Engineer - Intern", titles)
        self.assertNotIn("Senior Staff Software Engineer", titles)
        self.assertNotIn("Principal Architect", titles)


class TestClassifier(unittest.TestCase):
    def setUp(self):
        self.cfg = DEFAULT_CONFIG

    def test_category_and_link_type_assignment(self):
        """Verify deterministic category and link type assignment."""
        job = {"title": "Data Scientist", "location": "Bengaluru", "link": "https://example.com/job/123"}
        normalize_job_classification(self.cfg, job)
        self.assertEqual(job["category"], "data_ml")
        self.assertEqual(job["link_type"], "direct_apply")


if __name__ == "__main__":
    unittest.main()
