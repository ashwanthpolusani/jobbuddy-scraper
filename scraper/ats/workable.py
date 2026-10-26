"""Workable ATS API parser."""
import json
import re
import urllib.request


def extract_slug(url: str) -> str | None:
    m1 = re.search(r"([a-zA-Z0-9\-]+)\.workable\.com", url)
    if m1 and m1.group(1) not in ("apply", "www", "jobs", "api"):
        return m1.group(1)
    m2 = re.search(r"workable\.com/(?:api/v\d+/widget/accounts/)?([a-zA-Z0-9\-]+)", url)
    if m2 and m2.group(1) not in ("api", "widget", "accounts", "jobs"):
        return m2.group(1)
    return None


def fetch_jobs(slug: str) -> list[dict] | None:
    """Fetch jobs from Workable public widget API."""
    url = f"https://apply.workable.com/api/v1/widget/accounts/{slug}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return [
                {
                    "title":    j.get("title", ""),
                    "location": ", ".join(filter(None, [j.get("city", ""), j.get("country", "")])),
                    "link":     f"https://apply.workable.com/{slug}/j/{j.get('shortcode', '')}",
                    "content":  "",
                }
                for j in data.get("jobs", [])
            ]
    except Exception as e:
        print(f"    [Workable API Error] {e}")
        return None


def process(url: str) -> tuple[bool, list[dict], str]:
    slug = extract_slug(url)
    if slug:
        jobs = fetch_jobs(slug)
        if jobs is not None:
            return True, jobs, "Workable"
    return False, [], "Workable"
