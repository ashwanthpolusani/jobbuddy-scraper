"""
tests/test_performance_benchmarks.py - Micro-benchmarks for critical path operations.
Guarantees sub-millisecond execution for core filtering, multi-location deduplication,
and HTML cleaning, ensuring the pipeline never stalls under massive scrapers.
"""
import time
import unittest

from scraper.filters.pre_filter import deduplicate_and_consolidate_roles, pre_filter_jobs, normalize_title_for_dedup
from scraper.jd_fetcher import extract_text_from_html
from scraper.db import make_job_id


class TestPerformanceBenchmarks(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "locations": {
                "primary_country": "India",
                "allowed_cities": ["All India"],
                "indian_tech_hubs": ["Bengaluru", "Hyderabad", "Pune", "Mumbai", "Delhi", "Noida", "Gurugram"],
                "remote_rules": {
                    "allow_worldwide_remote": True,
                    "reject_region_locked_remote": True,
                    "restricted_regions": ["us", "uk", "canada", "germany"],
                    "restricted_timezones": ["PST", "EST"]
                },
                "international_visa_rules": {
                    "accept_foreign_roles_only_if_sponsored": True,
                    "accept_visa_sponsorship": True,
                    "sponsorship_keywords": ["visa sponsorship"]
                }
            },
            "experience": {
                "exclude_senior_roles": True,
                "senior_title_patterns": [
                    "senior", "staff", "principal", "lead", "manager", "director", "vp",
                    "sr", "sr.", "iii", "iv", "sde 2", "sde-2", "sde ii", "sde-ii"
                ],
                "junior_title_patterns": ["intern", "trainee", "fresher", "entry-level", "associate"]
            },
            "skills": {
                "domain": "tech",
                "tech_keywords": ["software", "developer", "engineer", "sde", "data", "ai", "cloud"],
                "non_tech_exclude_keywords": ["sales", "marketing", "hr", "finance", "legal"]
            },
            "hard_rejection_rules": {
                "reject_security_clearance": True,
                "reject_domestic_citizenship_only": True,
                "reject_non_english_titles": True,
                "reject_mandatory_foreign_language": True,
                "reject_explicit_no_visa_sponsorship": True
            }
        }

    def test_multi_location_dedup_benchmark_500_roles(self):
        """Deduplicating 500 multi-location postings of the same job (Speechify scenario) completes in < 25ms."""
        cities = [f"City_{i}" for i in range(500)]
        jobs = [
            {
                "title": "Software Engineer, AI Data",
                "company_name": "Speechify",
                "location": f"Remote - {city}",
                "link": f"https://speechify.com/job/{i}",
                "content": "Work on bleeding edge generative AI models and data pipelines across locations."
            }
            for i, city in enumerate(cities)
        ]

        start = time.perf_counter()
        deduped = deduplicate_and_consolidate_roles(self.cfg, jobs)
        elapsed_ms = (time.perf_counter() - start) * 1000

        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["locations_count"], 500)
        self.assertEqual(len(deduped[0]["other_locations"]), 499)
        self.assertLess(elapsed_ms, 25.0, f"Deduplication took {elapsed_ms:.2f}ms (threshold: 25ms)")

    def test_pre_filter_benchmark_1000_jobs(self):
        """Pre-filtering 1000 mixed jobs (seniors, non-tech, juniors) completes in < 50ms."""
        jobs = []
        for i in range(1000):
            if i % 3 == 0:
                jobs.append({"title": f"Senior Principal Engineer {i}", "location": "Bengaluru"})
            elif i % 3 == 1:
                jobs.append({"title": f"Sales Account Executive {i}", "location": "Bengaluru"})
            else:
                jobs.append({"title": f"Junior Software Engineer {i}", "location": "Bengaluru"})

        start = time.perf_counter()
        filtered = pre_filter_jobs(self.cfg, jobs)
        elapsed_ms = (time.perf_counter() - start) * 1000

        self.assertLess(elapsed_ms, 50.0, f"Pre-filter took {elapsed_ms:.2f}ms (threshold: 50ms)")
        # All seniors and sales roles filtered out
        for f in filtered:
            self.assertIn("junior", f["title"].lower())

    def test_make_job_id_throughput(self):
        """Computing 5,000 job IDs takes < 30ms."""
        start = time.perf_counter()
        for i in range(5000):
            make_job_id("Google", f"Software Engineer {i}", f"https://careers.google.com/jobs/{i}")
        elapsed_ms = (time.perf_counter() - start) * 1000

        self.assertLess(elapsed_ms, 30.0, f"Hashing 5000 job IDs took {elapsed_ms:.2f}ms")

    def test_html_cleaner_throughput(self):
        """Cleaning 100 complex HTML documents takes < 25ms."""
        html_doc = """
        <div>
            <h2>Role Overview</h2>
            <p>We are seeking high-caliber engineers &amp; architects.</p>
            <script>window.dataLayer = [];</script>
            <style>.main { margin: 0; }</style>
            <ul>
                <li>Write clean code</li>
                <li>Deploy microservices</li>
            </ul>
        </div>
        """
        start = time.perf_counter()
        for _ in range(100):
            extract_text_from_html(html_doc)
        elapsed_ms = (time.perf_counter() - start) * 1000

        self.assertLess(elapsed_ms, 25.0, f"Cleaning 100 HTML docs took {elapsed_ms:.2f}ms")


if __name__ == "__main__":
    unittest.main()
