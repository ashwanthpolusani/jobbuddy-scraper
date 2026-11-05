"""
tests/test_e2e_pipeline.py - Comprehensive End-to-End Pipeline & Idempotency Test Harness.
Executes Stage 1 -> Stage 2 -> Stage 1 Re-run across an isolated mock MongoDB and HTTP environment.
Validates the complete data lifecycle, atomic upserts, tombstone recording, and CLI flags.
"""
import unittest
from unittest.mock import patch, MagicMock
import mongomock

from scraper.config import DEFAULT_CONFIG, deep_merge
import scraper.db
import stage1
import stage2


class TestEndToEndPipeline(unittest.TestCase):
    def setUp(self):
        # Build isolated in-memory mongomock database
        self.mock_mongo_client = mongomock.MongoClient()
        self.db = self.mock_mongo_client["test_job_aggregator"]
        scraper.db._db = self.db
        scraper.db._client = self.mock_mongo_client

        self.cfg = deep_merge(DEFAULT_CONFIG, {
            "database": {
                "name": "test_job_aggregator",
                "jobs_collection": "jobs",
                "stats_collection": "site_stats",
                "urls_collection": "target_urls",
                "blocked_collection": "blocked_hashes",
                "jobs_ttl_days": 30,
                "stats_ttl_days": 14,
            },
            "runner": {
                "stage1_max_runtime_minutes": 2,
                "stage2_max_runtime_minutes": 2,
                "sleep_between_sites_seconds": 0,
                "sleep_between_stage2_jobs_seconds": 0,
            },
            "_gemini_api_key": "mock-test-key",
            "_mongodb_uri": "mongodb://localhost:27017/test_job_aggregator",
            "_config_source": "in-memory-test",
        })

        # Seed target URLs in MongoDB target_urls
        self.db["target_urls"].insert_many([
            {
                "url": "https://boards-api.greenhouse.io/v1/boards/acme/jobs",
                "company_name": "Acme Corp",
                "ats": "greenhouse",
                "enabled": True,
            },
            {
                "url": "https://api.lever.co/v0/postings/globex",
                "company_name": "Globex",
                "ats": "lever",
                "enabled": True,
            },
        ])

    def tearDown(self):
        scraper.db._db = None
        scraper.db._client = None

    @patch("scraper.ats.greenhouse.fetch_jobs")
    @patch("scraper.ats.lever.fetch_jobs")
    @patch("stage2.score_job")
    @patch("scraper.jd_fetcher.JDFetcher.fetch")
    def test_full_pipeline_lifecycle_and_idempotency(
        self, mock_jd_fetch, mock_gemini_score, mock_lever_jobs, mock_gh_jobs
    ):
        """
        Validates the entire multi-stage data journey:
        Stage 1 (Scrape & Pre-Filter) -> Stage 2 (Verify & Tombstone) -> Stage 1 Re-run (Idempotency).
        """
        # STEP 1: Upstream ATS mock responses
        # Acme (Greenhouse):
        # 1. Graduate Software Engineer (Bengaluru, India) - Eligible, SAFE
        # 2. Principal Architect SDE-3 (Pune, India) - Excluded by senior filter
        # 3. Junior Test Engineer (Chicago, USA) - Excluded by foreign location filter
        mock_gh_jobs.return_value = [
            {
                "title": "Graduate Software Engineer",
                "location": "Bengaluru, India",
                "link": "https://acme.com/jobs/1",
                "content": "<p>Entry level graduate Python and React software engineer role in Bangalore.</p>",
            },
            {
                "title": "Principal Architect SDE-3",
                "location": "Pune, India",
                "link": "https://acme.com/jobs/2",
                "content": "<p>15+ years experience required.</p>",
            },
            {
                "title": "Junior Test Engineer",
                "location": "Chicago, IL, USA",
                "link": "https://acme.com/jobs/3",
                "content": "<p>Must be US Citizen.</p>",
            },
        ]

        # Globex (Lever):
        # 4. Associate Cloud Engineer (Hyderabad, India) - Eligible, POSSIBLE
        # 5. Software Engineering Intern (Noida, India) - Eligible in Stage 1, but Stage 2 finds hidden YOE -> BLOCKED
        mock_lever_jobs.return_value = [
            {
                "title": "Associate Cloud Engineer",
                "location": "Hyderabad, India",
                "link": "https://globex.com/jobs/4",
                "content": "<p>Entry level cloud role working with AWS and Docker.</p>",
            },
            {
                "title": "Software Engineering Intern",
                "location": "Noida, India",
                "link": "https://globex.com/jobs/5",
                "content": "<p>Internship role for software engineer.</p>",
            },
        ]

        # STEP 2: Execute Stage 1 (Black-Box Ingestion)
        with patch("sys.argv", ["stage1.py"]):
            with patch("stage1.load_config", return_value=self.cfg):
                stage1.main()

        # Assert Stage 1 outputs in MongoDB 'jobs'
        jobs_in_db = list(self.db["jobs"].find())
        # Senior and US-only roles must be filtered out. Only Jobs 1, 4, 5 are kept.
        self.assertEqual(len(jobs_in_db), 3)
        job_titles = {j["title"] for j in jobs_in_db}
        self.assertIn("Graduate Software Engineer", job_titles)
        self.assertIn("Associate Cloud Engineer", job_titles)
        self.assertIn("Software Engineering Intern", job_titles)
        self.assertNotIn("Principal Architect SDE-3", job_titles)
        self.assertNotIn("Junior Test Engineer", job_titles)

        for j in jobs_in_db:
            self.assertFalse(j["stage2_verified"])
            self.assertIn(j["category"], ["software_engineering", "devops_cloud"])
            self.assertIn("scraped_at", j)

        # Assert Stage 1 telemetry in 'site_stats' and 'meta'
        stats = list(self.db["site_stats"].find())
        self.assertEqual(len(stats), 2)
        meta_s1 = self.db["meta"].find_one({"_id": "last_stage1_run"})
        self.assertIsNotNone(meta_s1)
        self.assertEqual(meta_s1["total_jobs_saved"], 3)
        self.assertEqual(meta_s1["urls_processed"], 2)

        # STEP 3: Execute Stage 2 (Deep Verification)
        mock_jd_fetch.side_effect = lambda url: f"Detailed qualifications for {url}"

        def mock_scoring(cfg, jd_text, pool):
            if "jobs/1" in jd_text:
                return {
                    "experience_verdict": "SAFE",
                    "verdict_reason": "0-1 years YOE verified",
                    "core_requirements": "Python, React, SQL",
                }
            elif "jobs/4" in jd_text:
                return {
                    "experience_verdict": "POSSIBLE",
                    "verdict_reason": "Entry-level cloud infrastructure role",
                    "core_requirements": "AWS, Linux, Docker",
                }
            elif "jobs/5" in jd_text:
                return {
                    "experience_verdict": "BLOCKED",
                    "verdict_reason": "Hidden requirement: 3+ years YOE required",
                    "core_requirements": "C++, Distributed systems",
                }
            return None

        mock_gemini_score.side_effect = mock_scoring

        with patch("sys.argv", ["stage2.py"]):
            with patch("stage2.load_config", return_value=self.cfg):
                stage2.main()

        # Assert Stage 2 outputs in MongoDB 'jobs'
        remaining_jobs = list(self.db["jobs"].find())
        # Job 5 was BLOCKED -> must be deleted from 'jobs'
        self.assertEqual(len(remaining_jobs), 2)
        remaining_titles = {j["title"] for j in remaining_jobs}
        self.assertIn("Graduate Software Engineer", remaining_titles)
        self.assertIn("Associate Cloud Engineer", remaining_titles)
        self.assertNotIn("Software Engineering Intern", remaining_titles)

        # Assert Stage 2 verified flags
        for j in remaining_jobs:
            self.assertTrue(j["stage2_verified"])
            self.assertIn(j["experience_verdict"], ["SAFE", "POSSIBLE"])
            self.assertIn("stage2_verified_at", j)

        # Assert Tombstone recorded in 'blocked_hashes' for Job 5
        tombstones = list(self.db["blocked_hashes"].find())
        self.assertEqual(len(tombstones), 1)
        self.assertIn("jobs/5", tombstones[0]["link"])
        self.assertIn("BLOCKED", tombstones[0]["reason"])

        # Assert Stage 2 telemetry in 'meta'
        meta_s2 = self.db["meta"].find_one({"_id": "last_stage2_run"})
        self.assertIsNotNone(meta_s2)
        self.assertEqual(meta_s2["verified"], 2)
        self.assertEqual(meta_s2["blocked"], 1)

        # STEP 4: Idempotency & Batch Tombstone Re-Run
        # Re-run Stage 1. Globex still returns Job 5 on its career feed.
        # Stage 1 MUST query blocked_hashes in 1 batch, detect Job 5, and omit it!
        # Jobs 1 and 4 must have scraped_at refreshed, but stage2_verified MUST NOT be overwritten!
        with patch("sys.argv", ["stage1.py"]):
            with patch("stage1.load_config", return_value=self.cfg):
                stage1.main()

        # Assert jobs count remains exactly 2 (Job 5 not resurrected)
        jobs_after_rerun = list(self.db["jobs"].find())
        self.assertEqual(len(jobs_after_rerun), 2)
        for j in jobs_after_rerun:
            self.assertTrue(
                j["stage2_verified"],
                f"Job '{j['title']}' stage2_verified was clobbered by $setOnInsert!",
            )

    @patch("scraper.ats.greenhouse.fetch_jobs")
    def test_stage1_cli_limit_argument(self, mock_gh_jobs):
        """Verify --limit flag restricts number of processed sites in Stage 1."""
        mock_gh_jobs.return_value = [
            {"title": "Software Engineer", "location": "Bengaluru", "link": "https://acme.com/jobs/99", "content": "dev"}
        ]
        with patch("sys.argv", ["stage1.py", "--limit", "1"]):
            with patch("stage1.load_config", return_value=self.cfg):
                stage1.main()

        meta = self.db["meta"].find_one({"_id": "last_stage1_run"})
        self.assertEqual(meta["urls_processed"], 1)

    @patch("scraper.jd_fetcher.JDFetcher.fetch")
    @patch("stage2.score_job")
    def test_stage2_cli_limit_argument(self, mock_score, mock_fetch):
        """Verify --limit flag restricts number of jobs verified in Stage 2 batch."""
        # Insert 3 pending jobs
        for i in range(3):
            self.db["jobs"].insert_one({
                "job_id": f"jid_{i}",
                "title": f"Junior Engineer {i}",
                "company_name": "Acme",
                "location": "Bengaluru",
                "link": f"https://acme.com/job/{i}",
                "link_type": "direct_apply",
                "scraped_at": stage2.now_utc(),
            })

        mock_fetch.return_value = "JD text"
        mock_score.return_value = {"experience_verdict": "SAFE", "verdict_reason": "Verified"}

        with patch("sys.argv", ["stage2.py", "--limit", "1"]):
            with patch("stage2.load_config", return_value=self.cfg):
                stage2.main()

        meta = self.db["meta"].find_one({"_id": "last_stage2_run"})
        self.assertEqual(meta["jobs_processed"], 1)
        self.assertEqual(meta["remaining_pending"], 2)


if __name__ == "__main__":
    unittest.main()

