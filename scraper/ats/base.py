"""
scraper/ats/base.py - Standardized interface and data models for ATS adapters.
Provides type safety, uniform job extraction contracts, and clean registry dispatch.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Tuple


@dataclass
class RawJob:
    """Standardized representation of a single job listing extracted from an ATS."""
    title: str
    company_name: str = ""
    location: str = ""
    link: str = ""
    content: str = ""
    link_type: str = "direct_apply"
    source_url: str = ""
    category: str = "other"
    experience_verdict: str = "POSSIBLE"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to MongoDB-compatible dictionary format."""
        d = asdict(self)
        d.pop("metadata", None)
        return d


class BaseATSAdapter(ABC):
    """Abstract Base Class that every ATS parser must implement."""

    name: str = "GenericATS"

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Determines if this adapter can process the given career page URL."""
        pass

    @abstractmethod
    def fetch_jobs(self, url: str, company_name: str = "") -> List[Dict[str, Any]]:
        """
        Fetches and returns raw job listings from the ATS.
        Returns list of standardized job dictionaries.
        """
        pass

    def process(self, url: str, company_name: str = "") -> Tuple[bool, List[Dict[str, Any]], str]:
        """
        Standard entry point for routing.
        Returns (is_supported, jobs_list, ats_name).
        """
        if not self.can_handle(url):
            return False, [], self.name
        try:
            jobs = self.fetch_jobs(url, company_name)
            return True, jobs, self.name
        except Exception as e:
            print(f"    [{self.name} Adapter Error] {e}")
            return True, [], self.name


class ATSRegistry:
    """Registry managing all ATS adapters with deterministic priority dispatch."""

    def __init__(self):
        self._adapters: List[BaseATSAdapter] = []

    def register(self, adapter: BaseATSAdapter) -> None:
        self._adapters.append(adapter)

    def find_adapter(self, url: str) -> Optional[BaseATSAdapter]:
        for adapter in self._adapters:
            if adapter.can_handle(url):
                return adapter
        return None

    def process_url(self, url: str, company_name: str = "") -> Tuple[bool, List[Dict[str, Any]], str]:
        adapter = self.find_adapter(url)
        if adapter:
            return adapter.process(url, company_name)
        return False, [], "Unknown"

