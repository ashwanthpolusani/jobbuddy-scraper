"""
tests/test_ats_adapters.py - Unit and modular tests for all 9 ATS adapters:
- Greenhouse
- Lever
- Ashby
- Workable
- SmartRecruiters
- Workday
- Eightfold
- Uber
- MyNextHire
Covers standard extraction, pagination loops, HTTP errors (404, 429, 500),
missing fields, malformed JSON, and registry dispatch without hitting live networks.
"""
import io
import json
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError

from scraper.ats import (
    greenhouse,
    lever,
    ashby,
    workable,
    smartrecruiters,
    workday,
    eightfold,
    uber,
    mynexthire,
    process_url,
    registry,
)


def _mock_http_response(payload, status: int = 200):
    """Creates a mock response for urllib.request.urlopen context manager."""
    mock_resp = MagicMock()
    mock_resp.status = status
    if isinstance(payload, (dict, list)):
        raw_bytes = json.dumps(payload).encode("utf-8")
    elif isinstance(payload, str):
        raw_bytes = payload.encode("utf-8")
    else:
        raw_bytes = payload
    mock_resp.read.return_value = raw_bytes
    mock_resp.__enter__.return_value = mock_resp
    return mock_resp


def _make_http_error(url: str = "https://example.com", code: int = 404, msg: str = "Error"):
    """Creates an HTTPError instance with an in-memory buffer."""
    return HTTPError(url, code, msg, {}, io.BytesIO(b""))


class TestGreenhouseAdapter(unittest.TestCase):
    """Unit tests for Greenhouse ATS parser and error handling."""

    def test_greenhouse_standard_fetch_success(self):
        payload = {
            "jobs": [
                {
                    "title": "Software Engineer, Backend",
                    "location": {"name": "Bengaluru, India"},
                    "absolute_url": "https://boards.greenhouse.io/stripe/jobs/101",
                    "content": "<p>Python and Go developer needed.</p>",
                },
                {
                    "title": "Frontend Engineer",
                    "location": {"name": "Remote"},
                    "absolute_url": "https://boards.greenhouse.io/stripe/jobs/102",
                    "content": "<p>React and TypeScript.</p>",
                },
            ]
        }
        with patch("urllib.request.urlopen", return_value=_mock_http_response(payload)):
            jobs = greenhouse.fetch_jobs("stripe")
            self.assertIsNotNone(jobs)
            self.assertEqual(len(jobs), 2)
            self.assertEqual(jobs[0]["title"], "Software Engineer, Backend")
            self.assertEqual(jobs[0]["location"], "Bengaluru, India")
            self.assertEqual(jobs[0]["link"], "https://boards.greenhouse.io/stripe/jobs/101")
            self.assertIn("Python and Go", jobs[0]["content"])

    def test_greenhouse_eu_fallback_on_404(self):
        """Standard endpoint 404 should seamlessly fall back to EU endpoint."""
        eu_payload = {
            "jobs": [
                {
                    "title": "Full Stack Engineer",
                    "location": {"name": "Amsterdam, Netherlands"},
                    "absolute_url": "https://boards.eu.greenhouse.io/miro/jobs/201",
                    "content": "Node.js developer.",
                }
            ]
        }
        # First call raises 404, second call succeeds
        side_effects = [
            _make_http_error(code=404, msg="Not Found"),
            _mock_http_response(eu_payload),
        ]
        with patch("urllib.request.urlopen", side_effect=side_effects):
            jobs = greenhouse.fetch_jobs("miro")
            self.assertIsNotNone(jobs)
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["title"], "Full Stack Engineer")
            self.assertEqual(jobs[0]["location"], "Amsterdam, Netherlands")

    def test_greenhouse_both_endpoints_404_returns_none(self):
        side_effects = [
            _make_http_error(code=404, msg="Not Found"),
            _make_http_error(code=404, msg="Not Found"),
        ]
        with patch("urllib.request.urlopen", side_effect=side_effects):
            jobs = greenhouse.fetch_jobs("nonexistent_company")
            self.assertIsNone(jobs)

    def test_greenhouse_http_429_returns_none(self):
        with patch("urllib.request.urlopen", side_effect=_make_http_error(code=429, msg="Too Many Requests")):
            jobs = greenhouse.fetch_jobs("ratelimited_company")
            self.assertIsNone(jobs)

    def test_greenhouse_missing_fields_and_null_location(self):
        payload = {
            "jobs": [
                {
                    "title": "Data Analyst",
                    "location": None,
                    "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
                    # content missing
                }
            ]
        }
        with patch("urllib.request.urlopen", return_value=_mock_http_response(payload)):
            jobs = greenhouse.fetch_jobs("acme")
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["location"], "")
            self.assertEqual(jobs[0]["content"], "")

    def test_greenhouse_malformed_json_returns_empty_list(self):
        with patch("urllib.request.urlopen", return_value=_mock_http_response("Not a JSON document")):
            jobs = greenhouse.fetch_jobs("corrupt")
            self.assertEqual(jobs, [])

    def test_greenhouse_process_valid_url(self):
        payload = {"jobs": [{"title": "DevOps Engineer", "location": {"name": "Pune"}, "absolute_url": "https://link"}]}
        with patch("urllib.request.urlopen", return_value=_mock_http_response(payload)):
            ok, jobs, ats = greenhouse.process("https://boards.greenhouse.io/figma")
            self.assertTrue(ok)
            self.assertEqual(ats, "Greenhouse")
            self.assertEqual(len(jobs), 1)


