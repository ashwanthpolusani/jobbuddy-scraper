"""
scraper/prompts/stage2.py - Dynamically builds Stage 2 deep verification prompt.
Parametrically constructed from experience, skills, compensation, and hard rejection rules sections.
Accurately serves all candidate personas.
"""


def build(cfg: dict, jd_text: str) -> str:
    skills_cfg = cfg.get("skills", {})
    exp_cfg    = cfg.get("experience", {})
    comp_cfg   = cfg.get("compensation", {})
    hard_rules = cfg.get("hard_rejection_rules", {})

    role       = skills_cfg.get("role_title", "Software Engineer")
    min_y      = exp_cfg.get("min_years", 0)
    max_y      = exp_cfg.get("max_years", 1)
    target_lvl = str(exp_cfg.get("target_level", "fresher")).strip().lower()
    threshold  = exp_cfg.get("blocked_threshold_years", max_y)
    # Self-healing safeguard: if user changed min_years but forgot blocked_threshold_years
    if threshold is None or threshold <= min_y:
        threshold = max_y + 1

    special_rules = []

    # Internship special rule
    if exp_cfg.get("internships_only", False) or target_lvl == "internship":
        special_rules.append(
            "- INTERNSHIP REQUIREMENT: The candidate strictly seeks an INTERNSHIP / CO-OP / STUDENT role. "
            "If this is a permanent full-time position requiring a completed degree or prior experience -> BLOCKED."
        )

    # Experienced candidate special rule
    if min_y >= 3:
        special_rules.append(
            f"- EXPERIENCED CANDIDATE RULE: The candidate has {min_y}+ years of experience. "
            f"If the posting is strictly an entry-level, fresher, or intern position (< {min_y} years) -> BLOCKED."
        )

    # Mandatory non-English language rule
    if hard_rules.get("reject_mandatory_foreign_language", True):
        special_rules.append(
            "- MANDATORY FOREIGN LANGUAGE RULE: If the JD requires mandatory non-English fluency "
            "(German C1, Japanese JLPT N1/N2, etc.) -> BLOCKED."
        )

    # Salary transparency rule
    if comp_cfg.get("require_salary_disclosed", False):
        min_usd = comp_cfg.get("min_annual_usd", 0)
        min_lpa = comp_cfg.get("min_annual_inr_lpa", 0)
        special_rules.append(
            f"- SALARY REQUIREMENT: The posting MUST disclose compensation. "
            f"If no salary/compensation range is mentioned, or if salary is explicitly below "
            f"(Min USD: ${min_usd:,}/year, Min INR: {min_lpa} LPA) -> BLOCKED."
        )

    rules_str = "\n".join(special_rules)
    if rules_str:
        rules_str = "\nSPECIAL VERDICT RULES:\n" + rules_str

    return f"""
You are an expert technical job screener.
Candidate Profile: {role} targeting {min_y} to {max_y} years of experience ({target_lvl}).

JOB DESCRIPTION:
{jd_text}

Evaluate this Job Description against the candidate profile:

1. "experience_verdict":
   - "SAFE": Posting matches candidate target experience ({min_y}-{max_y} years).
   - "POSSIBLE": Experience requirement is ambiguous or unspecified (candidate should apply anyway).
   - "BLOCKED": Posting strictly requires >{threshold} years of experience, or fails special rules.{rules_str}

2. "verdict_reason": 1 sentence explaining the verdict and quoting the exact experience or compensation text.

3. "core_requirements": 1-2 factual sentences summarizing ONLY the required tech stack, languages, or skills.

Return ONLY a valid JSON object with:
"experience_verdict", "verdict_reason", "core_requirements"
""".strip()
