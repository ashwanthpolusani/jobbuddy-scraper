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
    """Fetch jobs from Workable public widget API.

    The Workable widget API returns ``data["name"]`` as the canonical company
    name (e.g. ``"Mercari, inc."``). We capture it here so that
    ``stage1.py``'s fallback company name (derived from the ``target_urls``
    document) is never needed for Workable jobs.
    """
    url = f"https://apply.workable.com/api/v1/widget/accounts/{slug}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            # Prefer the name field from the API; fall back to a human-readable
            # slug derivation so we never store placeholder values like "Apply".
            company_name = (data.get("name") or "").strip() or slug.replace("-", " ").replace("_", " ").title()
            return [
                {
                    "title":        j.get("title", ""),
                    "company_name": company_name,
                    "location":     ", ".join(filter(None, [j.get("city", ""), j.get("country", "")])),
                    "link":         f"https://apply.workable.com/{slug}/j/{j.get('shortcode', '')}",
                    "content":      "",
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
