"""
discovery/generator.py - Generates target company lists via Gemini or text inputs.
"""
import json
import re
from scraper.gemini import ModelPool


def clean_slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return s


def generate_companies_from_prompt(cfg: dict, prompt: str, count: int = 25) -> list[dict]:
    """
    Use Gemini to expand a user prompt into a structured list of target companies with slug hints.
    """
    pool = ModelPool(cfg)
    gemini_prompt = f"""You are an expert tech recruiter and talent researcher.
User Request: "{prompt}"

Target Count: Approximately {count} companies.

Generate a JSON array of objects with the following fields for each matching company:
- "name": Clean company name (e.g. "Postman", "Razorpay")
- "domain": Main company website domain (e.g. "postman.com", "razorpay.com")
- "slug_hints": List of 1-3 lowercase slugs they likely use for ATS boards (e.g. ["postman", "getpostman"])
- "likely_ats": Known or likely ATS if you know it ('greenhouse', 'ashby', 'lever', 'workable', 'smartrecruiters', 'workday', 'eightfold', or 'unknown')

Guidelines:
1. Focus on companies matching the user prompt accurately.
2. Only return active, real companies.
3. Return ONLY a valid JSON array. Do not include markdown code fences (like ```json), commentary, or explanations.
"""
    try:
        text = pool.generate(gemini_prompt).strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        data = json.loads(text)
        if isinstance(data, list):
            cleaned = []
            seen = set()
            for item in data:
                if not isinstance(item, dict) or not item.get("name"):
                    continue
                name = item["name"].strip()
                if name.lower() in seen:
                    continue
                seen.add(name.lower())
                slugs = item.get("slug_hints", [])
                base_slug = clean_slug(name)
                if base_slug not in slugs:
                    slugs.append(base_slug)
                item["slug_hints"] = slugs
                cleaned.append(item)
            return cleaned
    except Exception as e:
        print(f"  [X] Error generating company list from Gemini: {e}")
    return []


def parse_companies_from_file(filepath: str) -> list[dict]:
    """Parse company names or domains from a text file (one per line)."""
    companies = []
    seen = set()
    with open(filepath, "r", encoding="utf-8-sig") as f:
        for line in f:
            name = line.strip()
            if not name or name.startswith("#"):
                continue
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            domain = name if "." in name and " " not in name else ""
            clean_n = name.split(".")[0].title() if domain else name
            slug = clean_slug(clean_n)
            companies.append({
                "name": clean_n,
                "domain": domain,
                "slug_hints": [slug],
                "likely_ats": "unknown"
            })
    return companies


def parse_companies_from_string(names_str: str) -> list[dict]:
    """Parse company names from a comma-separated string."""
    companies = []
    seen = set()
    for raw in names_str.split(","):
        name = raw.strip()
        if not name:
            continue
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        slug = clean_slug(name)
        companies.append({
            "name": name,
            "domain": "",
            "slug_hints": [slug],
            "likely_ats": "unknown"
        })
    return companies
