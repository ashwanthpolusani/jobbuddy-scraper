"""
scraper/filters/pre_filter.py - ATS pre-filtering engine.
Eliminates irrelevant jobs before Gemini to save quota and latency.
All keyword lists, junior/senior patterns, and salary markers are compiled
parametrically from scraper.config.json. Zero hardcoded logic.
"""
import hashlib
import re
from scraper.filters.eligibility import is_eligible


def normalize_title_for_dedup(title: str) -> str:
    """
    Normalizes a job title for clustering and deduplication by stripping
    location suffixes, parenthesis/bracket location tags, and remote tags.
    Preserves core discipline, level, and track.
    
    Examples:
      - 'Software Engineer, AI Data - Austin, TX (Remote)' -> 'Software Engineer, AI Data'
      - 'Junior Python Developer (Bangalore)' -> 'Junior Python Developer'
      - 'Data Analyst - Remote' -> 'Data Analyst'
      - 'Frontend Engineer | Remote' -> 'Frontend Engineer'
    """
    t = str(title or "").strip()
    if not t:
        return ""
    # 1. Remove bracketed/parenthetical qualifiers e.g. (Remote), (Hybrid), [US Only], (Pune)
    t = re.sub(r"\s*[\(\[][^)\]]*[\)\]]", "", t)
    # 2. Repeatedly strip trailing location or remote separators: e.g. ' - Austin, TX', ' | Remote', ' - Pune / Remote'
    pattern = re.compile(
        r"\s*[-–—|/]\s*(?:remote|hybrid|in[- ]person|onsite|wfh|india|bengaluru|bangalore|hyderabad|pune|mumbai|delhi|noida|chennai|us|usa|uk|emea|latam|[a-zA-Z\s,]+)\s*$",
        re.IGNORECASE
    )
    for _ in range(3):
        prev = t
        subbed = pattern.sub("", t).strip()
        if not subbed or subbed == prev:
            break
        t = subbed
    # 3. Collapse multiple spaces
    t = re.sub(r"\s+", " ", t).strip()
    return t or str(title or "").strip()


def deduplicate_and_consolidate_roles(cfg: dict, jobs: list[dict]) -> list[dict]:
    """
    Consolidates identical job postings across multiple locations into a single representative job.
    e.g. When a company posts the identical role across 200+ cities with the same JD:
    - Normalizes title and creates a fingerprint from (company, normalized_title, content_hash).
    - Selects the best eligible posting (preferring Indian tech hubs, then India, then Worldwide Remote).
    - Collects all locations into 'other_locations' and updates 'location_summary'.
    - Returns a deduplicated list with 1 representative job per unique position.
    """
    if not jobs:
        return []

    loc_cfg = cfg.get("locations", {})
    tech_hubs = [h.strip().lower() for h in loc_cfg.get("indian_tech_hubs", []) if h.strip()]

    def is_indian_hub(loc: str) -> bool:
        l = str(loc or "").lower()
        return any(h in l for h in tech_hubs) or "india" in l or bool(re.search(r"\bin\s*-\s*", l))

    def is_ww_remote(loc: str, title: str) -> bool:
        comb = f"{loc} {title}".lower()
        return any(w in comb for w in ["worldwide", "global", "anywhere", "work from anywhere", "remote"])

    def location_score(j: dict) -> int:
        loc = str(j.get("location") or "")
        title = str(j.get("title") or "")
        if is_indian_hub(loc):
            return 3  # Highest priority: India tech hub
        if "india" in loc.lower() or "india" in title.lower():
            return 2  # India general
        if is_ww_remote(loc, title):
            return 1  # Worldwide Remote
        return 0

    groups: dict[str, list[dict]] = {}

    for j in jobs:
        company = str(j.get("company_name", "")).strip().lower()
        title = str(j.get("title", "")).strip()
        norm_title = normalize_title_for_dedup(title).lower()

        content = str(j.get("content") or j.get("core_requirements") or "").strip().lower()
        if len(content) >= 100:
            clean_content = re.sub(r"\s+", " ", content[:1200])
            content_hash = hashlib.md5(clean_content.encode("utf-8")).hexdigest()
        else:
            content_hash = "no_content"

        group_key = f"{company}|{norm_title}|{content_hash}"
        groups.setdefault(group_key, []).append(j)

    consolidated = []
    for group_key, items in groups.items():
        if len(items) == 1:
            consolidated.append(items[0])
            continue

        # Sort items by location preference score descending
        items.sort(key=location_score, reverse=True)
        winner = dict(items[0])

        all_locations = []
        for it in items:
            l = str(it.get("location") or "").strip()
            if l and l not in all_locations:
                all_locations.append(l)

        if len(all_locations) > 1:
            winner["other_locations"] = [l for l in all_locations if l != winner.get("location")]
            winner["locations_count"] = len(all_locations)
            base_loc = winner.get("location") or "Multiple Locations"
            winner["location_summary"] = f"{base_loc} (+{len(all_locations) - 1} locations)"

        consolidated.append(winner)

    return consolidated


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

    # Hard reject junk non-job postings (talent community lead captures, ambassador programs, etc.)
    junk_posting_regex = re.compile(
        r"\b(?:join (?:our|.*?) talent community|talent community|talent network|talent pool|creator program|campus (?:crew )?ambassador|student ambassador)\b",
        re.IGNORECASE
    )

    good = []
    for j in jobs:
        title = str(j.get("title") or "").strip()
        if not title:
            continue
        t_lower = title.lower()

        # 0. Junk Lead-Capture / Ambassador Gate
        if junk_posting_regex.search(t_lower):
            continue

        content = str(j.get("content") or j.get("core_requirements") or "").lower()

        # 1. Internships Only Gate
        if only_intern and intern_regex and not intern_regex.search(t_lower):
            continue

        # 2. Experienced Candidate Gate (Exclude junior / fresher roles when candidate has >= 2 YOE)
        if min_years >= 2 and (exclude_jr or target_lvl in ("mid_senior", "senior", "lead")):
            if junior_regex and junior_regex.search(t_lower):
                continue

        # 3. Fresher Gate (Exclude senior roles when candidate has <= 1 YOE)
        if exclude_sr and max_years <= 1:
            t_normalized = re.sub(r"[\-_]+", " ", t_lower)
            if senior_regex and (senior_regex.search(t_lower) or senior_regex.search(t_normalized)):
                continue

            # Check explicit experience requirements in title (e.g. 'Experience: 4 - 8 yrs', '3+ yrs exp')
            title_exp = re.search(
                r"(?i)(?:(?:exp(?:erience)?|yoe)[\s:\-]*(\d+)(?:\s*(?:-|to)\s*(\d+))?\s*(?:yrs?|years?))|"
                r"\b(\d+)\+?\s*(?:yrs?|years?)\s*(?:exp|experience|yoe)\b",
                title
            )
            if title_exp:
                exp_num = int(title_exp.group(1) or title_exp.group(3))
                if exp_num > max_years:
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

    # Deduplicate and consolidate identical roles across multiple locations
    consolidated = deduplicate_and_consolidate_roles(cfg, good)

    # Prioritization
    if skills_regex:
        consolidated.sort(key=lambda x: 0 if skills_regex.search(x.get("title", "")) else 1)
    elif only_intern and intern_regex:
        consolidated.sort(key=lambda x: 0 if intern_regex.search(x.get("title", "")) else 1)
    elif fresher_regex and max_years <= 1:
        consolidated.sort(key=lambda x: 0 if fresher_regex.search(x.get("title", "")) else 1)

    return consolidated
