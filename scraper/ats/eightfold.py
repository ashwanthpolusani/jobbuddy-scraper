"""Eightfold ATS API parser (paginated)."""
import json
import re
import urllib.parse
import urllib.request


def normalize_eightfold_url(url: str) -> str:
    """Converts careers UI URL to the Eightfold API endpoint."""
    if "/api/apply/v2/jobs" in url:
        return url
    parsed = urllib.parse.urlparse(url)
    domain_host = parsed.netloc.split(":")[0]
    return f"https://{domain_host}/api/apply/v2/jobs"


def fetch_jobs(url: str) -> list[dict]:
    """Fetch all jobs from Eightfold API, looping through pages automatically."""
    api_endpoint = normalize_eightfold_url(url)
    base_url  = re.sub(r"[?&]start=[^&]+", "", api_endpoint)
    base_url  = re.sub(r"[?&]num=[^&]+",  "", base_url)
    separator = "&" if "?" in base_url else "?"
    all_jobs, start, num, max_pages, page = [], 0, 10, 100, 0
    try:
        while page < max_pages:
            fetch_url = f"{base_url}{separator}start={start}&num={num}"
            req = urllib.request.Request(fetch_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data      = json.loads(resp.read().decode("utf-8"))
                positions = data.get("positions", [])
                if not positions:
                    break
                for p in positions:
                    all_jobs.append({
                        "title":    p.get("name", ""),
                        "location": p.get("location", ""),
                        "link":     p.get("canonicalPositionUrl", ""),
                        "content":  "",
                    })
                start += num
                page  += 1
                if start >= data.get("count", 0):
                    break
                import time
                time.sleep(0.3)  # Polite pacing to avoid HTTP 429 on deep pagination
    except Exception as e:
        print(f"    [Eightfold API Error] {e}")
    return all_jobs


def process(url: str) -> tuple[bool, list[dict], str]:
    return True, fetch_jobs(url), "Eightfold"
