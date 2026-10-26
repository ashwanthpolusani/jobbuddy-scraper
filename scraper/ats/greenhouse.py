"""Greenhouse ATS API parser with official boards-api EU endpoint."""
import json
import re
import urllib.parse
import urllib.request
from urllib.error import HTTPError


def extract_slug(url: str) -> str | None:
    api_match = re.search(r"boards-api(?:\.eu)?\.greenhouse\.io/v1/boards/([^/?#]+)", url)
    if api_match:
        return api_match.group(1)
    match = re.search(r"greenhouse\.io/([^/?#]+)", url)
    if match:
        slug = match.group(1)
        if slug == "embed":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            return qs.get("for", [None])[0]
        return slug
    return None


def fetch_jobs(slug: str) -> list[dict] | None:
    """Fetch all jobs from Greenhouse public API (standard and EU boards-api)."""
    urls = [
        f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
        f"https://boards-api.eu.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    ]
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data  = json.loads(resp.read().decode("utf-8"))
                return [
                    {
                        "title":    j.get("title", ""),
                        "location": j.get("location", {}).get("name", ""),
                        "link":     j.get("absolute_url", ""),
                        "content":  j.get("content", ""),
                    }
                    for j in data.get("jobs", [])
                ]
        except HTTPError as e:
            if e.code == 404:
                continue
            print(f"    [Greenhouse API Blocked for {slug}] HTTP {e.code}")
            return None
        except Exception as e:
            return []
    return None


def process(url: str) -> tuple[bool, list[dict], str]:
    slug = extract_slug(url)
    if slug:
        jobs = fetch_jobs(slug)
        if jobs is not None:
            return True, jobs, "Greenhouse"
    return False, [], "Greenhouse"
