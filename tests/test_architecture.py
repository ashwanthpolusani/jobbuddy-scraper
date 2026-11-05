"""
tests/test_architecture.py - Unit tests for core scraper architecture components:
- Standardized ATS Adapters and ATSRegistry
- HTML text cleaner and smart bullet extractor
- Community presets validation
"""
import unittest
from pathlib import Path
from scraper.ats.base import RawJob, BaseATSAdapter, ATSRegistry
from scraper.jd_fetcher import extract_text_from_html, extract_core_requirements
from scraper.config import load_config


class DummyAdapter(BaseATSAdapter):
    name = "DummyATS"

    def can_handle(self, url: str) -> bool:
        return "dummy-ats.com" in url

    def fetch_jobs(self, url: str, company_name: str = ""):
        return [{"title": "Software Engineer", "link": url}]


class TestUniversalArchitecture(unittest.TestCase):

    def test_raw_job_to_dict(self):
        job = RawJob(
            title="Frontend Engineer",
            company_name="Acme Corp",
            location="Remote",
            link="https://acme.com/jobs/1",
            content="<p>React and TypeScript developer needed.</p>",
            category="software_engineering",
            experience_verdict="SAFE"
        )
        d = job.to_dict()
        self.assertEqual(d["title"], "Frontend Engineer")
        self.assertEqual(d["company_name"], "Acme Corp")
        self.assertEqual(d["experience_verdict"], "SAFE")
        self.assertNotIn("metadata", d)

    def test_ats_registry(self):
        reg = ATSRegistry()
        dummy = DummyAdapter()
        reg.register(dummy)

        self.assertIs(reg.find_adapter("https://dummy-ats.com/careers"), dummy)
        self.assertIsNone(reg.find_adapter("https://unknown.com"))

        is_supp, jobs, name = reg.process_url("https://dummy-ats.com/careers")
        self.assertTrue(is_supp)
        self.assertEqual(name, "DummyATS")
        self.assertEqual(len(jobs), 1)

    def test_html_unescaping_and_bullet_extractor(self):
        raw_html = (
            '&lt;div class=&quot;content-intro&quot;&gt;&lt;img src=&quot;tracker.png&quot;&gt;&lt;/div&gt;'
            '&lt;h2&gt;Who we are&lt;/h2&gt;&lt;p&gt;We are an innovative cloud company.&lt;/p&gt;'
            '&lt;h2&gt;Requirements&lt;/h2&gt;'
            '&lt;ul&gt;'
            '&lt;li&gt;Strong proficiency in Python and Django&lt;/li&gt;'
            '&lt;li&gt;Familiarity with PostgreSQL and Redis&lt;/li&gt;'
            '&lt;li&gt;Experience with Docker &amp; Kubernetes&lt;/li&gt;'
            '&lt;/ul&gt;'
        )
        clean = extract_core_requirements(raw_html, title="Backend Engineer")
        self.assertNotIn("&lt;", clean)
        self.assertNotIn("<div", clean)
        self.assertNotIn("content-intro", clean)
        self.assertIn("Python and Django", clean)
        self.assertIn("PostgreSQL", clean)

    def test_all_presets_valid(self):
        presets_dir = Path(__file__).resolve().parent.parent / "presets"
        preset_files = list(presets_dir.glob("*.json"))
        self.assertGreaterEqual(len(preset_files), 4)

        for p in preset_files:
            cfg = load_config(preset=p.stem, require_db=False, require_gemini=False)
            self.assertIn("locations", cfg)
            self.assertIn("experience", cfg)
            self.assertIn("skills", cfg)
            self.assertIn("categories", cfg)


if __name__ == "__main__":
    unittest.main()
