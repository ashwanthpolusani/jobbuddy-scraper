"""Uber Jobs API parser."""
import json
import re
import urllib.request


def fetch_jobs(url: str) -> list[dict]:
    """Fetch jobs from Uber public careers API with automatic pagination."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept":     "*/*",
        "Referer":    "https://jobs.uber.com/en/jobs/",
    }
    # Extract or build query string
    if "?" in url:
        query_string = url.split("?", 1)[1]
    elif "=" in url:
        query_string = url
    else:
        query_string = f"location={url}" if url else "location=Bengaluru"

    query_string = re.sub(r"[?&]page=\d+", "", query_string).strip("&")

    all_jobs, page, max_pages = [], 1, 10
    try:
        while page <= max_pages:
            api_url = f"https://jobs.uber.com/api/jobs/search/?{query_string}&page={page}"
            req = urllib.request.Request(api_url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                jobs = data.get("jobs", [])
                if not jobs:
                    break
                for j in jobs:
                    cities  = [loc.get("City") for loc in j.get("Locations", []) if loc.get("City")]
                    country = (j.get("Locations", [{}])[0].get("Country")) if j.get("Locations") else ""
                    loc_str = ", ".join(filter(None, cities + ([country] if country else []))) or "India"
                    job_path = j.get("Urls", [{}])[0].get("Url", f"/en/jobs/{j.get('Id')}/")
                    all_jobs.append({
                        "title":    j.get("Title", "Unknown Title"),
                        "location": loc_str,
                        "link":     f"https://jobs.uber.com{job_path}",
                        "content":  j.get("Description", ""),
                        "id":       str(j.get("Id", "")),
                    })
                if page >= data.get("totalPages", 1):
                    break
                page += 1
    except Exception as e:
        print(f"    [Uber API Error] {e}")
    return all_jobs


def process(url: str) -> tuple[bool, list[dict], str]:
    if "jobs.uber.com" in url or "uber.com/api/jobs" in url:
        return True, fetch_jobs(url), "Uber"
    if "uber.com" in url:
        # Fetch Bengaluru + Hyderabad, deduplicate
        blr = fetch_jobs("location=Bengaluru")
        hyd = fetch_jobs("location=Hyderabad")
        seen: set[str] = set()
        combined: list[dict] = []
        for j in blr + hyd:
            key = j.get("id") or j.get("link", "")
            if key not in seen:
                seen.add(key)
                combined.append(j)
        return True, combined, "Uber"
    return False, [], "Uber"
