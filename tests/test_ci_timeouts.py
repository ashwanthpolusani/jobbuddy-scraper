"""
tests/test_ci_timeouts.py - Verification of Max Runtime Fail-Safes and Matrix Sharding.
Ensures Stage 1 and Stage 2 break gracefully before GitHub Actions timeout ceilings (35m / 135m),
flush all in-flight state to MongoDB, and exit cleanly with Exit Code 0.
"""
import time
import unittest
from unittest.mock import MagicMock, patch
import mongomock

from scraper.config import DEFAULT_CONFIG, deep_merge
import scraper.db
from scraper.db import get_target_urls
import stage1
import stage2


class TestCITimeoutFailSafe(unittest.TestCase):
    def setUp(self):
        self.mock_mongo_client = mongomock.MongoClient()
        self.db = self.mock_mongo_client["test_timeouts"]
        scraper.db._db = self.db
        scraper.db._client = self.mock_mongo_client

        self.cfg = deep_merge(DEFAULT_CONFIG, {
            "database": {
                "name": "test_timeouts",
                "jobs_collection": "jobs",
                "stats_collection": "site_stats",
                "urls_collection": "target_urls",
                "blocked_collection": "blocked_hashes",
            },
            "runner": {
                # Configure ultra-low runtime threshold: 0.001 minutes = 0.06 seconds
                "stage1_max_runtime_minutes": 0.001,
                "stage2_max_runtime_minutes": 0.001,
                "sleep_between_sites_seconds": 0,
                "sleep_between_stage2_jobs_seconds": 0,
            },
            "_gemini_api_key": "test-key",
            "_mongodb_uri": "mongodb://localhost:27017/test_timeouts",
            "_config_source": "in-memory-test",
        })

    def tearDown(self):
        scraper.db._db = None
        scraper.db._client = None

    @patch("stage1.ats_process_url")
    def test_stage1_runtime_failsafe_graceful_shutdown(self, mock_ats_process):
        """
        Stage 1 must detect elapsed time > max_runtime, break loop gracefully,
        flush processed jobs, write stop_reason to meta, and return with exit code 0.
        """
        # Seed 20 target URLs in MongoDB
        urls = [
            {"url": f"https://jobs.example.com/{i}", "company_name": f"Company {i}", "enabled": True}
            for i in range(20)
        ]
        self.db["target_urls"].insert_many(urls)

        # Simulate 40ms processing time per site so max_runtime (60ms) triggers after 2-3 sites
        def slow_ats_process(url, company_name=""):
            time.sleep(0.04)
            return True, [
                {
                    "title": "Junior Python Engineer",
                    "location": "Bengaluru",
                    "link": f"{url}/job1",
                    "content": "Entry level software engineering role.",
                }
            ], "MockATS"

        mock_ats_process.side_effect = slow_ats_process

        with patch("sys.argv", ["stage1.py"]):
            with patch("stage1.load_config", return_value=self.cfg):
                # Must terminate cleanly without hanging or raising unhandled exceptions
                stage1.main()

        # Verify stop reason and telemetry in MongoDB meta collection
        meta = self.db["meta"].find_one({"_id": "last_stage1_run"})
        self.assertIsNotNone(meta, "Stage 1 did not record telemetry to meta collection!")
        self.assertIn("Hit stage1 max runtime limit", meta["stop_reason"])
        self.assertLess(meta["urls_processed"], 20, "Runner should have broken early due to timeout limit")
        self.assertGreater(meta["total_jobs_saved"], 0, "Jobs processed before timeout must be saved to DB")

    @patch("stage2.score_job")
    @patch("scraper.jd_fetcher.JDFetcher.fetch")
    def test_stage2_runtime_failsafe_graceful_shutdown(self, mock_fetch, mock_score):
        """
        Stage 2 must detect elapsed time > max_runtime, break loop gracefully,
        leave remaining pending jobs intact for next run, and record telemetry to meta.
        """
        # Seed 20 pending jobs in MongoDB jobs collection
        jobs = [
            {
                "job_id": f"jid_{i}",
                "title": f"Junior Dev {i}",
                "company_name": "Acme Corp",
                "location": "Bengaluru",
                "link": f"https://acme.com/job/{i}",
                "link_type": "direct_apply",
                "scraped_at": stage2.now_utc(),
            }
            for i in range(20)
        ]
        self.db["jobs"].insert_many(jobs)

        mock_fetch.return_value = "Detailed JD content requirements"

        def slow_score(cfg, text, pool):
            time.sleep(0.04)
            return {"experience_verdict": "SAFE", "verdict_reason": "Entry level verified"}

        mock_score.side_effect = slow_score

        with patch("sys.argv", ["stage2.py"]):
            with patch("stage2.load_config", return_value=self.cfg):
                stage2.main()

        # Verify stop reason and telemetry in MongoDB meta collection
        meta = self.db["meta"].find_one({"_id": "last_stage2_run"})
        self.assertIsNotNone(meta, "Stage 2 did not record telemetry to meta collection!")
        self.assertIn("Hit stage2 max runtime limit", meta["stop_reason"])
        self.assertLess(meta["jobs_processed"], 20, "Stage 2 should have broken early due to timeout limit")
        self.assertGreater(meta["verified"], 0, "Jobs verified before timeout must be persisted")
        self.assertGreater(meta["remaining_pending"], 0, "Unverified jobs must remain pending for next run")

    def test_matrix_sharding_disjointness_and_completeness(self):
        """
        Verifies that matrix chunking via modulo math partitions target URLs
        completely and without duplicate assignments across workers.
        """
        # Seed 25 target URLs (non-multiple of 4 chunks)
        all_urls = [
            {"url": f"https://boards.greenhouse.io/co_{i}", "company_name": f"Co {i}", "enabled": True}
            for i in range(25)
        ]
        self.db["target_urls"].insert_many(all_urls)

        total_chunks = 4
        shards = []
        for chunk_idx in range(total_chunks):
            shard_urls = get_target_urls(self.cfg, chunk_index=chunk_idx, total_chunks=total_chunks)
            shards.append(shard_urls)

        # 1. Completeness: All 25 URLs accounted for
        total_partitioned = sum(len(s) for s in shards)
        self.assertEqual(total_partitioned, 25)

        # 2. Disjointness: No overlap between any two shards
        seen_urls = set()
        for s in shards:
            shard_url_set = {doc["url"] for doc in s}
            self.assertEqual(len(seen_urls.intersection(shard_url_set)), 0)
            seen_urls.update(shard_url_set)

        self.assertEqual(len(seen_urls), 25)


if __name__ == "__main__":
    unittest.main()
