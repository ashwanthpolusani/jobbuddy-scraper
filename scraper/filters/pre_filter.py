"""
scraper/filters/pre_filter.py - ATS pre-filtering engine.
Eliminates irrelevant jobs before Gemini to save quota and latency.
All keyword lists, junior/senior patterns, and salary markers are compiled
parametrically from scraper.config.json. Zero hardcoded logic.
"""
import re
from scraper.filters.eligibility import is_eligible


def pre_filter_jobs(cfg: dict, jobs: list[dict]) -> list[dict]:
    exp_cfg    = cfg.get("experience", {})
    skills_cfg = cfg.get("skills", {})
    comp_cfg   = cfg.get("compensation", {})
    cat_cfg    = cfg.get("categories", {})

    min_years  = exp_cfg.get("min_years", 0)
    max_years  = exp_cfg.get("max_years", 1)
    target_lvl = str(exp_cfg.get("target_level", "fresher")).strip().lower()
    exclude_sr = exp_cfg.get("exclude_senior_roles", True)
    exclude_jr = exp_cfg.get("exclude_junior_roles", False)
    only_intern = exp_cfg.get("internships_only", False) or target_lvl == "internship"

    domain     = str(skills_cfg.get("domain", "tech")).strip().lower()

    # Dynamic regex compilations from config
    tech_keywords = skills_cfg.get("tech_keywords", [])
    tech_regex = re.compile(
        r"\b(?:" + "|".join(map(re.escape, tech_keywords)) + r")\b",
        re.IGNORECASE
    ) if tech_keywords else None

    non_tech_keywords = skills_cfg.get("non_tech_exclude_keywords", [])
    non_tech_regex = re.compile(
        r"\b(?:" + "|".join(map(re.escape, non_tech_keywords)) + r")\b",
        re.IGNORECASE
    ) if non_tech_keywords else None

    safe_labels = exp_cfg.get("safe_labels", [])
    fresher_regex = re.compile(
        r"\b(?:" + "|".join(map(re.escape, safe_labels)) + r")\b",
        re.IGNORECASE
    ) if safe_labels else None

    senior_patterns = exp_cfg.get("senior_title_patterns", [])
    senior_regex = re.compile(
        r"\b(?:" + "|".join(map(re.escape, senior_patterns)) + r")\b",
        re.IGNORECASE
    ) if senior_patterns else None

    junior_patterns = exp_cfg.get("junior_title_patterns", [])
    junior_regex = re.compile(
        r"\b(?:" + "|".join(map(re.escape, junior_patterns)) + r")\b",
        re.IGNORECASE
    ) if junior_patterns else None

    intern_patterns = exp_cfg.get("internship_patterns", [])
    intern_regex = re.compile(
        r"\b(?:" + "|".join(map(re.escape, intern_patterns)) + r")\b",
        re.IGNORECASE
    ) if intern_patterns else None

    salary_keywords = comp_cfg.get("salary_keywords", [])
    salary_regex = re.compile(
        r"(?:" + "|".join(map(re.escape, salary_keywords)) + r")",
        re.IGNORECASE
    ) if salary_keywords else None

    target_skills = [s.strip() for s in skills_cfg.get("target_skills", []) if s.strip()]
    skills_regex = re.compile(
        r"\b(?:" + "|".join(map(re.escape, target_skills)) + r")\b",
        re.IGNORECASE
    ) if target_skills else None

    domain_alias = {"hr": "human_resources", "swe": "software_engineering", "ml": "data_ml", "cloud": "devops_cloud"}.get(domain, domain)
    domain_keywords = cat_cfg.get("category_patterns", {}).get(domain_alias, cat_cfg.get("category_patterns", {}).get(domain, []))
    domain_regex = re.compile(
        r"\b(?:" + "|".join(map(re.escape, domain_keywords)) + r")\b",
        re.IGNORECASE
    ) if domain_keywords else None

    good = []
    for j in jobs:
        title = str(j.get("title") or "").strip()
        if not title:
            continue
        t_lower = title.lower()
        content = str(j.get("content") or j.get("core_requirements") or "").lower()

        # 1. Internships Only Gate
        if only_intern and intern_regex and not intern_regex.search(t_lower):
            continue

        # 2. Experienced Candidate Gate (Exclude junior / fresher roles when candidate has >= 2 YOE)
        if min_years >= 2 and (exclude_jr or target_lvl in ("mid_senior", "senior", "lead")):
            if junior_regex and junior_regex.search(t_lower):
                continue

        # 3. Fresher Gate (Exclude senior roles when candidate has <= 1 YOE)
        if exclude_sr and max_years <= 1 and senior_regex and senior_regex.search(t_lower):
            continue

        # 4. Domain & Skills Gate
        if domain != "tech" and domain not in ("all", "any"):
            # Check domain-specific keywords or user target skills
            matches_domain = bool(domain_regex.search(t_lower)) if domain_regex else False
            matches_skills = bool(skills_regex.search(t_lower)) if skills_regex else False
            if not matches_domain and not matches_skills:
                continue
            # Also respect non_tech_exclude_keywords (which for HR candidate excludes software engineers)
            if non_tech_regex and non_tech_regex.search(t_lower) and not matches_skills:
                continue
        elif domain == "tech":
            is_tech = bool(tech_regex.search(t_lower)) if tech_regex else True
            if skills_regex and skills_regex.search(t_lower):
                is_tech = True
            if non_tech_regex and non_tech_regex.search(t_lower) and not is_tech:
                continue
        elif domain in ("all", "any"):
            pass

        # 5. Salary Disclosure Gate
        if comp_cfg.get("require_salary_disclosed", False):
            combined_text = f"{title} {content}"
            if len(content) > 50 and salary_regex and not salary_regex.search(combined_text):
                continue

        # 6. Location eligibility pre-check
        loc = str(j.get("location") or "").strip()
        if loc:
            check = dict(j)
            if not check.get("core_requirements") and check.get("content"):
                check["core_requirements"] = check["content"][:2500]
            ok, _ = is_eligible(cfg, check)
            if not ok:
                continue

        good.append(j)

    # Prioritization
    if skills_regex:
        good.sort(key=lambda x: 0 if skills_regex.search(x.get("title", "")) else 1)
    elif only_intern and intern_regex:
        good.sort(key=lambda x: 0 if intern_regex.search(x.get("title", "")) else 1)
    elif fresher_regex and max_years <= 1:
        good.sort(key=lambda x: 0 if fresher_regex.search(x.get("title", "")) else 1)

    return good