class TestLeverAdapter(unittest.TestCase):
    """Unit tests for Lever ATS parser."""

    def test_lever_standard_fetch_success(self):
        payload = [
            {
                "text": "Machine Learning Engineer",
                "categories": {"location": "San Francisco, CA"},
                "hostedUrl": "https://jobs.lever.co/openai/ml-101",
                "descriptionPlain": "Develop neural network training pipelines.",
            },
            {
                "text": "Platform Engineer",
                "categories": {"location": "Bengaluru, India"},
                "hostedUrl": "https://jobs.lever.co/openai/plat-102",
                "descriptionPlain": "Kubernetes and Go.",
            },
        ]
        with patch("urllib.request.urlopen", return_value=_mock_http_response(payload)):
            jobs = lever.fetch_jobs("openai")
            self.assertIsNotNone(jobs)
            self.assertEqual(len(jobs), 2)
            self.assertEqual(jobs[0]["title"], "Machine Learning Engineer")
            self.assertEqual(jobs[0]["location"], "San Francisco, CA")
            self.assertEqual(jobs[0]["link"], "https://jobs.lever.co/openai/ml-101")
            self.assertEqual(jobs[0]["content"], "Develop neural network training pipelines.")

    def test_lever_missing_categories_or_none(self):
        payload = [
            {
                "text": "Security Specialist",
                "categories": None,
                "hostedUrl": "https://jobs.lever.co/test/sec-1",
            }
        ]
        with patch("urllib.request.urlopen", return_value=_mock_http_response(payload)):
            jobs = lever.fetch_jobs("test")
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["location"], "")
            self.assertEqual(jobs[0]["content"], "")

    def test_lever_network_exception_returns_empty_list(self):
        with patch("urllib.request.urlopen", side_effect=URLError("Connection refused")):
            jobs = lever.fetch_jobs("fail_company")
            self.assertEqual(jobs, [])

    def test_lever_process_routing(self):
        payload = [{"text": "SRE", "categories": {"location": "Remote"}, "hostedUrl": "https://lever.co/job"}]
        with patch("urllib.request.urlopen", return_value=_mock_http_response(payload)):
            ok, jobs, ats = lever.process("https://jobs.lever.co/palantir")
            self.assertTrue(ok)
            self.assertEqual(ats, "Lever")
            self.assertEqual(len(jobs), 1)


class TestAshbyAdapter(unittest.TestCase):
    """Unit tests for Ashby ATS parser."""

    def test_ashby_fetch_and_remote_formatting(self):
        payload = {
            "jobs": [
                {
                    "title": "Founding Engineer",
                    "location": "New York, NY",
                    "isRemote": True,
                    "jobUrl": "https://jobs.ashbyhq.com/ramp/job-1",
                    "descriptionPlain": "Full stack architecture.",
                },
                {
                    "title": "Product Designer",
                    "location": "Remote, Global",
                    "isRemote": True,
                    "jobUrl": "https://jobs.ashbyhq.com/ramp/job-2",
                    "descriptionPlain": "Figma design systems.",
                },
                {
                    "title": "Onsite Specialist",
                    "location": "Austin, TX",
                    "isRemote": False,
                    "jobUrl": "https://jobs.ashbyhq.com/ramp/job-3",
                    "descriptionPlain": "Hardware setup.",
                },
            ]
        }
        with patch("urllib.request.urlopen", return_value=_mock_http_response(payload)):
            jobs = ashby.fetch_jobs("ramp")
            self.assertIsNotNone(jobs)
            self.assertEqual(len(jobs), 3)
            # Appends (Remote) when "remote" not in location
            self.assertEqual(jobs[0]["location"], "New York, NY (Remote)")
            # Does not double-append (Remote) when already present
            self.assertEqual(jobs[1]["location"], "Remote, Global")
            # Keeps onsite location as-is
            self.assertEqual(jobs[2]["location"], "Austin, TX")

    def test_ashby_http_error_returns_none(self):
        with patch("urllib.request.urlopen", side_effect=_make_http_error(code=404, msg="Not Found")):
            jobs = ashby.fetch_jobs("unknown")
            self.assertIsNone(jobs)

    def test_ashby_missing_fields_fallback(self):
        payload = {"jobs": [{}]}
        with patch("urllib.request.urlopen", return_value=_mock_http_response(payload)):
            jobs = ashby.fetch_jobs("test")
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["title"], "Unknown Title")
            self.assertEqual(jobs[0]["location"], "Unknown Location")


