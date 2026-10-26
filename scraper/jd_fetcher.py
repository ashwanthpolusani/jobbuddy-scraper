"""
scraper/jd_fetcher.py - Fetches full job description HTML/text for Stage 2.
Tries fast HTTP first; falls back to Workday CXS JSON API or persistent Playwright.
Keeps 1 persistent Playwright browser session across batch runs to eliminate process churn.
"""
import json
import re
import urllib.request
from playwright.sync_api import sync_playwright


def extract_text_from_html(html: str, max_chars: int = 8000) -> str:
    """Strip scripts, styles, and tags from HTML - return clean readable text."""
    html = re.sub(r"<script.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style.*?</style>",   "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<svg.*?</svg>",       "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<[^>]+>", " ", html)
    html = re.sub(r"\s{3,}", "\n\n", html)
    return html.strip()[:max_chars]


def _fetch_http(url: str) -> str:
    """Fast urllib fetch - works for 85%+ of ATS pages in ~100ms."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html,*/*;q=0.8"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            if len(html) > 500:
                return html
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

        html = _fetch_http(url)
        if html:
            return extract_text_from_html(html)

        # Persistent Playwright fallback
        try:
            browser = self._get_browser()
            if browser:
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(1500)
                html = page.content()
                page.close()
                if html:
                    return extract_text_from_html(html)
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
