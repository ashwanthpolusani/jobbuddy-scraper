"""
tests/test_db_pipeline.py - Exhaustive Integration & Data Pipeline Test Suite.
Tests atomic upserts, Stage 2 data preservation, blocked_hashes tombstone memory,
BSON Date TTL compliance, multi-location consolidation persistence, and idempotency.
Uses mongomock for hermetic, isolated, sub-millisecond execution.
"""
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
import mongomock

from scraper.config import DEFAULT_CONFIG
import scraper.db as db_mod
from scraper.filters.pre_filter import deduplicate_and_consolidate_roles


class TestDatabasePipelineIntegration(unittest.TestCase):

    def setUp(self):
        """Provision a clean in-memory mongomock database before each test."""
        self.mock_client = mongomock.MongoClient()
        self.mock_db = self.mock_client["jobbuddy_test"]
        self.patcher = patch("scraper.db.get_db", return_value=self.mock_db)
        self.patcher.start()

        # Initialize collections and indexes
        db_mod.create_indexes(DEFAULT_CONFIG)
        self.jobs_col = DEFAULT_CONFIG["database"]["jobs_collection"]
        self.stats_col = DEFAULT_CONFIG["database"]["stats_collection"]
        self.blocked_col = DEFAULT_CONFIG["database"].get("blocked_collection", "blocked_hashes")

    def tearDown(self):
        """Tear down database mock and patcher."""
        self.patcher.stop()

    # -------------------------------------------------------------------------
    # TEST 1: Atomic Upsert & Stage 2 Non-Clobbering ($setOnInsert)
    # -------------------------------------------------------------------------
    def test_upsert_preserves_stage2_verified_data(self):
        """
        CRITICAL TEST: Ensures that recurring Stage 1 scrapes update scraped_at
        but NEVER overwrite Stage 2 verification fields (stage2_verified, experience_verdict).
        """
        job = {
            "title": "Junior Python Developer",
            "company_name": "Acme Corp",
            "link": "https://acme.com/jobs/101",
            "location": "Bengaluru, India",
            "category": "software_engineering",
            "source_url": "https://acme.com/careers",
        }

        # 1. Initial Stage 1 ingestion
        saved = db_mod.upsert_jobs(DEFAULT_CONFIG, [job], ats_name="Greenhouse")
        self.assertEqual(saved, 1)

        doc = self.mock_db[self.jobs_col].find_one({"company_name": "Acme Corp"})
        self.assertIsNotNone(doc)
        self.assertFalse(doc["stage2_verified"])
        self.assertEqual(doc["experience_verdict"], "POSSIBLE")
        initial_first_seen = doc["first_seen"]
        initial_scraped_at = doc["scraped_at"]

        # 2. Stage 2 executes and enriches the job
        self.mock_db[self.jobs_col].update_one(
            {"_id": doc["_id"]},
            {"$set": {
                "stage2_verified": True,
                "experience_verdict": "SAFE",
                "verdict_reason": "Verified < 1 YOE requirement in full JD",
                "stage2_verified_at": db_mod.now_utc(),
                "core_requirements": "Python, Django, PostgreSQL",
            }}
        )

        # 3. Stage 1 executes again on recurring run
        saved_recurring = db_mod.upsert_jobs(DEFAULT_CONFIG, [job], ats_name="Greenhouse")
        self.assertEqual(saved_recurring, 1)

        # 4. Assert protected fields were NOT clobbered
        doc_after = self.mock_db[self.jobs_col].find_one({"_id": doc["_id"]})
        self.assertTrue(doc_after["stage2_verified"], "Stage 2 verified flag was clobbered by Stage 1!")
        self.assertEqual(doc_after["experience_verdict"], "SAFE", "Stage 2 verdict was reset by Stage 1!")
        self.assertEqual(doc_after["verdict_reason"], "Verified < 1 YOE requirement in full JD")
        self.assertEqual(doc_after["core_requirements"], "Python, Django, PostgreSQL")
        self.assertEqual(doc_after["first_seen"], initial_first_seen, "first_seen timestamp should remain immutable!")
        self.assertGreaterEqual(doc_after["scraped_at"], initial_scraped_at, "scraped_at should be refreshed on re-scrape!")

    # -------------------------------------------------------------------------
    # TEST 2: Multi-Location Consolidation Persistence
    # -------------------------------------------------------------------------
    def test_multi_location_consolidation_persists_to_db(self):
        """
        Validates that consolidated multi-location fields (other_locations,
        locations_count, location_summary) are properly persisted into MongoDB.
        """
        shared_jd = "Build high-throughput data processing systems with Python and Redis. Scale to millions." * 3
        raw_postings = [
            {"title": "Data Engineer - Austin, TX (Remote)", "company_name": "Speechify", "location": "Austin, TX (Remote)", "content": shared_jd, "link": "https://speechify.com/1"},
            {"title": "Data Engineer - Bengaluru (Remote)", "company_name": "Speechify", "location": "Bengaluru, India (Remote)", "content": shared_jd, "link": "https://speechify.com/2"},
            {"title": "Data Engineer - London (Remote)", "company_name": "Speechify", "location": "London, UK (Remote)", "content": shared_jd, "link": "https://speechify.com/3"},
        ]

        consolidated = deduplicate_and_consolidate_roles(DEFAULT_CONFIG, raw_postings)
        self.assertEqual(len(consolidated), 1)
        winner = consolidated[0]
        self.assertIn("Bengaluru", winner["location"])
        self.assertEqual(winner["locations_count"], 3)
        self.assertIn("(+2 locations)", winner["location_summary"])

        # Persist to DB
        saved = db_mod.upsert_jobs(DEFAULT_CONFIG, consolidated, ats_name="Greenhouse")
        self.assertEqual(saved, 1)

        doc = self.mock_db[self.jobs_col].find_one({"company_name": "Speechify"})
        self.assertIsNotNone(doc)
        self.assertEqual(doc["location"], winner["location"])
        self.assertEqual(doc["locations_count"], 3)
        self.assertEqual(len(doc["other_locations"]), 2)
        self.assertIn("(+2 locations)", doc["location_summary"])

        # Also test recurring scrape updating multi-location summary
        winner["locations_count"] = 4
        winner["other_locations"].append("Pune, India")
        winner["location_summary"] = "Bengaluru, India (Remote) (+3 locations)"
        db_mod.upsert_jobs(DEFAULT_CONFIG, [winner], ats_name="Greenhouse")

        doc_updated = self.mock_db[self.jobs_col].find_one({"company_name": "Speechify"})
        self.assertEqual(doc_updated["locations_count"], 4)
        self.assertEqual(len(doc_updated["other_locations"]), 3)
        self.assertIn("(+3 locations)", doc_updated["location_summary"])

    # -------------------------------------------------------------------------
    # TEST 3: Blocked Tombstone Memory & Infinite Re-Evaluation Prevention
    # -------------------------------------------------------------------------
    def test_blocked_tombstones_prevent_reingestion(self):
        """
        Verifies that rejected jobs are recorded as tombstones in blocked_hashes
        and skipped during subsequent Stage 1 upserts and batch queries.
        """
        job_id = "test_blocked_hash_001"
        link = "https://acme.com/jobs/senior-lead"

        # Record tombstone
        db_mod.record_blocked_job(DEFAULT_CONFIG, job_id, link, reason="Requires 8+ YOE")

        # 1. Individual lookup
        self.assertTrue(db_mod.is_job_blocked(DEFAULT_CONFIG, job_id, link))
        self.assertTrue(db_mod.is_job_blocked(DEFAULT_CONFIG, job_id, ""))
        self.assertTrue(db_mod.is_job_blocked(DEFAULT_CONFIG, "unrelated_id", link))
        self.assertFalse(db_mod.is_job_blocked(DEFAULT_CONFIG, "clean_id", "https://clean.com"))

        # 2. Batch lookup query (1 network roundtrip)
        pairs = [
            (job_id, link),
            ("clean_id_101", "https://acme.com/jobs/fresher"),
            ("matched_by_link_only", link),
        ]
        blocked_set = db_mod.get_blocked_job_ids(DEFAULT_CONFIG, pairs)
        self.assertIn(job_id, blocked_set)
        self.assertIn("matched_by_link_only", blocked_set)
        self.assertNotIn("clean_id_101", blocked_set)

        # 3. upsert_jobs must skip the blocked job
        blocked_job = {
            "title": "Senior Lead Architect",
            "company_name": "Acme Corp",
            "link": link,
            "location": "Bengaluru, India",
        }
        saved_count = db_mod.upsert_jobs(DEFAULT_CONFIG, [blocked_job])
        self.assertEqual(saved_count, 0, "Blocked job was saved into jobs collection!")
        self.assertEqual(self.mock_db[self.jobs_col].count_documents({"link": link}), 0)

    # -------------------------------------------------------------------------
    # TEST 4: Data Pipeline Idempotency (f(x) == f(f(x)))
    # -------------------------------------------------------------------------
    def test_pipeline_idempotency_multi_run(self):
        """
        Verifies that running the upsert pipeline multiple times over identical
        or overlapping data produces zero duplicate documents and maintains state.
        """
        batch = [
            {"title": f"Software Engineer {i}", "company_name": "TestCorp", "link": f"https://testcorp.com/jobs/{i}"}
            for i in range(10)
        ]

        # First run
        saved_run1 = db_mod.upsert_jobs(DEFAULT_CONFIG, batch)
        self.assertEqual(saved_run1, 10)
        self.assertEqual(self.mock_db[self.jobs_col].count_documents({}), 10)

        # Second run with exact same data
        saved_run2 = db_mod.upsert_jobs(DEFAULT_CONFIG, batch)
        self.assertEqual(saved_run2, 10)
        # Count must remain exactly 10, NOT 20
        self.assertEqual(self.mock_db[self.jobs_col].count_documents({}), 10)

    # -------------------------------------------------------------------------
    # TEST 5: BSON UTC Datetime & TTL Index Compliance
    # -------------------------------------------------------------------------
    def test_bson_datetime_compliance(self):
        """
        MongoDB TTL background worker REQUIRES native BSON Date types.
        Verifies that scraped_at, first_seen, run_date, and blocked_at are
        instances of datetime.datetime and NOT serialized ISO strings.
        """
        # Test now_utc returns timezone-aware UTC datetime
        now = db_mod.now_utc()
        self.assertIsInstance(now, datetime)
        self.assertEqual(now.tzinfo, timezone.utc)

        # Verify upsert stores datetime objects
        job = {"title": "DevOps Engineer", "company_name": "CloudCo", "link": "https://cloud.co/1"}
        db_mod.upsert_jobs(DEFAULT_CONFIG, [job])
        doc = self.mock_db[self.jobs_col].find_one({"company_name": "CloudCo"})

        self.assertIsInstance(doc["scraped_at"], datetime)
        self.assertIsInstance(doc["first_seen"], datetime)
        self.assertNotIsInstance(doc["scraped_at"], str, "scraped_at must be BSON Date, not string!")
        self.assertNotIsInstance(doc["first_seen"], str, "first_seen must be BSON Date, not string!")

        # Verify site_stats stores datetime objects
        db_mod.record_site_stats(DEFAULT_CONFIG, "https://cloud.co", True, 250, [job], None)
        stat = self.mock_db[self.stats_col].find_one({"url": "https://cloud.co"})
        self.assertIsInstance(stat["run_date"], datetime)
        self.assertNotIsInstance(stat["run_date"], str)

        # Verify blocked_hashes stores datetime objects
        db_mod.record_blocked_job(DEFAULT_CONFIG, "hash123", "https://cloud.co/bad", "Invalid")
        blocked = self.mock_db[self.blocked_col].find_one({"_id": "hash123"})
        self.assertIsInstance(blocked["blocked_at"], datetime)
        self.assertNotIsInstance(blocked["blocked_at"], str)

    # -------------------------------------------------------------------------
    # TEST 6: Scraper Metadata Dynamic Profile Writing
    # -------------------------------------------------------------------------
    def test_record_scraper_metadata(self):
        """
        Verifies record_scraper_metadata writes target cities and categories
        to MongoDB meta collection for frontend plug-and-play UI.
        """
        db_mod.record_scraper_metadata(DEFAULT_CONFIG)
        meta = self.mock_db["meta"].find_one({"_id": "active_profile"})
        self.assertIsNotNone(meta)
        self.assertIn("allowed_cities", meta)
        self.assertIn("enabled_categories", meta)
        self.assertIsInstance(meta["updated_at"], datetime)
        self.assertEqual(meta["primary_country"], "India")


if __name__ == "__main__":
    unittest.main()
