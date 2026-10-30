"""
scraper/prompts.py - Centralized AI Prompt Builders
Dynamically constructs prompts for Stage 1 candidate extraction and Stage 2 deep verification
from config sections (locations, experience, skills, categories, compensation, and hard rules).
"""


def build_stage1(cfg: dict, raw_data: str) -> str:
    """Dynamically builds Stage 1 extraction prompt from config."""
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


def build_stage2(cfg: dict, jd_text: str) -> str:
    """Dynamically builds Stage 2 deep verification prompt from config."""
    skills_cfg = cfg.get("skills", {})
    exp_cfg    = cfg.get("experience", {})
    comp_cfg   = cfg.get("compensation", {})
    hard_rules = cfg.get("hard_rejection_rules", {})

    role       = skills_cfg.get("role_title", "Software Engineer")
    min_y      = exp_cfg.get("min_years", 0)
    max_y      = exp_cfg.get("max_years", 1)
    target_lvl = str(exp_cfg.get("target_level", "fresher")).strip().lower()
    threshold  = exp_cfg.get("blocked_threshold_years", max_y)
    if threshold is None or threshold <= min_y:
        threshold = max_y + 1

    special_rules = []

    if exp_cfg.get("internships_only", False) or target_lvl == "internship":
        special_rules.append(
            "- INTERNSHIP REQUIREMENT: The candidate strictly seeks an INTERNSHIP / CO-OP / STUDENT role. "
            "If this is a permanent full-time position requiring a completed degree or prior experience -> BLOCKED."
        )

    if min_y >= 3:
        special_rules.append(
            f"- EXPERIENCED CANDIDATE RULE: The candidate has {min_y}+ years of experience. "
            f"If the posting is strictly an entry-level, fresher, or intern position (< {min_y} years) -> BLOCKED."
        )

    if hard_rules.get("reject_mandatory_foreign_language", True):
        special_rules.append(
            "- MANDATORY FOREIGN LANGUAGE RULE: If the JD requires mandatory non-English fluency "
            "(German C1, Japanese JLPT N1/N2, etc.) -> BLOCKED."
        )

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

EXPERIENCE CLAUSE DISAMBIGUATION RULES:
- "Degree OR equivalent work experience to X+ years" (e.g. "Bachelor's degree in engineering or related field, or equivalent work experience to 2+ Years"):
  * This is an IN-LIEU substitution clause. Candidates who hold the Bachelor's degree require 0 prior years of professional experience (fresh graduates ARE eligible!).
  * Do NOT classify as "BLOCKED" merely because the alternative non-degree path mentions 2+ years.
  * Assign "SAFE" (if entry-level/fresher eligible) or "POSSIBLE" (if ambiguous).
  * In "verdict_reason", explain: "Accepts Bachelor's degree for fresh graduates, or 2+ years work experience in lieu of a degree."
  * In "core_requirements", clearly state: "Bachelor's degree in engineering or related field (or 2+ years QA/tech experience in lieu of degree), [key skills]."
- "Degree AND X+ years experience" / "Requires strictly X+ years experience":
  * This is a mandatory experience requirement. If X > {threshold}, classify strictly as "BLOCKED".

1. "experience_verdict":
   - "SAFE": Posting matches candidate target experience ({min_y}-{max_y} years), OR explicitly targets interns, apprentices, trainees, new grads, campus hires, or entry-level.
   - "POSSIBLE": Experience requirement is completely unspecified or ambiguous, but role is open to freshers / junior candidates.
   - "BLOCKED": Posting strictly requires >{threshold} years of experience, or requires senior/staff/lead level, or fails special rules.{rules_str}

2. "verdict_reason": 1 sentence explaining the verdict and quoting the exact experience or compensation text.

3. "core_requirements": 1-2 factual sentences summarizing ONLY the required tech stack, languages, or skills (e.g. "Requires Python, Django, SQL, and Git."). Never include company overviews, corporate introductions, or HTML markup.

Return ONLY a valid JSON object with:
"experience_verdict", "verdict_reason", "core_requirements"
""".strip()


# Namespace wrappers for backward compatibility with stage1_prompt.build() / stage2_prompt.build()
class _PromptHandler:
    def __init__(self, fn):
        self.build = fn


stage1_prompt = _PromptHandler(build_stage1)
stage2_prompt = _PromptHandler(build_stage2)
stage1 = stage1_prompt
stage2 = stage2_prompt
