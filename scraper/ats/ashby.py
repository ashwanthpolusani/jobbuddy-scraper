"""Ashby ATS API parser."""
import json
import re
import urllib.request
from urllib.error import HTTPError


def extract_slug(url: str) -> str | None:
    api_match = re.search(r"api\.ashbyhq\.com/posting-api/job-board/([^/?#]+)", url)
    if api_match:
        return api_match.group(1)
    match = re.search(r"ashbyhq\.com/([^/?#]+)", url)
    return match.group(1) if match else None


def _normalize_location(j: dict) -> str:
    loc_name = (j.get("location") or "").strip()
    addr = j.get("address") or {}
    postal = addr.get("postalAddress") or {}
    country = (postal.get("addressCountry") or "").strip()
    region = (postal.get("addressRegion") or "").strip()

    parts = []
    if loc_name and loc_name != "Unknown Location":
        parts.append(loc_name)
    if region and region.lower() not in loc_name.lower():
        parts.append(region)
    if country and country.lower() not in loc_name.lower():
        parts.append(country)

    full = ", ".join(parts)
    if j.get("isRemote"):
        if not full:
            return "Remote"
        if "remote" not in full.lower():
            return f"{full} (Remote)"
    return full or "Unknown Location"


def fetch_jobs(slug: str) -> list[dict] | None:
    """Fetch and normalize Ashby jobs via their public API."""
    api_url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return [
                {
                    "title":    j.get("title", "Unknown Title"),
                    "location": _normalize_location(j),
                    "link":     j.get("jobUrl", ""),
                    "content":  j.get("descriptionPlain", ""),
                }
                for j in data.get("jobs", [])
            ]
    except HTTPError as e:
        print(f"    [Ashby API Blocked] HTTP {e.code}")
        return None
    except Exception as e:
        print(f"    [Ashby API Error] {e}")
        return []


def process(url: str) -> tuple[bool, list[dict], str]:
    slug = extract_slug(url)
    if slug:
        jobs = fetch_jobs(slug)
        if jobs is not None:
            return True, jobs, "Ashby"
    return False, [], "Ashby"
