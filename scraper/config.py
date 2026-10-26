"""
scraper/config.py - Centralized configuration loader with schema enforcement,
multi-section support, and robust zero-crash fallbacks.
All patterns are driven parametrically from config without hardcoded logic.
"""
import copy
import json
import os
import re
from pathlib import Path
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_CONFIG = {
    "locations": {
        "primary_country": "India",
        "allowed_cities": [
            "All India"
        ],
        "indian_tech_hubs": [
            "Bengaluru", "Bangalore", "blr", "Hyderabad", "hyd", "Pune",
            "Mumbai", "bom", "Navi Mumbai", "Thane", "Gurugram", "Gurgaon",
            "Delhi", "New Delhi", "del", "Noida", "Greater Noida", "NCR",
            "Chennai", "maa", "Kolkata", "ccu", "Ahmedabad", "amd",
            "Kochi", "Cochin", "Coimbatore", "Indore", "Jaipur", "Chandigarh", "Mohali"
        ],
        "remote_rules": {
            "allow_worldwide_remote": True,
            "reject_region_locked_remote": True,
            "restricted_regions": [
                "us", "u.s.", "usa", "united states", "canada", "can", "uk", "united kingdom",
                "europe", "emea", "germany", "france", "spain", "portugal", "latin america",
                "latam", "colombia", "brazil", "peru", "mexico", "argentina", "chile",
                "costa rica", "australia", "nz", "china"
            ],
            "restricted_timezones": [
                "PST", "EST", "CST", "MST", "CET", "GMT"
            ]
        },
        "international_visa_rules": {
            "accept_foreign_roles_only_if_sponsored": True,
            "accept_visa_sponsorship": True,
            "accept_relocation_assistance": True,
            "allow_japan_tech_pending_stage2": True,
            "sponsorship_keywords": [
                "visa sponsorship",
                "sponsorship available",
                "will sponsor",
                "can sponsor",
                "relocation support",
                "relocation assistance",
                "international applicants welcome",
                "work authorization assistance"
            ]
        }
    },
    "experience": {
        "target_level": "fresher",
        "internships_only": False,
        "min_years": 0,
        "max_years": 1,
        "blocked_threshold_years": 1,
        "delete_blocked_jobs": True,
        "allow_unspecified_experience": True,
        "safe_labels": [
            "fresher", "entry-level", "entry level", "new grad",
            "graduate hire", "trainee", "associate", "campus hire",
            "0 years", "0-1 years", "no experience required"
        ],
        "internship_patterns": [
            "intern", "internship", "summer intern", "co-op", "coop",
            "apprentice", "apprenticeship", "student", "fellow", "trainee"
        ],
        "junior_title_patterns": [
            "intern", "internship", "trainee", "fresher", "entry-level",
            "entry level", "graduate", "campus hire", "associate", "junior", "0-1 years"
        ],
        "exclude_senior_roles": True,
        "exclude_junior_roles": False,
        "senior_title_patterns": [
            "senior", "staff", "principal", "lead", "manager", "director", "vp", "head",
            "architect", "level 3", "level 4", "level 5", "level iii", "level iv", "level v",
            "sr", "sr.", "iii", "iv", "sde 2", "sde-2", "sde ii", "sde-ii",
            "sde 3", "sde-3", "sde iii", "sde-iii", "engineer 3", "engineer 4", "engineer 5",
            "engineer iii", "engineer iv", "engineer v"
        ]
    },
    "skills": {
        "domain": "tech",
        "role_title": "Software Engineer / Tech Professional",
        "target_skills": [],
        "excluded_skills": [],
        "tech_keywords": [
            "software", "developer", "engineer", "engineering", "sde", "swe",
            "frontend", "front-end", "backend", "back-end", "fullstack", "full-stack",
            "data", "analyst", "ai", "ml", "devops", "cloud", "qa", "testing",
            "security", "product", "python", "java", "react", "golang", "c++"
        ],
        "non_tech_exclude_keywords": [
            "sales", "marketing", "hr", "recruiter", "talent acquisition",
            "finance", "accounting", "legal", "customer support", "call center", "telemarketing"
        ]
    },
    "categories": {
        "enabled": [
            "software_engineering",
            "data_ml",
            "devops_cloud",
            "cybersecurity",
            "product_design",
            "other"
        ],
        "detect_early_career_programs": True,
        "early_career_program_patterns": [
            "program", "cohort", "talent network", "talent community", "emerging talent",
            "university intern", "campus recruitment", "campus hiring", "fresher portal",
            "career opportunities", "entry-level careers", "early talent", "graduate program",
            "internship program", "leadership development", "rotational program", "student careers"
        ],
        "category_patterns": {
            "software_engineering": [
                "software", "developer", "engineer", "engineering", "sde", "swe", "sdet",
                "frontend", "front-end", "backend", "back-end", "fullstack", "full-stack",
                "web", "android", "ios", "mobile", "qa", "quality assurance", "test",
                "testing", "tester", "automation", "programmer", "coding", "coder", "firmware",
                "embedded", "systems engineer", "java", "python", "c++", "react", "node", "golang"
            ],
            "data_ml": [
                "data", "machine learning", "ml", "ai", "artificial intelligence", "deep learning",
                "analytics", "analyst", "data scientist", "data science", "bi analyst", "business intelligence",
                "mle", "nlp", "computer vision", "llm", "gen ai", "data engineer"
            ],
            "devops_cloud": [
                "devops", "cloud", "sre", "site reliability", "infrastructure", "platform",
                "aws", "azure", "gcp", "kubernetes", "docker", "sysadmin", "systems administrator", "network engineer"
            ],
            "cybersecurity": [
                "security", "cyber", "infosec", "information security", "soc", "vulnerability",
                "penetration", "pentest", "iam", "threat", "incident response"
            ],
            "product_design": [
                "product manager", "associate product manager", "apm", "product design", "ux designer",
                "ui designer", "ui/ux", "user experience", "user interface", "interaction design", "graphic design",
                "designer", "game design"
            ],
            "human_resources": [
                "hr", "human resources", "talent acquisition", "recruiter", "recruitment", "recruiting",
                "people operations", "people ops", "people partner", "hrbp", "talent partner", "payroll", "onboarding", "sourcing"
            ],
            "marketing_sales": [
                "marketing", "growth", "content", "social media", "seo", "sem", "brand",
                "communications", "pr", "sales", "account executive", "bdr", "sdr", "business development"
            ],
            "finance_legal": [
                "finance", "financial", "accounting", "accountant", "tax", "audit", "controller",
                "treasury", "fp&a", "banking", "legal", "compliance", "counsel"
            ],
            "operations": [
                "operations", "supply chain", "logistics", "procurement", "program manager", "project manager", "scrum master"
            ]
        }
    },
    "compensation": {
        "require_salary_disclosed": False,
        "min_annual_usd": 0,
        "min_annual_inr_lpa": 0,
        "currency_preference": "ANY",
        "salary_keywords": [
            "$", "€", "£", "₹", "inr", "usd", "eur", "gbp", "lpa", "ctc",
            "k/year", "per annum", "annually", "hourly", "per hour", "base salary", "compensation range"
        ]
    },
    "hard_rejection_rules": {
        "reject_security_clearance": True,
        "clearance_patterns": [
            "security clearance", "secret clearance", "top secret", "polygraph",
            "ts/sci", "clearance required", "dod clearance", "active secret", "active clearance"
        ],
        "reject_domestic_citizenship_only": True,
        "citizenship_patterns": [
            "must be a us citizen", "must be us citizen", "us citizens only", "us citizen required",
            "uk citizens only", "us persons only"
        ],
        "reject_explicit_no_visa_sponsorship": True,
        "no_visa_patterns": [
            "without sponsorship", "no visa sponsorship", "will not sponsor", "cannot sponsor",
            "unable to sponsor", "not able to sponsor", "permanent right to work"
        ],
        "domestic_authorization_restricted_countries": [
            "us", "u.s.", "usa", "united states", "uk", "canada"
        ],
        "reject_mandatory_foreign_language": True,
        "foreign_language_tests": [
            "jlpt", "hsk", "delf", "dalf", "goethe", "cefr"
        ],
        "foreign_languages": [
            "japanese", "german", "deutsch", "french", "mandarin", "chinese", "korean", "spanish", "italian"
        ],
        "reject_non_english_titles": True
    },
    "ai_models": {
        "provider": "gemini",
        "models": [
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite"
        ],
        "rpm_limit": 15,
        "rpd_limit": 500,
        "stage1_chunk_size": 50,
        "stage1_max_chunks_per_site": 4,
        "stage2_batch_size": 150
    },
    "database": {
        "name": "job_aggregator",
        "jobs_collection": "jobs",
        "stats_collection": "site_stats",
        "urls_collection": "target_urls",
        "blocked_collection": "blocked_hashes",
        "jobs_ttl_days": 30,
        "stats_ttl_days": 14
    },
    "runner": {
        "max_runtime_minutes": 80,
        "sleep_between_sites_seconds": 3,
        "sleep_between_stage2_jobs_seconds": 4
    }
}


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base without mutating base."""
    result = copy.deepcopy(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = copy.deepcopy(v)
    return result


def _normalize_config(raw: dict) -> dict:
    """Normalizes configuration from legacy structures or direct 9-section layout."""
    mapped = {}
    for sec in [
        "locations", "experience", "skills", "categories", "compensation",
        "hard_rejection_rules", "ai_models", "database", "runner"
    ]:
        if sec in raw and isinstance(raw[sec], dict):
            mapped[sec] = raw[sec]

    if "candidate" in raw and isinstance(raw["candidate"], dict):
        c = raw["candidate"]
        if "locations" in c and "locations" not in mapped:
            old_loc = c["locations"]
            mapped["locations"] = {
                "primary_country": old_loc.get("primary_country", "India"),
                "allowed_cities": old_loc.get("cities", ["All India"]),
                "remote_rules": {
                    "allow_worldwide_remote": old_loc.get("allow_remote", True),
                    "reject_region_locked_remote": True
                },
                "international_visa_rules": {
                    "accept_foreign_roles_only_if_sponsored": True,
                    "accept_visa_sponsorship": old_loc.get("allow_visa_sponsorship", True),
                    "accept_relocation_assistance": True,
                    "allow_japan_tech_pending_stage2": old_loc.get("allow_japan_tech_relocation", True)
                }
            }
        if "experience" in c and "experience" not in mapped:
            mapped["experience"] = {
                "min_years": c["experience"].get("min_years", 0),
                "max_years": c["experience"].get("max_years", 1),
                "blocked_threshold_years": c["experience"].get("max_years", 1)
            }
        if "skills" in c and "skills" not in mapped:
            mapped["skills"] = {
                "role_title": c.get("role_title", "Software Engineer / Tech Professional"),
                "target_skills": c["skills"].get("target", []),
                "excluded_skills": c["skills"].get("excluded", [])
            }
        if "tracks" in c and "categories" not in mapped:
            mapped["categories"] = {"enabled": c["tracks"]}

    if "advanced" in raw and isinstance(raw["advanced"], dict):
        adv = raw["advanced"]
        if "gemini" in adv and "ai_models" not in mapped:
            mapped["ai_models"] = adv["gemini"]
        if "database" in adv and "database" not in mapped:
            mapped["database"] = adv["database"]
        if "runner" in adv and "runner" not in mapped:
            mapped["runner"] = adv["runner"]
        if "hard_rejection_rules" in adv and "hard_rejection_rules" not in mapped:
            mapped["hard_rejection_rules"] = adv["hard_rejection_rules"]

    if "gemini" in raw and "ai_models" not in mapped:
        mapped["ai_models"] = raw["gemini"]

    return mapped


def load_config(config_path: str | Path | None = None, preset: str | None = None) -> dict:
    """Load scraper configuration with full safety fallbacks. Guaranteed non-crashing."""
    load_dotenv(_ROOT / ".env")

    if preset:
        preset_clean = preset if preset.endswith(".json") else f"{preset}.json"
        target_path = _ROOT / "presets" / preset_clean
        if not target_path.exists():
            avail = [p.stem for p in (_ROOT / "presets").glob("*.json")]
            raise FileNotFoundError(
                f"Preset '{preset}' not found in presets/.\nAvailable: {', '.join(avail)}"
            )
    elif config_path:
        target_path = Path(config_path)
        if not target_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {target_path}")
    else:
        target_path = _ROOT / "scraper.config.json"
        if not target_path.exists():
            target_path = None

    raw = {}
    if target_path and target_path.exists():
        try:
            with open(target_path, "r", encoding="utf-8-sig") as f:
                raw = json.load(f)
        except Exception as e:
            print(f"  [!] Warning: Error reading {target_path.name}: {e}. Using safe defaults.")

    normalized = _normalize_config(raw)
    cfg = deep_merge(DEFAULT_CONFIG, normalized)

    # Backward compatibility alias - points directly to ai_models dictionary
    cfg["gemini"] = cfg["ai_models"]

    cfg["_gemini_api_key"] = os.getenv("GEMINI_API_KEY", "").strip()
    cfg["_mongodb_uri"]    = os.getenv("MONGODB_URI", "").strip()
    cfg["_config_source"]   = str(target_path.resolve()) if target_path else "in-memory-defaults"

    if not cfg["_gemini_api_key"]:
        raise EnvironmentError("GEMINI_API_KEY is not set in .env or environment.")
    if not cfg["_mongodb_uri"]:
        raise EnvironmentError("MONGODB_URI is not set in .env or environment.")

    return cfg
