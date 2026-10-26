"""
scraper/filters/classifier.py - Normalizes link_type and category on every job.
All classification patterns and early career portal patterns are compiled dynamically
from the categories section of scraper.config.json. Zero hardcoded logic.
"""
import re


def _compile_patterns(cfg: dict):
    cat_cfg = cfg.get("categories", {})
    early_patterns = cat_cfg.get("early_career_program_patterns", [])
    portal_regex = re.compile(
        r"\b(?:" + "|".join(map(re.escape, early_patterns)) + r")\b",
        re.IGNORECASE
    ) if early_patterns else None

    category_regexes = {}
    patterns_map = cat_cfg.get("category_patterns", {})
    for category_name, keywords in patterns_map.items():
        if keywords:
            category_regexes[category_name] = re.compile(
                r"\b(?:" + "|".join(map(re.escape, keywords)) + r")\b",
                re.IGNORECASE
            )

    return portal_regex, category_regexes


def normalize_job_classification(cfg: dict, job: dict) -> dict:
    categories_cfg = cfg.get("categories", {})
    enabled_tracks = categories_cfg.get("enabled", [
        "software_engineering", "data_ml", "devops_cloud", "cybersecurity", "product_design", "other"
    ])

    title = str(job.get("title", "") or "")
    link  = str(job.get("link", "") or "")
    reqs  = str(job.get("core_requirements", "") or "")

    portal_regex, category_regexes = _compile_patterns(cfg)

    # 1. Link type detection
    if portal_regex and (portal_regex.search(title) or portal_regex.search(link)):
        job["link_type"] = "filtered_list"
    elif job.get("link_type") in ("filtered_list", "career_homepage"):
        job["link_type"] = "filtered_list"
    else:
        job["link_type"] = "direct_apply"

    # 2. Category normalization
    cat = str(job.get("category", "") or "").strip().lower()
    valid = set(enabled_tracks)

    if cat not in valid or cat == "other":
        matched = False
        for track in enabled_tracks:
            if track in category_regexes:
                rgx = category_regexes[track]
                if rgx.search(title) or rgx.search(reqs):
                    job["category"] = track
                    matched = True
                    break
        if not matched:
            job["category"] = "other"
    else:
        job["category"] = cat

    return job
