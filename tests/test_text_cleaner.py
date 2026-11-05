"""
tests/test_text_cleaner.py - Comprehensive unit tests for:
- extract_text_from_html
- extract_core_requirements
- Workday CXS JD fetcher (_fetch_workday_jd)
- Fast HTTP fetcher (_fetch_http)
Covers tag stripping, entity unescaping, regex section targeting, EEO boilerplate removal,
length truncation at word boundaries, and fallback strategies.
"""
import io
import json
import unittest
from unittest.mock import patch, MagicMock

from scraper.jd_fetcher import (
    extract_text_from_html,
    extract_core_requirements,
    _fetch_workday_jd,
    _fetch_http,
)


class TestHtmlCleaner(unittest.TestCase):
    """Unit tests for extract_text_from_html."""

    def test_empty_and_none_input(self):
        self.assertEqual(extract_text_from_html(""), "")
        self.assertEqual(extract_text_from_html(None), "")
        self.assertEqual(extract_text_from_html("   \n\t  "), "")

    def test_html_entity_unescaping(self):
        html_input = (
            "&lt;div class=&quot;header&quot;&gt;Tom &amp; Jerry&#39;s &quot;Fun&quot;&lt;/div&gt;"
            "&nbsp;Price: &euro;100 &amp; &pound;50"
        )
        cleaned = extract_text_from_html(html_input)
        self.assertNotIn("&lt;", cleaned)
        self.assertNotIn("&gt;", cleaned)
        self.assertNotIn("&quot;", cleaned)
        self.assertNotIn("&amp;", cleaned)
        self.assertNotIn("&#39;", cleaned)
        self.assertIn("Tom & Jerry's \"Fun\"", cleaned)
        self.assertIn("Price: €100 & £50", cleaned)

    def test_block_level_tags_converted_to_newlines(self):
        html_input = (
            "<p>Paragraph 1</p>"
            "<div>Division 1</div>"
            "<ul>"
            "  <li>Bullet 1</li>"
            "  <li>Bullet 2</li>"
            "</ul>"
            "<br>"
            "<table><tr><td>Cell 1</td></tr></table>"
        )
        cleaned = extract_text_from_html(html_input)
        lines = [line.strip() for line in cleaned.split("\n") if line.strip()]
        self.assertIn("Paragraph 1", lines)
        self.assertIn("Division 1", lines)
        self.assertIn("Bullet 1", lines)
        self.assertIn("Bullet 2", lines)
        self.assertIn("Cell 1", lines)

    def test_strip_scripts_styles_and_svgs_with_internal_content(self):
        html_input = (
            "<div>Headline Text</div>"
            "<script type='text/javascript'>"
            "  var x = 100; function test() { return '<tag>'; }"
            "</script>"
            "<style>"
            "  body { background: #fff; font-size: 14px; }"
            "</style>"
            "<svg width='100' height='100'>"
            "  <circle cx='50' cy='50' r='40' stroke='green' />"
            "</svg>"
            "<p>Valid Body Content</p>"
        )
        cleaned = extract_text_from_html(html_input)
        self.assertIn("Headline Text", cleaned)
        self.assertIn("Valid Body Content", cleaned)
        self.assertNotIn("var x = 100", cleaned)
        self.assertNotIn("background: #fff", cleaned)
        self.assertNotIn("circle cx", cleaned)

    def test_case_insensitive_script_and_style_stripping(self):
        html_input = (
            "<SCRIPT>console.log('secret');</SCRIPT>"
            "<STYLE>p { color: red; }</STYLE>"
            "<SVG><path d='M0 0'/></SVG>"
            "<p>Visible Text</p>"
        )
        cleaned = extract_text_from_html(html_input)
        self.assertNotIn("console.log", cleaned)
        self.assertNotIn("color: red", cleaned)
        self.assertEqual(cleaned, "Visible Text")

    def test_max_chars_truncation(self):
        long_html = "<p>" + ("word " * 500) + "</p>"
        cleaned = extract_text_from_html(long_html, max_chars=50)
        self.assertLessEqual(len(cleaned), 50)


