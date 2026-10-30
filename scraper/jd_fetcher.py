"""
scraper/jd_fetcher.py - Fetches full job description HTML/text for Stage 2.
Tries fast HTTP first; falls back to Workday CXS JSON API or persistent Playwright.
Keeps 1 persistent Playwright browser session across batch runs to eliminate process churn.
"""
import html
import json
import re
import urllib.request
from playwright.sync_api import sync_playwright


def extract_text_from_html(raw_html: str, max_chars: int = 8000) -> str:
    """Strip scripts, styles, and tags from HTML - return clean readable text."""
    if not raw_html:
        return ""
    # 1. Unescape HTML entities (e.g. &lt;div&gt; -> <div>, &quot; -> ", &amp; -> &)
    text = html.unescape(raw_html)
    text = text.replace("&nbsp;", " ").replace("\xa0", " ")
    # 2. Convert block-level / line-break tags to newlines before stripping
    text = re.sub(r"</?(?:p|div|h[1-6]|li|br|ul|ol|tr|table|article|section)[^>]*>", "\n", text, flags=re.IGNORECASE)
    # 3. Strip scripts, styles, SVGs
    text = re.sub(r"<script.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style.*?</style>",   "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<svg.*?</svg>",       "", text, flags=re.DOTALL | re.IGNORECASE)
    # 4. Strip remaining HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # 5. Normalize whitespace and empty lines
    lines = [line.strip() for line in text.split("\n")]
    clean_lines = []
    for line in lines:
        if line:
            clean_lines.append(re.sub(r"[ \t]+", " ", line))
    text = "\n".join(clean_lines)
    return text[:max_chars].strip()


def extract_core_requirements(content: str, title: str = "", max_chars: int = 280) -> str:
    """
    Extracts a clean, concise, 1-2 sentence core requirements summary from raw JD content/HTML.
    Intelligently targets Requirements/Qualifications sections and strips boilerplate.
    Guaranteed NEVER to return raw HTML or entity markup.
    """
    if not content:
        return f"Entry-level role for {title}." if title else "Qualifications detailed in job posting."

    clean_text = extract_text_from_html(content, max_chars=15000)
    if not clean_text:
        return f"Entry-level role for {title}." if title else "Qualifications detailed in job posting."

    # Search for Requirements / Qualifications / Skills section
    section_pattern = re.compile(
        r"(?:what you(?:'ll)? (?:need|bring)|requirements|qualifications|skills|who you are|minimum qualifications|basic qualifications|what we look for)[\s:\-]*\n+(.*?)(?=\n\s*(?:what we offer|benefits|perks|about us|about the company|who we are|nice to have|preferred qualifications)|\Z)",
        re.DOTALL | re.IGNORECASE
    )
    m = section_pattern.search(clean_text)
    if m:
        extracted = m.group(1).strip()
        bullet_lines = [
            re.sub(r"^[•\-*–\d\.]+\s*", "", l).strip()
            for l in extracted.split("\n")
            if len(l.strip()) > 5
        ]
        bullet_lines = [b for b in bullet_lines if not any(skip in b.lower() for skip in ["equal opportunity", "we are an equal", "diversity", "affirmative action"])]
        if bullet_lines:
            res = " • ".join(bullet_lines[:3])
            if len(res) > max_chars:
                res = res[:max_chars - 3].rsplit(" ", 1)[0] + "..."
            return res

    # Fallback: scan lines for first meaningful non-intro paragraph
    lines = clean_text.split("\n")
    boilerplate_words = ["who is", "about us", "about the company", "about the team", "founded in", "equal opportunity", "privacy policy", "our mission", "company overview", "job description"]
    for l in lines:
        l_str = l.strip()
        if len(l_str) >= 30 and not any(bw in l_str.lower() for bw in boilerplate_words):
            if len(l_str) > max_chars:
                return l_str[:max_chars - 3].rsplit(" ", 1)[0] + "..."
            return l_str

    fallback = clean_text[:max_chars].strip()
    return fallback + ("..." if len(clean_text) > max_chars else "")


def _fetch_http(url: str) -> str:
    """Fast urllib fetch - works for 85%+ of ATS pages in ~100ms."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html,*/*;q=0.8"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            html_text = resp.read().decode("utf-8", errors="ignore")
            if len(html_text) > 500:
                return html_text
    except Exception:
        pass
    return ""


def _fetch_workday_jd(url: str) -> str:
    """Direct Workday CXS JSON API - avoids browser rendering entirely."""
    try:
        match = re.search(
            r"https://([a-zA-Z0-9\-]+)\.([^/]+myworkdayjobs\.com)"
            r"/(?:[a-zA-Z]{2}-[a-zA-Z]{2}/)?([^/]+)/job/(.+)",
            url,
        )
        if match:
            tenant   = match.group(1)
            domain   = f"{tenant}.{match.group(2)}"
            site     = match.group(3)
            job_path = match.group(4)
            api_url  = f"https://{domain}/wday/cxs/{tenant}/{site}/job/{job_path}"
            req = urllib.request.Request(
                api_url,
                headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data    = json.loads(resp.read().decode("utf-8"))
                jd_html = data.get("jobPostingInfo", {}).get("jobDescription", "")
                if jd_html:
                    return extract_text_from_html(jd_html)
    except Exception:
        pass
    return ""


class JDFetcher:
    """
    Session-aware Job Description fetcher.
    Keeps 1 Playwright Chromium browser open across the batch run if needed.
    """
    def __init__(self):
        self._playwright = None
        self._browser = None

    def _get_browser(self):
        if self._browser is None:
            try:
                self._playwright = sync_playwright().start()
                self._browser = self._playwright.chromium.launch(headless=True)
            except Exception as e:
                print(f"    [Playwright Init Warning] {e}")
        return self._browser

    def fetch(self, url: str) -> str:
        """Fetch JD text: Workday API -> Fast HTTP -> Persistent Playwright."""
        if "myworkdayjobs.com" in url:
            wd_text = _fetch_workday_jd(url)
            if wd_text:
                return wd_text

        html_text = _fetch_http(url)
        if html_text:
            return extract_text_from_html(html_text)

        # Persistent Playwright fallback
        try:
            browser = self._get_browser()
            if browser:
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(1500)
                page_html = page.content()
                page.close()
                if page_html:
                    return extract_text_from_html(page_html)
        except Exception as e:
            print(f"    [Playwright Fetch Warning] {e}")

        return ""

    def close(self):
        """Cleanly terminates the browser instance at the end of the batch."""
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
