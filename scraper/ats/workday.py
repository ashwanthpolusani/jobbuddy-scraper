"""Workday ATS API parser (CXS JSON API)."""
import json
import re
import urllib.request


def extract_params(url: str) -> tuple[str, str, str] | None:
    """Extract (tenant, domain, site_name) from a Workday URL."""
    match = re.search(
        r"https://([a-zA-Z0-9\-]+)\.([^/]+myworkdayjobs\.com)/(?:[a-zA-Z]{2}-[a-zA-Z]{2}/)?([^/]+)",
        url,
    )
    if not match:
        return None
    tenant = match.group(1)
    domain = f"{tenant}.{match.group(2)}"
    site   = match.group(3)
    if site.startswith("job") or site.startswith("login"):
        return None
    return tenant, domain, site


def fetch_jobs(url: str) -> list[dict]:
    """Fetch all jobs from Workday CXS JSON API with dynamic total pagination."""
    params = extract_params(url)
    if not params:
        return []
    tenant, domain, site = params
    api_url = f"https://{domain}/wday/cxs/{tenant}/{site}/jobs"
    headers = {
        "Accept":       "application/json",
        "Content-Type": "application/json",
        "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    }
    all_jobs, offset, limit, max_pages, page = [], 0, 20, 250, 0
    try:
        while page < max_pages:
            data = json.dumps({"limit": limit, "offset": offset}).encode("utf-8")
            req  = urllib.request.Request(api_url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                postings  = resp_data.get("jobPostings", [])
                if not postings:
                    break
                for p in postings:
                    ext_path = p.get("externalPath", "")
                    all_jobs.append({
                        "title":    p.get("title", ""),
                        "location": p.get("locationsText", ""),
                        "link":     f"https://{domain}/en-US/{site}{ext_path}",
                        "content":  "",
                    })
                total = resp_data.get("total")
                if total is not None and len(all_jobs) >= total:
                    break
                offset += limit
                page   += 1
    except Exception as e:
        print(f"    [Workday API Error] {e}")
    return all_jobs


def process(url: str) -> tuple[bool, list[dict], str]:
    if extract_params(url):
        return True, fetch_jobs(url), "Workday"
    return False, [], "Workday"
