"""
scraper/prompts/stage1.py - Dynamically builds Stage 1 extraction prompt.
Parametrically constructed from locations, experience, skills, and categories sections.
"""


def build(cfg: dict, raw_data: str) -> str:
    skills_cfg = cfg.get("skills", {})
    exp_cfg    = cfg.get("experience", {})
    loc_cfg    = cfg.get("locations", {})
    cat_cfg    = cfg.get("categories", {})

    role  = skills_cfg.get("role_title", "Software Engineer")
    min_y = exp_cfg.get("min_years", 0)
    max_y = exp_cfg.get("max_years", 1)

    primary = loc_cfg.get("primary_country", "India")
    cities  = loc_cfg.get("allowed_cities", ["All India"])
    tracks  = ", ".join(cat_cfg.get("enabled", ["software_engineering", "data_ml"]))
    skills  = skills_cfg.get("target_skills", [])

    skills_clause = f"\nTarget Skills / Tech Stack: {', '.join(skills)}" if skills else ""
    locations_str = f"{primary} ({', '.join(cities)})"
    if loc_cfg.get("remote_rules", {}).get("allow_worldwide_remote", True):
        locations_str += " + Worldwide Remote"
    if loc_cfg.get("international_visa_rules", {}).get("accept_visa_sponsorship", True):
        locations_str += " + Roles with Visa Sponsorship"

    if min_y == 0 and max_y <= 1:
        exp_instruction = (
            f"TARGET CANDIDATE: Fresh Graduate / Entry-level (0-{max_y} years experience).\n"
            f"- ACCEPT: 'fresher', 'entry-level', 'new grad', 'trainee', 'associate', '0-1 years', 'no experience required', 'campus hire'.\n"
            f"- REJECT: Any role requiring {max_y + 1}+ years of experience, Senior, Staff, Principal, or Lead."
        )
    elif min_y >= 5:
        exp_instruction = (
            f"TARGET CANDIDATE: Senior / Lead / Staff ({min_y}+ years of experience).\n"
            f"- ACCEPT: Roles requiring {min_y} to {max_y} years of experience (Senior, Staff, Lead).\n"
            f"- REJECT: Entry-level, intern, trainee, or junior roles requiring < {min_y} years."
        )
    else:
        exp_instruction = (
            f"TARGET CANDIDATE: Experienced Professional ({min_y} to {max_y} years experience).\n"
            f"- ACCEPT: Mid-level roles, SDE-2, Associate, roles requiring {min_y} to {max_y} years.\n"
            f"- REJECT: Intern/trainee/0-year roles, and REJECT executive roles requiring > {max_y} years."
        )

    return f"""
You are an expert technical talent recruiter screening job postings for: {role}.
{skills_clause}

{exp_instruction}

LOCATION RULES:
- ACCEPT: {locations_str}
- REJECT: Foreign domestic roles that do NOT state visa sponsorship or international relocation.

CATEGORIES ALLOWED: {tracks}

TASK:
Extract ONLY matching job listings from the raw career board data below.
Assign:
- "experience_verdict": "SAFE" (explicitly matches {min_y}-{max_y} years), "POSSIBLE" (likely matches experience tier)
- "link_type": "direct_apply" (one specific job) or "filtered_list" (cohort/program portal)
- "category": one of: {tracks}
- "core_requirements": 1 short factual sentence listing required tech stack or skills.

Return ONLY a valid JSON array of objects with keys:
"title", "company_name", "location", "core_requirements", "link", "link_type", "category", "experience_verdict"

If no valid jobs match -> return []
If the raw data is a CAPTCHA or Cloudflare challenge -> return [{{"error_type": "site_blocked_or_invalid"}}]

RAW DATA:
{raw_data}
""".strip()
