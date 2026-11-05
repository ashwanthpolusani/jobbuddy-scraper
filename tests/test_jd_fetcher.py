"""
tests/test_jd_fetcher.py - Comprehensive unit tests for JDFetcher and text extraction utilities.
Tests HTML parsing, entity unescaping, requirements extraction, regex pattern matching,
and Workday CXS API extraction logic without external network calls.
"""
import io
import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from scraper.jd_fetcher import (
    extract_text_from_html,
    extract_core_requirements,
    _fetch_http,
    _fetch_workday_jd,
    JDFetcher
)


class TestJDFetcher(unittest.TestCase):
    def test_extract_text_strips_scripts_and_styles(self):
        html_input = """
        <html>
            <head>
                <style>body { color: red; }</style>
                <script>console.log("analytics");</script>
            </head>
            <body>
                <h1>Software Engineer</h1>
                <p>Welcome to our team.</p>
                <svg><circle cx="50" cy="50" r="40" /></svg>
            </body>
        </html>
        """
        result = extract_text_from_html(html_input)
        self.assertNotIn("color: red", result)
        self.assertNotIn("console.log", result)
        self.assertNotIn("circle cx", result)
        self.assertIn("Software Engineer", result)
        self.assertIn("Welcome to our team.", result)

    def test_extract_text_unescapes_entities(self):
        raw = "We are seeking &quot;full-stack&quot; engineers with C++ &amp; Python &lt;3 yrs."
        result = extract_text_from_html(raw)
        self.assertEqual(result, 'We are seeking "full-stack" engineers with C++ & Python <3 yrs.')

    def test_extract_text_empty_and_max_chars(self):
        self.assertEqual(extract_text_from_html(""), "")
        self.assertEqual(extract_text_from_html(None), "")
        long_text = "<p>" + ("A" * 1000) + "</p>"
        self.assertEqual(len(extract_text_from_html(long_text, max_chars=100)), 100)

    def test_extract_core_requirements_section_bullets(self):
        jd = """
        About Us:
        We are a fast-growing tech company founded in 2020.

        What You'll Bring:
        • Strong knowledge of Python and SQL
        • Understanding of REST APIs and Docker
        • Bachelor's degree in Computer Science or related field
        • We are an equal opportunity employer and value diversity.

        What We Offer:
        • Competitive salary and stock options
        """
        reqs = extract_core_requirements(jd, title="Python Engineer")
        self.assertIn("Strong knowledge of Python and SQL", reqs)
        self.assertIn("Understanding of REST APIs and Docker", reqs)
        self.assertIn("Bachelor's degree in Computer Science", reqs)
        # EEO line must be stripped
        self.assertNotIn("equal opportunity", reqs)

    def test_extract_core_requirements_numbered_bullets(self):
        jd = """
        Minimum Qualifications:
        1. Proficiency in JavaScript / TypeScript.
        2. Experience with React and Next.js.
        3. Familiarity with Git version control.

        Benefits:
        Health insurance.
        """
        reqs = extract_core_requirements(jd, title="Frontend Dev")
        self.assertIn("Proficiency in JavaScript / TypeScript", reqs)
        self.assertIn("Experience with React and Next.js", reqs)
        self.assertFalse(reqs.startswith("1."))

    def test_extract_core_requirements_empty_content_fallback(self):
        res = extract_core_requirements("", title="Junior Data Analyst")
        self.assertEqual(res, "Entry-level role for Junior Data Analyst.")
        res2 = extract_core_requirements("")
        self.assertEqual(res2, "Qualifications detailed in job posting.")

    def test_extract_core_requirements_fallback_paragraphs(self):
        jd = """
        Company Overview:
        Founded in 2018 in San Francisco.

        We are looking for self-motivated engineers who want to build real-time distributed platforms.
        """
        res = extract_core_requirements(jd, title="Backend Engineer")
        self.assertIn("self-motivated engineers", res)

    @patch("urllib.request.urlopen")
    def test_fetch_workday_jd_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "jobPostingInfo": {
                "jobDescription": "<p>Responsible for building scalable microservices in Java.</p>"
            }
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        url = "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/Bengaluru/Software-Engineer_JR19001"
        res = _fetch_workday_jd(url)
        self.assertIn("Responsible for building scalable microservices in Java", res)

    @patch("urllib.request.urlopen")
    def test_fetch_workday_jd_failure(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Workday 404 Not Found")
        url = "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/Bengaluru/Invalid_JR999"
        res = _fetch_workday_jd(url)
        self.assertEqual(res, "")

    @patch("urllib.request.urlopen")
    def test_fetch_http_success(self, mock_urlopen):
        mock_resp = MagicMock()
        # Must be > 500 bytes per _fetch_http threshold
        mock_resp.read.return_value = ("<html><body>" + ("<p>Job content</p>" * 50) + "</body></html>").encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        html = _fetch_http("https://jobs.example.com/123")
        self.assertTrue(len(html) > 500)

    @patch("urllib.request.urlopen")
    def test_fetch_http_short_response_ignored(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"<html>Short</html>"
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        html = _fetch_http("https://jobs.example.com/123")
        self.assertEqual(html, "")

    def test_jd_fetcher_lifecycle(self):
        fetcher = JDFetcher()
        self.assertIsNone(fetcher._browser)
        self.assertIsNone(fetcher._playwright)
        # Calling close on uninitialized fetcher must be safely idempotent
        fetcher.close()
        self.assertIsNone(fetcher._browser)


if __name__ == "__main__":
    unittest.main()
