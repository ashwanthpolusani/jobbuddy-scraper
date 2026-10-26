"""
ATS Router - maps URLs to the correct ATS parser module.
"""
from scraper.ats import (
    ashby,
    eightfold,
    greenhouse,
    lever,
    mynexthire,
    smartrecruiters,
    uber,
    workable,
    workday,
)


def process_url(url: str) -> tuple[bool, list[dict], str]:
    """
    Route a URL to the correct ATS fetcher.
    Returns (is_supported, raw_jobs_list, ats_name).
    """
    if "greenhouse.io" in url:
        return greenhouse.process(url)
    if "lever.co" in url:
        return lever.process(url)
    if "ashbyhq.com" in url:
        return ashby.process(url)
    if "eightfold.ai" in url or "/api/apply/v2/jobs" in url:
        return eightfold.process(url)
    if ".mynexthire.com" in url:
        return mynexthire.process(url)
    if ".myworkdayjobs.com" in url:
        return workday.process(url)
    if "smartrecruiters.com" in url:
        return smartrecruiters.process(url)
    if "jobs.uber.com" in url or "uber.com" in url:
        return uber.process(url)
    if "workable.com" in url:
        return workable.process(url)

    return False, [], "Unknown"