class TestWorkableAdapter(unittest.TestCase):
    """Unit tests for Workable ATS parser."""

    def test_workable_fetch_success(self):
        payload = {
            "jobs": [
                {
                    "title": "Senior React Developer",
                    "city": "Bengaluru",
                    "country": "India",
                    "shortcode": "REACT101",
                },
                {
                    "title": "QA Automation Engineer",
                    "city": "",
                    "country": "Germany",
                    "shortcode": "QA202",
                },
            ]
        }
        with patch("urllib.request.urlopen", return_value=_mock_http_response(payload)):
            jobs = workable.fetch_jobs("invideo")
            self.assertIsNotNone(jobs)
            self.assertEqual(len(jobs), 2)
            self.assertEqual(jobs[0]["title"], "Senior React Developer")
            self.assertEqual(jobs[0]["location"], "Bengaluru, India")
            self.assertEqual(jobs[0]["link"], "https://apply.workable.com/invideo/j/REACT101")
            self.assertEqual(jobs[1]["location"], "Germany")

    def test_workable_exception_returns_none(self):
        with patch("urllib.request.urlopen", side_effect=Exception("Timeout")):
            jobs = workable.fetch_jobs("error_slug")
            self.assertIsNone(jobs)

    def test_workable_process_routing(self):
        payload = {"jobs": [{"title": "Analyst", "city": "Pune", "country": "India", "shortcode": "ABC"}]}
        with patch("urllib.request.urlopen", return_value=_mock_http_response(payload)):
            ok, jobs, ats = workable.process("https://apply.workable.com/acme/")
            self.assertTrue(ok)
            self.assertEqual(ats, "Workable")
            self.assertEqual(len(jobs), 1)


class TestSmartRecruitersAdapter(unittest.TestCase):
    """Unit tests for SmartRecruiters ATS parser including multi-page pagination."""

    def test_smartrecruiters_single_page(self):
        payload = {
            "content": [
                {
                    "name": "Backend Engineer",
                    "location": {"city": "Berlin", "country": "de"},
                    "id": "JOB100",
                }
            ],
            "totalFound": 1,
        }
        with patch("urllib.request.urlopen", return_value=_mock_http_response(payload)):
            jobs = smartrecruiters.fetch_jobs("Square")
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["title"], "Backend Engineer")
            self.assertEqual(jobs[0]["location"], "Berlin, de")
            self.assertEqual(jobs[0]["link"], "https://jobs.smartrecruiters.com/Square/JOB100")

    def test_smartrecruiters_pagination_loop(self):
        """Simulate two pages where limit=100 and totalFound=150."""
        page1 = {
            "content": [{"name": f"Job {i}", "location": {"city": "City"}, "id": str(i)} for i in range(100)],
            "totalFound": 150,
        }
        page2 = {
            "content": [{"name": f"Job {i}", "location": {"city": "City"}, "id": str(i)} for i in range(100, 150)],
            "totalFound": 150,
        }
        with patch("urllib.request.urlopen", side_effect=[_mock_http_response(page1), _mock_http_response(page2)]):
            jobs = smartrecruiters.fetch_jobs("Visa")
            self.assertEqual(len(jobs), 150)
            self.assertEqual(jobs[0]["title"], "Job 0")
            self.assertEqual(jobs[149]["title"], "Job 149")

    def test_smartrecruiters_empty_content_breaks_loop(self):
        payload = {"content": [], "totalFound": 50}
        with patch("urllib.request.urlopen", return_value=_mock_http_response(payload)):
            jobs = smartrecruiters.fetch_jobs("EmptyCo")
            self.assertEqual(jobs, [])

    def test_smartrecruiters_link_fallback_to_ref(self):
        payload = {
            "content": [
                {
                    "name": "Consultant",
                    "location": {"city": "Mumbai"},
                    "id": "",
                    "ref": "https://custom.link/ref123",
                }
            ],
            "totalFound": 1,
        }
        with patch("urllib.request.urlopen", return_value=_mock_http_response(payload)):
            jobs = smartrecruiters.fetch_jobs("TestCo")
            self.assertEqual(jobs[0]["link"], "https://custom.link/ref123")


