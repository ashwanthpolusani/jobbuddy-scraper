"""Lever ATS API parser."""
import json
import re
import urllib.request


def extract_slug(url: str) -> str | None:
    api_match = re.search(r"api\.lever\.co/v0/postings/([^/?#]+)", url)
    if api_match:
        return api_match.group(1)
    match = re.search(r"lever\.co/([^/?#]+)", url)
    return match.group(1) if match else None


def fetch_jobs(slug: str) -> list[dict] | None:
    """Fetch all jobs from Lever public API."""
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json, text/plain, */*",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as resp:
            jobs = json.loads(resp.read().decode("utf-8"))
            return [
                {
                    "title":    j.get("text", ""),
                    "location": j.get("categories", {}).get("location", ""),
                    "link":     j.get("hostedUrl", ""),
                    "content":  j.get("descriptionPlain", ""),
                }
                for j in jobs
            ]
    except Exception as e:
        print(f"    [Lever API Error] {e}")
        return []


def process(url: str) -> tuple[bool, list[dict], str]:
    slug = extract_slug(url)
    if slug:
        jobs = fetch_jobs(slug)
        if jobs is not None:
            return True, jobs, "Lever"
    return False, [], "Lever"
