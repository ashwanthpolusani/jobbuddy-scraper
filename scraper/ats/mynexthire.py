"""MyNextHire ATS API parser (used by Swiggy and others)."""
import json
import re
import urllib.request


def fetch_jobs(domain: str) -> list[dict]:
    """Fetch all jobs from MyNextHire public API."""
    api_url = f"https://{domain}/employer/careers/reqlist/get"
    headers = {
        "Accept":       "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    }
    payload = json.dumps({"source": "careers", "code": "", "filterByBuId": -1}).encode("utf-8")
    try:
        req = urllib.request.Request(api_url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            return [
                {
                    "title":    j.get("reqTitle", ""),
                    "location": j.get("location", ""),
                    "link":     f"https://{domain}/employer/jobs/careers?category={j.get('reqId', '')}",
                    "content":  "",
                }
                for j in resp_data.get("reqDetailsBOList", [])
            ]
    except Exception as e:
        print(f"    [MyNextHire API Error] {e}")
        return []


def process(url: str) -> tuple[bool, list[dict], str]:
    match = re.search(r"https://([^/]+\.mynexthire\.com)", url)
    if match:
        return True, fetch_jobs(match.group(1)), "MyNextHire"
    return False, [], "MyNextHire"
