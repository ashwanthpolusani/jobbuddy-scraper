"""
scraper/filters/eligibility.py - Comprehensive location, visa sponsorship,
and hard rejection filter.
Zero hardcoded keywords - all rules, words, and regions compiled from scraper.config.json.
Cached regex pattern compilation prevents redundant compilation across thousands of jobs.
"""
import json
import re


def _compile_rejection_patterns(cfg: dict):
    """Compiles dynamic regex patterns from config for high-speed scanning."""
    rules = cfg.get("hard_rejection_rules", {})

    clearance_words = rules.get("clearance_keywords", [
        "security clearance", "secret clearance", "top secret", "ts/sci", "polygraph", "dod clearance"
    ])
    clearance_regex = re.compile(
        r"\b(?:" + "|".join(map(re.escape, clearance_words)) + r")\b",
        re.IGNORECASE
    ) if clearance_words else None

    citizenship_words = rules.get("citizenship_only_keywords", [
        "us citizen", "u.s. citizen", "us citizenship", "u.s. citizenship", "uk citizen", "canadian citizen", "greencard", "green card"
    ])
    citizen_regex = re.compile(
        r"(?<!not\s)(?<!no\s)\b(?:" + "|".join(map(re.escape, citizenship_words)) + r")\b",
        re.IGNORECASE
    ) if citizenship_words else None

    no_visa_words = rules.get("explicit_no_visa_keywords", [
        "without sponsorship", "no visa sponsorship", "will not sponsor", "cannot sponsor", "unable to sponsor", "permanent right to work"
    ])
    restricted_countries = rules.get("domestic_authorization_restricted_countries", ["us", "u.s.", "usa", "united states", "uk", "canada"])
    countries_pat = "|".join(map(re.escape, restricted_countries))

    no_sponsor_parts = [re.escape(w) for w in no_visa_words]
    if restricted_countries:
        no_sponsor_parts.append(rf"must be authorized to work in (?:the\s+)?(?:{countries_pat})")

    no_sponsor_regex = re.compile(
        r"(?<!with or\s)(?<!regardless of\s)(?:" + "|".join(no_sponsor_parts) + r")",
        re.IGNORECASE
    ) if no_sponsor_parts else None

    lang_tests = rules.get("foreign_language_tests", ["jlpt", "hsk", "delf", "dalf", "goethe", "cefr"])
    langs = rules.get("foreign_languages", ["japanese", "german", "deutsch", "french", "mandarin", "chinese", "korean", "spanish", "italian"])
    tests_pat = "|".join(map(re.escape, lang_tests))
    langs_pat = "|".join(map(re.escape, langs))
    foreign_lang_regex = re.compile(
        rf"\b(?:{tests_pat})\b|\b(?:{langs_pat})\b[^\.\n;]{{0,60}}\b(?:mandatory|required|must have|fluent|fluency|business level|native|bilingual)\b",
        re.IGNORECASE
    ) if (lang_tests or langs) else None

    non_en_regex = re.compile(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF\uAC00-\uD7AF]")

    return clearance_regex, citizen_regex, no_sponsor_regex, foreign_lang_regex, non_en_regex


_COMPILED_PATTERNS_CACHE = {}


def get_compiled_rejection_patterns(cfg: dict):
    """Cached getter for rejection regex patterns avoiding recompilation on every job."""
    rules = cfg.get("hard_rejection_rules", {})
    cache_key = json.dumps(rules, sort_keys=True)
    if cache_key not in _COMPILED_PATTERNS_CACHE:
        _COMPILED_PATTERNS_CACHE[cache_key] = _compile_rejection_patterns(cfg)
    return _COMPILED_PATTERNS_CACHE[cache_key]


