"""SmartRecruiters ATS API parser."""
import json
import re
import urllib.request


def extract_token(url: str) -> str | None:
    match = re.search(r"smartrecruiters\.com/(?:v1/companies/)?([^/?#]+)", url)
    if match:
        token = match.group(1)
        if token not in ("v1", "companies", "jobs", "postings"):
            return token
    return None


def fetch_jobs(token: str) -> list[dict]:
    """Fetch jobs from SmartRecruiters public API."""
    api_url = f"https://api.smartrecruiters.com/v1/companies/{token}/postings"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    all_jobs, offset, limit, max_pages = [], 0, 100, 20
    try:
        for _ in range(max_pages):
            req = urllib.request.Request(f"{api_url}?limit={limit}&offset={offset}", headers=headers)
            with urllib.request.urlopen(req, timeout=12) as resp:
                data  = json.loads(resp.read().decode("utf-8"))
                items = data.get("content", [])
                if not items:
                    break
                for j in items:
                    city    = j.get("location", {}).get("city", "")
                    country = j.get("location", {}).get("country", "")
                    loc     = ", ".join(filter(None, [city, country]))
                    job_id = j.get("id", "")
                    link = f"https://jobs.smartrecruiters.com/{token}/{job_id}" if job_id else j.get("ref", "")
                    all_jobs.append({
                        "title":    j.get("name", ""),
                        "location": loc,
                        "link":     link,
                        "content":  "",
                    })
                total = data.get("totalFound", 0)
                offset += limit
                if offset >= total:
                    break
    except Exception as e:
        print(f"    [SmartRecruiters API Error for {token}] {e}")
    return all_jobs


def process(url: str) -> tuple[bool, list[dict], str]:
    token = extract_token(url)
    if token:
        jobs = fetch_jobs(token)
        if jobs:
            return True, jobs, "SmartRecruiters"
    return False, [], "SmartRecruiters"
