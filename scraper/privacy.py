"""
scraper/privacy.py - Centralized privacy and zero-leakage logging helpers.
Ensures public CI environments (like GitHub Actions) never expose proprietary
target URLs, company names, ATS slugs, or direct job links in stdout, while
preserving complete diagnostic readability during local developer runs.
"""
import os
import re

# Detect if running in a public CI runner (GitHub Actions, etc.)
IS_CI = os.getenv("GITHUB_ACTIONS") == "true" or os.getenv("CI") == "true"


def register_ci_masks(urls: list[str]) -> None:
    """
    Registers dynamic target URLs with the GitHub Actions runner secret engine.
    Any accidental print of these strings anywhere in runner logs will be
    automatically redacted to '***' by GitHub Actions.
    """
    if not IS_CI:
        return
    for u in urls:
        raw_u = str(u or "").strip()
        if raw_u and len(raw_u) > 8:
            # GitHub Actions workflow command to mask a value
            print(f"::add-mask::{raw_u}", flush=True)


def format_site_header(index: int, total: int, company_name: str, ats_name: str = "") -> str:
    """
    Formats the site processing header.
    In CI: Anonymized Site ID with ATS vendor ('[014/296] Site #014 [SmartRecruiters]').
    Locally: Full Company Name ('[014/296] Swiggy (SmartRecruiters)').
    """
    if IS_CI:
        ats_badge = f" [{ats_name}]" if ats_name and ats_name != "Unknown" else ""
        return f"\n[{index:03d}/{total:03d}] Site #{index:03d}{ats_badge}"
    else:
        ats_badge = f" ({ats_name})" if ats_name else ""
        return f"\n[{index:03d}/{total:03d}] {company_name}{ats_badge}"


def format_role_header(index: int, total: int, title: str, company: str, category: str = "", location: str = "") -> str:
    """
    Formats the Stage 2 role verification header.
    In CI: Anonymized Role ID with domain category ('[001/020] Role #001 (software_engineering)').
    Locally: Full title and company ('[001/020] Junior SDE @ Google (Bengaluru)').
    """
    if IS_CI:
        cat_badge = f" ({category})" if category else ""
        return f"[{index:03d}/{total:03d}] Role #{index:03d}{cat_badge}"
    else:
        loc_badge = f" ({location})" if location else ""
        return f"[{index:03d}/{total:03d}] {title} @ {company}{loc_badge}"


def format_role_deletion(index: int, total: int, title: str, reason: str, location: str = "") -> str:
    """
    Formats Stage 2 ineligible deletion log.
    In CI: Anonymized role deletion with rejection reason.
    Locally: Full title and location.
    """
    if IS_CI:
        return f"[{index:03d}/{total:03d}] [Deleted] Role #{index:03d} -> {reason}"
    else:
        loc_badge = f" ({location})" if location else ""
        return f"[{index:03d}/{total:03d}] [Deleted] Ineligible: {title}{loc_badge} -> {reason}"


def should_display_raw_links() -> bool:
    """Returns True if raw career/job links can be displayed in console (Local runs only)."""
    return not IS_CI