class TestCoreRequirementsExtractor(unittest.TestCase):
    """Unit tests for extract_core_requirements."""

    def test_empty_content_with_title_fallback(self):
        res = extract_core_requirements("", title="Backend Developer")
        self.assertEqual(res, "Entry-level role for Backend Developer.")

    def test_empty_content_without_title_fallback(self):
        res = extract_core_requirements("", title="")
        self.assertEqual(res, "Qualifications detailed in job posting.")

    def test_extract_requirements_section_with_bullets(self):
        content = """
        <h2>About Acme</h2>
        <p>Acme builds high throughput financial systems.</p>
        
        <h2>Requirements</h2>
        <ul>
            <li>Strong proficiency in Python, Django, and Fast-API</li>
            <li>Hands-on experience with PostgreSQL and Redis caching</li>
            <li>Familiarity with Docker and Kubernetes deployment</li>
            <li>Knowledge of AWS services (S3, ECS, SQS)</li>
        </ul>
        
        <h2>Benefits</h2>
        <p>We offer health insurance, 401k, and unlimited PTO.</p>
        """
        extracted = extract_core_requirements(content, title="Software Engineer")
        self.assertIn("Python, Django, and Fast-API", extracted)
        self.assertIn("PostgreSQL and Redis caching", extracted)
        self.assertIn("Docker and Kubernetes deployment", extracted)
        # Verifies bullet points are joined with ' • ' and max 3 bullets
        self.assertIn(" • ", extracted)
        self.assertNotIn("About Acme", extracted)
        self.assertNotIn("Benefits", extracted)
        self.assertNotIn("unlimited PTO", extracted)

    def test_extract_qualifications_headers_variants(self):
        header_variants = [
            "Qualifications:",
            "What you'll bring:",
            "What you bring:",
            "What we look for:",
            "Basic Qualifications:",
            "Minimum Qualifications:",
            "Who you are:",
        ]
        for header in header_variants:
            with self.subTest(header=header):
                content = f"""
                <p>Welcome to our careers page.</p>
                <h3>{header}</h3>
                • 0-1 years of experience in Go or C++
                • Solid grasp of data structures and algorithms
                • B.Tech or M.Tech in Computer Science
                
                <h3>What We Offer</h3>
                Competitive compensation package.
                """
                extracted = extract_core_requirements(content, title="Junior Developer")
                self.assertIn("0-1 years of experience in Go or C++", extracted)
                self.assertIn("Solid grasp of data structures", extracted)

    def test_filter_out_eeo_and_diversity_boilerplate(self):
        content = """
        <h3>Basic Qualifications</h3>
        • Bachelor's degree in Computer Science
        • We are an equal opportunity employer and value diversity at our company
        • Experience with React, TypeScript, and CSS
        • Affirmative action employer committed to inclusion
        • Strong communication skills
        """
        extracted = extract_core_requirements(content, title="Frontend Dev")
        self.assertIn("Bachelor's degree in Computer Science", extracted)
        self.assertIn("Experience with React, TypeScript, and CSS", extracted)
        self.assertIn("Strong communication skills", extracted)
        self.assertNotIn("equal opportunity", extracted.lower())
        self.assertNotIn("affirmative action", extracted.lower())

    def test_max_chars_truncation_at_word_boundary(self):
        content = """
        <h2>Requirements</h2>
        • Exceptionally long bullet point detailing extensive microservice architectures and distributed consensus protocols
        • Another verbose requirement covering continuous integration and deployment pipelines with Terraform and Ansible
        • A third bullet describing event-driven systems with Apache Kafka, RabbitMQ, and Apache Flink stream processing
        """
        extracted = extract_core_requirements(content, max_chars=120)
        self.assertLessEqual(len(extracted), 120)
        self.assertTrue(extracted.endswith("..."))
        # Ensure it didn't cut off inside a word
        before_ellipsis = extracted[:-3]
        self.assertFalse(before_ellipsis.endswith(" "))

    def test_fallback_to_meaningful_paragraph_when_no_section_header(self):
        content = """
        <p>Who is Acme Corp? Acme Corp is a global software enterprise.</p>
        <p>About us: We were founded in 2010 in San Francisco.</p>
        <p>Looking for a motivated Junior QA Analyst proficient in Selenium and test automation frameworks.</p>
        <p>Equal opportunity employer.</p>
        """
        extracted = extract_core_requirements(content, title="QA Analyst")
        self.assertIn("Looking for a motivated Junior QA Analyst", extracted)
        self.assertNotIn("Who is Acme Corp", extracted)
        self.assertNotIn("About us", extracted)


class TestWorkdayAndHttpJdFetcher(unittest.TestCase):
    """Unit tests for _fetch_workday_jd and _fetch_http."""

    def test_fetch_workday_jd_success(self):
        url = "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/US-CA-Santa-Clara/Architect_JR1001"
        payload = {
            "jobPostingInfo": {
                "jobDescription": "<p>Build Next-Gen GPUs.</p><h2>Requirements</h2><ul><li>Proficiency in Verilog</li></ul>"
            }
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            text = _fetch_workday_jd(url)
            self.assertIn("Build Next-Gen GPUs", text)
            self.assertIn("Proficiency in Verilog", text)

    def test_fetch_workday_jd_invalid_url_returns_empty(self):
        self.assertEqual(_fetch_workday_jd("https://example.com/not-workday"), "")

    def test_fetch_workday_jd_exception_returns_empty(self):
        url = "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/Santa-Clara/Architect_JR1"
        with patch("urllib.request.urlopen", side_effect=Exception("Network error")):
            self.assertEqual(_fetch_workday_jd(url), "")

    def test_fetch_http_success_for_large_html(self):
        html_content = "<html><body>" + ("<p>Job content line</p>" * 50) + "</body></html>"
        mock_resp = MagicMock()
        mock_resp.read.return_value = html_content.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            res = _fetch_http("https://example.com/job/1")
            self.assertIn("Job content line", res)

    def test_fetch_http_short_response_returns_empty(self):
        # Under 500 characters returns empty
        short_html = "<html><body>Too short</body></html>"
        mock_resp = MagicMock()
        mock_resp.read.return_value = short_html.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            self.assertEqual(_fetch_http("https://example.com/short"), "")

    def test_fetch_http_exception_returns_empty(self):
        with patch("urllib.request.urlopen", side_effect=Exception("DNS lookup failed")):
            self.assertEqual(_fetch_http("https://unreachable.domain"), "")


if __name__ == "__main__":
    unittest.main()
