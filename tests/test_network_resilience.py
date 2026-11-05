"""
tests/test_network_resilience.py - Chaos Testing for Network Timeouts, HTTP Status Codes & Corrupt Feeds.
Tests that ATS adapters, JD fetchers, and the Gemini ModelPool degrade gracefully under network hostility.
"""
import json
import socket
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from scraper.ats.ashby import fetch_jobs as ashby_fetch_jobs
from scraper.ats.greenhouse import fetch_jobs as gh_fetch_jobs
from scraper.ats.lever import fetch_jobs as lever_fetch_jobs
from scraper.ats.smartrecruiters import fetch_jobs as sr_fetch_jobs
from scraper.ats.workable import fetch_jobs as workable_fetch_jobs
from scraper.ats.workday import fetch_jobs as workday_fetch_jobs
from scraper.gemini import ModelPool
from scraper.jd_fetcher import JDFetcher, _fetch_http


class TestNetworkResilienceChaos(unittest.TestCase):

    # -- 1. Socket Timeouts (Simulating hung servers >10-15s) ------------------

    @patch("urllib.request.urlopen", side_effect=socket.timeout("Connection timed out after 10s"))
    def test_greenhouse_socket_timeout_resilience(self, mock_urlopen):
        """Greenhouse adapter must catch socket timeout and return empty list cleanly."""
        jobs = gh_fetch_jobs("acme")
        self.assertEqual(jobs, [])

    @patch("urllib.request.urlopen", side_effect=socket.timeout("Connection timed out after 12s"))
    def test_lever_socket_timeout_resilience(self, mock_urlopen):
        """Lever adapter must catch socket timeout and return empty list cleanly."""
        jobs = lever_fetch_jobs("globex")
        self.assertEqual(jobs, [])

    @patch("urllib.request.urlopen", side_effect=socket.timeout("Connection timed out after 15s"))
    def test_workday_socket_timeout_resilience(self, mock_urlopen):
        """Workday CXS API must catch socket timeout and return partial jobs without crash."""
        jobs = workday_fetch_jobs("https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite")
        self.assertEqual(jobs, [])

    # -- 2. HTTP Status Code Chaos (404, 429, 500, 503) -----------------------

    @patch("urllib.request.urlopen")
    def test_lever_http_404_not_found(self, mock_urlopen):
        """HTTP 404 indicating inactive career page must return empty list."""
        mock_urlopen.side_effect = HTTPError(
            url="https://api.lever.co/v0/postings/defunct",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=None,
        )
        jobs = lever_fetch_jobs("defunct")
        self.assertEqual(jobs, [])

    @patch("urllib.request.urlopen")
    def test_greenhouse_http_429_rate_limit(self, mock_urlopen):
        """HTTP 429 Too Many Requests must be caught and return None indicating blocked API."""
        mock_urlopen.side_effect = HTTPError(
            url="https://boards-api.greenhouse.io/v1/boards/stripe/jobs",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=None,
        )
        result = gh_fetch_jobs("stripe")
        self.assertIsNone(result)

    @patch("urllib.request.urlopen")
    def test_workday_http_503_service_unavailable(self, mock_urlopen):
        """HTTP 503 Server Error must be caught and return empty list without crashing."""
        mock_urlopen.side_effect = HTTPError(
            url="https://nvidia.wd5.myworkdayjobs.com/wday/cxs/jobs",
            code=503,
            msg="Service Unavailable",
            hdrs={},
            fp=None,
        )
        jobs = workday_fetch_jobs("https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite")
        self.assertEqual(jobs, [])

    @patch("urllib.request.urlopen")
    def test_ashby_http_500_internal_error(self, mock_urlopen):
        """HTTP 500 on Ashby must return None indicating blocked API and not terminate process."""
        mock_urlopen.side_effect = HTTPError(
            url="https://api.ashbyhq.com/posting-api/job-board/test",
            code=500,
            msg="Internal Server Error",
            hdrs={},
            fp=None,
        )
        jobs = ashby_fetch_jobs("test")
        self.assertIsNone(jobs)

    # -- 3. Corrupted & Malformed Payloads -------------------------------------

    @patch("urllib.request.urlopen")
    def test_malformed_truncated_json_feed(self, mock_urlopen):
        """Simulate connection drop midway through JSON response resulting in truncated syntax."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"jobs": [{"title": "Software Engineer", "link": "http'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        jobs = lever_fetch_jobs("testco")
        self.assertEqual(jobs, [])

    @patch("urllib.request.urlopen")
    def test_greenhouse_null_jobs_key_regression(self, mock_urlopen):
        """
        Verify regression fix in greenhouse.py:
        When API returns {"jobs": null}, must return [] and NOT raise TypeError: 'NoneType' object is not iterable.
        """
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"jobs": null}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        jobs = gh_fetch_jobs("testco")
        self.assertEqual(jobs, [])

    @patch("urllib.request.urlopen")
    def test_html_error_page_with_status_200(self, mock_urlopen):
        """Cloudflare challenge or maintenance HTML page returned with HTTP 200."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"<html><body>Attention Required! Cloudflare DDOS Check</body></html>"
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        jobs = workable_fetch_jobs("testco")
        self.assertIsNone(jobs)

    # -- 4. Network Drops & Unreachable Hosts ----------------------------------

    @patch("urllib.request.urlopen", side_effect=URLError("Connection refused: host unreachable"))
    def test_jd_fetcher_unreachable_host(self, mock_urlopen):
        """Fast HTTP JD fetcher must catch URLError and return empty string."""
        text = _fetch_http("https://unreachable-company-host.org/job/123")
        self.assertEqual(text, "")

    @patch("urllib.request.urlopen", side_effect=ConnectionResetError("Connection reset by peer"))
    def test_connection_reset_by_peer(self, mock_urlopen):
        """TCP Reset by peer during ATS scrape must be handled cleanly."""
        jobs = sr_fetch_jobs("square")
        self.assertEqual(jobs, [])

    # -- 5. Gemini Dual-Model Pool Quota Chaos & Failover ---------------------

    @patch("scraper.gemini.genai.Client")
    def test_gemini_model_pool_failover_on_429(self, mock_client_cls):
        """
        Verify instant failover:
        When Model 1 encounters a 429 Rate Limit, ModelPool immediately tries Model 2
        without sleeping, and returns Model 2's successful output.
        """
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        # Model 1 raises 429 quota error; Model 2 returns valid JSON response
        resp_model2 = MagicMock()
        resp_model2.text = json.dumps({"experience_verdict": "SAFE", "verdict_reason": "Entry level"})

        def mock_generate_content(model, contents, config):
            if "gemini-3.5-flash-lite" in model:
                raise Exception("429 ResourceExhausted: Quota exceeded for model")
            return resp_model2

        mock_client.models.generate_content.side_effect = mock_generate_content

        cfg = {
            "_gemini_api_key": "test-key",
            "ai_models": {
                "models": ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"],
                "rpm_limit": 15,
                "rpd_limit": 1500,
            },
        }

        pool = ModelPool(cfg)
        result_text = pool.generate("Verify job description")

        parsed = json.loads(result_text)
        self.assertEqual(parsed["experience_verdict"], "SAFE")
        # Verify Model 1 was marked as exhausted
        self.assertEqual(pool._stats["gemini-3.5-flash-lite"]["minute_count"], 15)
        # Verify Model 2 recorded 1 successful usage
        self.assertEqual(pool._stats["gemini-3.1-flash-lite"]["minute_count"], 1)


if __name__ == "__main__":
    unittest.main()