class TestWorkdayAdapter(unittest.TestCase):
    """Unit tests for Workday ATS parser with POST JSON pagination."""

    def test_workday_fetch_success_and_pagination(self):
        url = "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite"
        page1 = {
            "jobPostings": [
                {
                    "title": "Deep Learning Architect",
                    "locationsText": "Santa Clara, CA",
                    "externalPath": "/job/1001",
                }
            ],
            "total": 2,
        }
        page2 = {
            "jobPostings": [
                {
                    "title": "CUDA Core Engineer",
                    "locationsText": "Pune, India",
                    "externalPath": "/job/1002",
                }
            ],
            "total": 2,
        }
        with patch("urllib.request.urlopen", side_effect=[_mock_http_response(page1), _mock_http_response(page2)]):
            jobs = workday.fetch_jobs(url)
            self.assertEqual(len(jobs), 2)
            self.assertEqual(jobs[0]["title"], "Deep Learning Architect")
            self.assertEqual(jobs[0]["location"], "Santa Clara, CA")
            self.assertIn("NVIDIAExternalCareerSite/job/1001", jobs[0]["link"])
            self.assertEqual(jobs[1]["title"], "CUDA Core Engineer")
            self.assertEqual(jobs[1]["location"], "Pune, India")

    def test_workday_invalid_url_returns_empty(self):
        self.assertEqual(workday.fetch_jobs("https://nvidia.wd5.myworkdayjobs.com/en-US/login"), [])

    def test_workday_empty_postings_breaks_loop(self):
        url = "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite"
        payload = {"jobPostings": [], "total": 0}
        with patch("urllib.request.urlopen", return_value=_mock_http_response(payload)):
            jobs = workday.fetch_jobs(url)
            self.assertEqual(jobs, [])


class TestEightfoldAdapter(unittest.TestCase):
    """Unit tests for Eightfold ATS parser."""

    def test_eightfold_fetch_and_pagination(self):
        url = "https://micron.eightfold.ai/careers"
        # Eightfold uses num=10 per page by default
        page1 = {
            "positions": [
                {
                    "name": f"Silicon Design Engineer {i}",
                    "location": "Hyderabad, India",
                    "canonicalPositionUrl": f"https://micron.eightfold.ai/careers/job/{i}",
                }
                for i in range(10)
            ],
            "count": 12,
        }
        page2 = {
            "positions": [
                {
                    "name": f"Firmware Engineer {i}",
                    "location": "Bengaluru, India",
                    "canonicalPositionUrl": f"https://micron.eightfold.ai/careers/job/{i}",
                }
                for i in range(10, 12)
            ],
            "count": 12,
        }
        # Patch sleep so tests run instantly
        with patch("urllib.request.urlopen", side_effect=[_mock_http_response(page1), _mock_http_response(page2)]), \
             patch("time.sleep"):
            jobs = eightfold.fetch_jobs(url)
            self.assertEqual(len(jobs), 12)
            self.assertEqual(jobs[0]["title"], "Silicon Design Engineer 0")
            self.assertEqual(jobs[0]["location"], "Hyderabad, India")
            self.assertEqual(jobs[11]["title"], "Firmware Engineer 11")
            self.assertEqual(jobs[11]["location"], "Bengaluru, India")

    def test_eightfold_empty_positions_breaks(self):
        with patch("urllib.request.urlopen", return_value=_mock_http_response({"positions": [], "count": 0})):
            jobs = eightfold.fetch_jobs("https://test.eightfold.ai/careers")
            self.assertEqual(jobs, [])


