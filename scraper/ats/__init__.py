"""
scraper/ats/__init__.py - Master ATS Router and Adapter Registry.
Maps career page URLs to standardized ATS adapters. Fully extensible.
"""
from typing import Tuple, List, Dict, Any, Optional

from scraper.ats.base import BaseATSAdapter, ATSRegistry, RawJob
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


class GreenhouseAdapter(BaseATSAdapter):
    name = "Greenhouse"

    def can_handle(self, url: str) -> bool:
        return "greenhouse.io" in url or bool(greenhouse.extract_slug(url))

    def fetch_jobs(self, url: str, company_name: str = "") -> List[Dict[str, Any]]:
        _, jobs, _ = greenhouse.process(url)
        return jobs


class LeverAdapter(BaseATSAdapter):
    name = "Lever"

    def can_handle(self, url: str) -> bool:
        return "lever.co" in url or bool(lever.extract_slug(url))

    def fetch_jobs(self, url: str, company_name: str = "") -> List[Dict[str, Any]]:
        _, jobs, _ = lever.process(url)
        return jobs


class AshbyAdapter(BaseATSAdapter):
    name = "Ashby"

    def can_handle(self, url: str) -> bool:
        return "ashbyhq.com" in url or bool(ashby.extract_slug(url))

    def fetch_jobs(self, url: str, company_name: str = "") -> List[Dict[str, Any]]:
        _, jobs, _ = ashby.process(url)
        return jobs


class SmartRecruitersAdapter(BaseATSAdapter):
    name = "SmartRecruiters"

    def can_handle(self, url: str) -> bool:
        return "smartrecruiters.com" in url or bool(smartrecruiters.extract_token(url))

    def fetch_jobs(self, url: str, company_name: str = "") -> List[Dict[str, Any]]:
        _, jobs, _ = smartrecruiters.process(url)
        return jobs


class WorkdayAdapter(BaseATSAdapter):
    name = "Workday"

    def can_handle(self, url: str) -> bool:
        return ".myworkdayjobs.com" in url

    def fetch_jobs(self, url: str, company_name: str = "") -> List[Dict[str, Any]]:
        _, jobs, _ = workday.process(url)
        return jobs


class WorkableAdapter(BaseATSAdapter):
    name = "Workable"

    def can_handle(self, url: str) -> bool:
        return "workable.com" in url or bool(workable.extract_slug(url))

    def fetch_jobs(self, url: str, company_name: str = "") -> List[Dict[str, Any]]:
        _, jobs, _ = workable.process(url)
        return jobs


class EightfoldAdapter(BaseATSAdapter):
    name = "Eightfold"

    def can_handle(self, url: str) -> bool:
        return "eightfold.ai" in url or "/api/apply/v2/jobs" in url

    def fetch_jobs(self, url: str, company_name: str = "") -> List[Dict[str, Any]]:
        _, jobs, _ = eightfold.process(url)
        return jobs


class UberAdapter(BaseATSAdapter):
    name = "Uber"

    def can_handle(self, url: str) -> bool:
        return "jobs.uber.com" in url or "uber.com" in url

    def fetch_jobs(self, url: str, company_name: str = "") -> List[Dict[str, Any]]:
        _, jobs, _ = uber.process(url)
        return jobs


class MyNextHireAdapter(BaseATSAdapter):
    name = "MyNextHire"

    def can_handle(self, url: str) -> bool:
        return ".mynexthire.com" in url

    def fetch_jobs(self, url: str, company_name: str = "") -> List[Dict[str, Any]]:
        _, jobs, _ = mynexthire.process(url)
        return jobs


# Global Registry Instance
registry = ATSRegistry()
registry.register(GreenhouseAdapter())
registry.register(LeverAdapter())
registry.register(AshbyAdapter())
registry.register(EightfoldAdapter())
registry.register(MyNextHireAdapter())
registry.register(WorkdayAdapter())
registry.register(SmartRecruitersAdapter())
registry.register(UberAdapter())
registry.register(WorkableAdapter())


def process_url(url: str) -> Tuple[bool, List[Dict[str, Any]], str]:
    """
    Route a URL to the correct ATS fetcher via Registry.
    Returns (is_supported, raw_jobs_list, ats_name).
    """
    return registry.process_url(url)
