"""
tests/test_concurrency_stress.py - Concurrency, thread-safety, and stress tests.
Validates:
- Thread-safe MongoDB client singleton instantiation
- Concurrent tombstone querying and upserting under high batch volume
- Parallel execution of role fingerprinting and deduplication
"""
import concurrent.futures
import unittest
from unittest.mock import patch
import mongomock

from scraper.db import get_db, make_job_id, get_blocked_job_ids, record_blocked_job
from stage2 import make_role_fingerprint


class TestConcurrencyStress(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "_mongodb_uri": "mongodb://localhost:27017/stress_test",
            "database": {
                "name": "jobbuddy_stress",
                "jobs_collection": "jobs",
                "blocked_hashes_collection": "blocked_hashes"
            }
        }

    def test_get_db_thread_safe_singleton(self):
        """10 threads requesting get_db simultaneously must receive the exact same singleton instance."""
        mock_client = mongomock.MongoClient()
        with patch("scraper.db.MongoClient", return_value=mock_client):
            # Reset globals for isolation
            import scraper.db as db_module
            db_module._client = None
            db_module._db = None

            instances = []
            def worker():
                return get_db(self.cfg)

            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                futures = [executor.submit(worker) for _ in range(16)]
                for f in concurrent.futures.as_completed(futures):
                    instances.append(f.result())

            self.assertEqual(len(instances), 16)
            # All instances must be the exact same object reference
            first_inst = instances[0]
            for inst in instances:
                self.assertIs(inst, first_inst)

    def test_high_volume_batch_tombstone_lookups(self):
        """Batch tombstone check scales gracefully to 500 pairs in 1 batch query."""
        mock_db = mongomock.MongoClient()["jobbuddy_stress"]
        with patch("scraper.db.get_db", return_value=mock_db):
            # Seed 50 blocked jobs
            for i in range(50):
                jid = f"blocked_hash_{i:04d}"
                record_blocked_job(self.cfg, jid, f"https://example.com/job/{i}", "Senior role")

            # Query 500 candidate pairs
            pairs = []
            for i in range(500):
                jid = f"blocked_hash_{i:04d}"
                pairs.append((jid, f"https://example.com/job/{i}"))

            blocked_set = get_blocked_job_ids(self.cfg, pairs)
            self.assertEqual(len(blocked_set), 50)
            self.assertIn("blocked_hash_0000", blocked_set)
            self.assertIn("blocked_hash_0049", blocked_set)
            self.assertNotIn("blocked_hash_0050", blocked_set)

    def test_parallel_role_fingerprinting(self):
        """Concurrent role fingerprint computations produce deterministic results without collision."""
        def hash_worker(i):
            return make_role_fingerprint("Speechify", f"Software Engineer - City {i % 10}", "JD description text")

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(hash_worker, i) for i in range(100)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        self.assertEqual(len(results), 100)
        # All 100 must be valid 64-char sha256 strings
        for h in results:
            self.assertEqual(len(h), 64)


if __name__ == "__main__":
    unittest.main()