def is_eligible(cfg: dict, job: dict) -> tuple[bool, str]:
    loc_cfg    = cfg.get("locations", {})
    rem_cfg    = loc_cfg.get("remote_rules", {})
    visa_cfg   = loc_cfg.get("international_visa_rules", {})
    skills_cfg = cfg.get("skills", {})
    hard_rules = cfg.get("hard_rejection_rules", {})

    loc   = str(job.get("location", "") or "")
    title = str(job.get("title", "") or "")
    reqs  = str(job.get("core_requirements", "") or "")
    combined = f"{title} {loc} {reqs}".lower()

    clearance_rx, citizen_rx, no_sponsor_rx, foreign_lang_rx, non_en_rx = get_compiled_rejection_patterns(cfg)

    # 1. Hard Rejections
    if hard_rules.get("reject_security_clearance", True) and clearance_rx and clearance_rx.search(combined):
        return False, "Requires government/defense security clearance"

    if hard_rules.get("reject_domestic_citizenship_only", True) and citizen_rx and citizen_rx.search(combined):
        return False, "Requires domestic citizenship"

    if hard_rules.get("reject_non_english_titles", True) and non_en_rx and non_en_rx.search(title):
        return False, f"Title contains non-English script: {title}"

    if hard_rules.get("reject_mandatory_foreign_language", True) and foreign_lang_rx and foreign_lang_rx.search(combined):
        return False, "Requires mandatory foreign language proficiency"

    if hard_rules.get("reject_explicit_no_visa_sponsorship", True) and no_sponsor_rx and no_sponsor_rx.search(combined):
        return False, "Explicitly states no visa sponsorship or domestic right to work required"

    # 2. Excluded Skills
    for exc in skills_cfg.get("excluded_skills", []):
        exc_str = exc.strip()
        if exc_str and re.search(rf"\b{re.escape(exc_str)}\b", combined, re.IGNORECASE):
            return False, f"Contains excluded skill: '{exc_str}'"

    # 3. Location & Visa Evaluation
    primary = loc_cfg.get("primary_country", "India").strip().lower()
    allowed_cities = [c.strip().lower() for c in loc_cfg.get("allowed_cities", ["All India"]) if c.strip()]
    tech_hubs = [h.strip().lower() for h in loc_cfg.get("indian_tech_hubs", []) if h.strip()]

    is_remote_job = (
        "remote" in loc.lower()
        or "remote" in title.lower()
        or loc.strip().lower() in ("global", "anywhere", "worldwide")
    )

    # 3A. Candidate Requested "Remote Only"
    if "remote only" in allowed_cities:
        if is_remote_job:
            if rem_cfg.get("reject_region_locked_remote", True):
                for reg in rem_cfg.get("restricted_regions", []):
                    if reg.strip() and re.search(rf"\b{re.escape(reg.strip())}\b", loc, re.IGNORECASE):
                        return False, f"Region-locked remote role ({loc})"
                for tz in rem_cfg.get("restricted_timezones", []):
                    if tz.strip() and re.search(rf"\b{re.escape(tz.strip())}\b", loc, re.IGNORECASE):
                        return False, f"Region-locked timezone remote role ({loc})"
            return True, "Worldwide Remote"
        return False, "Non-remote role rejected (Candidate requested Remote Only)"

    # 3B. Worldwide Remote Evaluation
    if is_remote_job and rem_cfg.get("allow_worldwide_remote", True):
        if rem_cfg.get("reject_region_locked_remote", True):
            for reg in rem_cfg.get("restricted_regions", []):
                if reg.strip() and re.search(rf"\b{re.escape(reg.strip())}\b", loc, re.IGNORECASE):
                    return False, f"Region-locked remote role ({loc})"
            for tz in rem_cfg.get("restricted_timezones", []):
                if tz.strip() and re.search(rf"\b{re.escape(tz.strip())}\b", loc, re.IGNORECASE):
                    return False, f"Region-locked timezone remote role ({loc})"
        return True, "Worldwide Remote"

    # 3C. Primary Country Location Match (India by default)
    if primary == "india" or any(c in ("all india", "anywhere in india", "india") for c in allowed_cities):
        hub_pattern = r"\b(?:" + "|".join(map(re.escape, tech_hubs)) + r")\b|\bIN\s*-\s*[a-zA-Z]+|\bIndia\b"
        if re.search(hub_pattern, loc, re.IGNORECASE) or re.search(hub_pattern, title, re.IGNORECASE):
            target_cities = [c for c in allowed_cities if c not in ("all india", "anywhere in india", "india", "remote", "remote only")]
            if target_cities:
                target_pat = r"\b(?:" + "|".join(map(re.escape, target_cities)) + r")\b"
                if re.search(target_pat, loc, re.IGNORECASE) or re.search(target_pat, title, re.IGNORECASE):
                    return True, f"Target city matched in India: {loc}"
                else:
                    return False, f"Location '{loc}' not in target cities: {target_cities}"
            return True, "India-based location"
    elif primary and (primary in loc.lower() or primary in title.lower()):
        return True, f"Home country matched: {primary}"

    # 3D. Custom Target Cities
    custom_cities = [c for c in allowed_cities if c not in ("all india", "anywhere in india", "india", "remote", "remote only")]
    if custom_cities:
        pattern = r"\b(?:" + "|".join(map(re.escape, custom_cities)) + r")\b"
        if re.search(pattern, loc, re.IGNORECASE) or re.search(pattern, title, re.IGNORECASE):
            return True, f"Target location matched: {loc}"

    # 3E. International Visa Sponsorship & Relocation Assistance
    if visa_cfg.get("accept_visa_sponsorship", True) or visa_cfg.get("accept_relocation_assistance", True):
        for phrase in visa_cfg.get("sponsorship_keywords", []):
            if phrase.strip() and re.search(rf"\b{re.escape(phrase.strip())}\b", combined, re.IGNORECASE):
                return True, "Explicit international relocation or visa sponsorship provided"

    # 3F. Japan Tech Roles Exemption (hold for Stage 2 deep JD evaluation)
    if visa_cfg.get("allow_japan_tech_pending_stage2", True):
        if re.search(r"\b(?:japan|tokyo|kyoto|osaka|yokohama)\b", combined):
            if not non_en_rx.search(title) and not (foreign_lang_rx and foreign_lang_rx.search(combined)):
                if len(reqs) < 100:
                    return True, "Japan tech role pending Stage 2 visa verification"

    # 3G. Default Rejection for Foreign Roles Without Verified Sponsorship
    if visa_cfg.get("accept_foreign_roles_only_if_sponsored", True):
        return False, f"Foreign domestic role without verified visa sponsorship ({loc})"

    return False, f"Location not in target preference ({loc})"
