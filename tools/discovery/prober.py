"""
discovery/prober.py - Probes ATS API endpoints and uses Gemini fallback to discover career URLs.
Maintains rate limits by accepting a shared ModelPool instance.
"""
import json
import urllib.request
import urllib.parse
from scraper.ats import process_url as ats_process_url
from scraper.gemini import ModelPool

_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def _http_get_json(url: str, timeout: int = 4):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as res:
            if res.status == 200:
                data = json.loads(res.read().decode("utf-8", errors="ignore"))
                return data
    except Exception:
        pass
    return None


def probe_greenhouse(slug: str) -> tuple[str | None, int]:
    """Test Greenhouse API for a slug."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    data = _http_get_json(url)
    if data and isinstance(data, dict) and "jobs" in data:
        return url, len(data.get("jobs", []))
    return None, 0


def probe_ashby(slug: str) -> tuple[str | None, int]:
    """Test Ashby posting API for a slug."""
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    data = _http_get_json(url)
    if data and isinstance(data, dict) and "jobs" in data:
        return url, len(data.get("jobs", []))
    return None, 0


def probe_lever(slug: str) -> tuple[str | None, int]:
    """Test Lever API for a slug."""
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    data = _http_get_json(url)
    if data and isinstance(data, list):
        board_url = f"https://jobs.lever.co/{slug}"
        return board_url, len(data)
    return None, 0


def probe_workable(slug: str) -> tuple[str | None, int]:
    """Test Workable API for a slug."""
    url = f"https://apply.workable.com/api/v1/widget/accounts/{slug}"
    data = _http_get_json(url)
    if data and isinstance(data, dict) and "jobs" in data:
        return f"https://apply.workable.com/{slug}/", len(data.get("jobs", []))
    return None, 0


def probe_smartrecruiters(slug: str) -> tuple[str | None, int]:
    """Test SmartRecruiters API for a slug."""
    url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
    data = _http_get_json(url)
    if data and isinstance(data, dict) and "content" in data:
        return f"https://careers.smartrecruiters.com/{slug}", len(data.get("content", []))
    return None, 0


def probe_all_ats(slug: str) -> tuple[str | None, str | None, int]:
    """Test a single slug across Greenhouse, Ashby, Lever, Workable, SmartRecruiters."""
    gh_url, count = probe_greenhouse(slug)
    if gh_url:
        return "Greenhouse", gh_url, count

    ashby_url, count = probe_ashby(slug)
    if ashby_url:
        return "Ashby", ashby_url, count

    lever_url, count = probe_lever(slug)
    if lever_url:
        return "Lever", lever_url, count

    workable_url, count = probe_workable(slug)
    if workable_url:
        return "Workable", workable_url, count

    sr_url, count = probe_smartrecruiters(slug)
    if sr_url:
        return "SmartRecruiters", sr_url, count

    return None, None, 0


def gemini_ats_lookup(cfg: dict, company_name: str, domain: str = "", pool: ModelPool | None = None) -> tuple[str | None, str | None]:
    """Fallback: Ask Gemini for the public ATS or career URL with preserved rate limits."""
    if pool is None:
        pool = ModelPool(cfg)
    prompt = f"""What is the exact public ATS careers board or job posting URL for:
Company: {company_name}
Domain: {domain or 'unknown'}

We support:
- Greenhouse (e.g. boards.greenhouse.io/<slug> or api.greenhouse.io)
- Ashby (e.g. jobs.ashbyhq.com/<slug> or api.ashbyhq.com)
- Lever (e.g. jobs.lever.co/<slug>)
- Workday (e.g. <tenant>.myworkdayjobs.com/<site>)
- SmartRecruiters (e.g. careers.smartrecruiters.com/<slug>)
- Eightfold (e.g. <company>.eightfold.ai/careers)
- Workable (e.g. apply.workable.com/<slug>)
- MyNextHire (e.g. <company>.mynexthire.com)
- Uber Careers

Return a JSON object with:
- "url": the exact ATS career page or API URL (or empty string if not known)
- "ats": the name of the ATS ('Greenhouse', 'Ashby', 'Lever', 'Workday', 'SmartRecruiters', 'Eightfold', 'Workable', 'MyNextHire', 'Uber', or 'None')

Return ONLY the raw JSON object, no markdown."""
    try:
        text = pool.generate(prompt).strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        data = json.loads(text)
        url = data.get("url", "").strip()
        if url and url.startswith("http"):
            is_api, _, ats_name = ats_process_url(url)
            if is_api and ats_name != "Unknown":
                return ats_name, url
    except Exception:
        pass
    return None, None


def discover_company_ats(cfg: dict, company: dict, pool: ModelPool | None = None) -> dict | None:
    """Attempts to find and verify an ATS URL for a single company."""
    name = company.get("name", "")
    slugs = company.get("slug_hints", [])

    for slug in slugs:
        ats_name, url, count = probe_all_ats(slug)
        if url:
            return {
                "company_name": name,
                "url": url,
                "ats": ats_name,
                "jobs_count": count,
                "discovery_method": "direct_probe",
            }

    ats_name, url = gemini_ats_lookup(cfg, name, company.get("domain", ""), pool=pool)
    if url:
        return {
            "company_name": name,
            "url": url,
            "ats": ats_name,
            "jobs_count": -1,
            "discovery_method": "gemini_lookup",
        }

    return None