class TestUberAdapter(unittest.TestCase):
    """Unit tests for Uber ATS parser."""

    def test_uber_fetch_and_location_flattening(self):
        payload = {
            "jobs": [
                {
                    "Id": 12345,
                    "Title": "Software Engineer II - Maps",
                    "Locations": [{"City": "Bengaluru", "Country": "India"}],
                    "Urls": [{"Url": "/en/jobs/12345/"}],
                    "Description": "Uber Maps routing engine.",
                }
            ],
            "totalPages": 1,
        }
        with patch("urllib.request.urlopen", return_value=_mock_http_response(payload)):
            jobs = uber.fetch_jobs("location=Bengaluru")
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["title"], "Software Engineer II - Maps")
            self.assertEqual(jobs[0]["location"], "Bengaluru, India")
            self.assertEqual(jobs[0]["link"], "https://jobs.uber.com/en/jobs/12345/")
            self.assertEqual(jobs[0]["id"], "12345")

    def test_uber_process_dual_hub_deduplication(self):
        """Test process('https://www.uber.com') fetching Bengaluru and Hyderabad with dedup."""
        job_blr = {"id": "1", "title": "SWE", "link": "https://jobs.uber.com/1"}
        job_hyd = {"id": "2", "title": "Data Analyst", "link": "https://jobs.uber.com/2"}
        duplicate_job = {"id": "1", "title": "SWE", "link": "https://jobs.uber.com/1"}

        with patch("scraper.ats.uber.fetch_jobs", side_effect=[[job_blr, duplicate_job], [job_hyd]]):
            ok, combined, ats = uber.process("https://uber.com")
            self.assertTrue(ok)
            self.assertEqual(ats, "Uber")
            # Duplicate job with id "1" must be filtered out
            self.assertEqual(len(combined), 2)
            ids = [j["id"] for j in combined]
            self.assertIn("1", ids)
            self.assertIn("2", ids)


class TestMyNextHireAdapter(unittest.TestCase):
    """Unit tests for MyNextHire ATS parser."""

    def test_mynexthire_fetch_success(self):
        payload = {
            "reqDetailsBOList": [
                {
                    "reqTitle": "Associate Product Manager",
                    "location": "Bengaluru",
                    "reqId": 9988,
                },
                {
                    "reqTitle": "SDE 1 - Backend",
                    "location": "Gurugram",
                    "reqId": 9989,
                },
            ]
        }
        with patch("urllib.request.urlopen", return_value=_mock_http_response(payload)):
            jobs = mynexthire.fetch_jobs("swiggy.mynexthire.com")
            self.assertEqual(len(jobs), 2)
            self.assertEqual(jobs[0]["title"], "Associate Product Manager")
            self.assertEqual(jobs[0]["location"], "Bengaluru")
            self.assertEqual(jobs[0]["link"], "https://swiggy.mynexthire.com/employer/jobs/careers?category=9988")

    def test_mynexthire_exception_returns_empty(self):
        with patch("urllib.request.urlopen", side_effect=Exception("Server Down")):
            jobs = mynexthire.fetch_jobs("test.mynexthire.com")
            self.assertEqual(jobs, [])

    def test_mynexthire_process_routing(self):
        payload = {"reqDetailsBOList": [{"reqTitle": "Dev", "location": "Pune", "reqId": 1}]}
        with patch("urllib.request.urlopen", return_value=_mock_http_response(payload)):
            ok, jobs, ats = mynexthire.process("https://swiggy.mynexthire.com/careers")
            self.assertTrue(ok)
            self.assertEqual(ats, "MyNextHire")
            self.assertEqual(len(jobs), 1)


class TestATSRegistryIntegration(unittest.TestCase):
    """Verify registry routing and dispatch across all 9 adapters."""

    def test_all_registered_adapters(self):
        test_urls = [
            ("https://boards.greenhouse.io/stripe", "Greenhouse"),
            ("https://jobs.lever.co/netflix", "Lever"),
            ("https://jobs.ashbyhq.com/retool", "Ashby"),
            ("https://careers.smartrecruiters.com/Square", "SmartRecruiters"),
            ("https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite", "Workday"),
            ("https://apply.workable.com/invideo/", "Workable"),
            ("https://micron.eightfold.ai/careers", "Eightfold"),
            ("https://jobs.uber.com/en/jobs/", "Uber"),
            ("https://swiggy.mynexthire.com/careers", "MyNextHire"),
        ]
        for url, expected_name in test_urls:
            with self.subTest(url=url, expected=expected_name):
                adapter = registry.find_adapter(url)
                self.assertIsNotNone(adapter, f"Adapter not found for {url}")
                self.assertEqual(adapter.name, expected_name)


if __name__ == "__main__":
    unittest.main()
