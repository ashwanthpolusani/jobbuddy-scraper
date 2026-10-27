"""
discover.py - CLI tool to discover ATS URLs from prompts, company names, or files,
and automatically update them into MongoDB target_urls.

Usage examples:
    # 1. Discover from a natural language prompt:
    python tools/discover.py --prompt "Top 30 AI and SaaS startups in India hiring engineers"

    # 2. Discover from comma-separated company names:
    python tools/discover.py --names "Figma, Stripe, Postman, Sarvam AI, DevRev"

    # 3. Discover from a text file:
    python tools/discover.py --file companies.txt

    # 4. Preview only without saving to DB:
    python tools/discover.py --prompt "YC W24 AI startups" --no-db
"""
import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scraper.config import load_config
from scraper.db import get_db, now_iso
from scraper.ats import process_url as ats_process_url
from scraper.gemini import ModelPool

_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


# ==============================================================================
# 1. Company Name & Slug Parsing / Generation
# ==============================================================================

def clean_slug(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")


def generate_companies_from_prompt(cfg: dict, prompt: str, count: int = 25) -> list[dict]:
    """Use Gemini to expand a user prompt into a structured list of target companies with slug hints."""
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


# ==============================================================================
# 2. ATS Probing & Verification
# ==============================================================================

def _http_get_json(url: str, timeout: int = 4):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as res:
            if res.status == 200:
                data = json.loads(res.read().decode("utf-8", errors="ignore"))
                return data
    except Exception:
        pass
    return None


def probe_greenhouse(slug: str) -> tuple[str | None, int]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    data = _http_get_json(url)
    if data and isinstance(data, dict) and "jobs" in data:
        return url, len(data.get("jobs", []))
    return None, 0


def probe_ashby(slug: str) -> tuple[str | None, int]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    data = _http_get_json(url)
    if data and isinstance(data, dict) and "jobs" in data:
        return url, len(data.get("jobs", []))
    return None, 0


def probe_lever(slug: str) -> tuple[str | None, int]:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    data = _http_get_json(url)
    if data and isinstance(data, list):
        board_url = f"https://jobs.lever.co/{slug}"
        return board_url, len(data)
    return None, 0


def probe_workable(slug: str) -> tuple[str | None, int]:
    url = f"https://apply.workable.com/api/v1/widget/accounts/{slug}"
    data = _http_get_json(url)
    if data and isinstance(data, dict) and "jobs" in data:
        return f"https://apply.workable.com/{slug}/", len(data.get("jobs", []))
    return None, 0


def probe_smartrecruiters(slug: str) -> tuple[str | None, int]:
    url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
    data = _http_get_json(url)
    if data and isinstance(data, dict) and "content" in data:
        return f"https://careers.smartrecruiters.com/{slug}", len(data.get("content", []))
    return None, 0


def probe_all_ats(slug: str) -> tuple[str | None, str | None, int]:
    """Test a single slug across Greenhouse, Ashby, Lever, Workable, SmartRecruiters."""
    gh_url, count = probe_greenhouse(slug)
    if gh_url:
        return "Greenhouse", gh_url, count

    ashby_url, count = probe_ashby(slug)
    if ashby_url:
        return "Ashby", ashby_url, count

    lever_url, count = probe_lever(slug)
    if lever_url:
        return "Lever", lever_url, count

    workable_url, count = probe_workable(slug)
    if workable_url:
        return "Workable", workable_url, count

    sr_url, count = probe_smartrecruiters(slug)
    if sr_url:
        return "SmartRecruiters", sr_url, count

    return None, None, 0


def gemini_ats_lookup(cfg: dict, company_name: str, domain: str = "", pool: ModelPool | None = None) -> tuple[str | None, str | None]:
    """Fallback: Ask Gemini for the public ATS or career URL with preserved rate limits."""
    if pool is None:
        pool = ModelPool(cfg)
    prompt = f"""What is the exact public ATS careers board or job posting URL for:
Company: {company_name}
Domain: {domain or 'unknown'}

We support:
- Greenhouse (e.g. boards.greenhouse.io/<slug> or api.greenhouse.io)
- Ashby (e.g. jobs.ashbyhq.com/<slug> or api.ashbyhq.com)
- Lever (e.g. jobs.lever.co/<slug>)
- Workday (e.g. <tenant>.myworkdayjobs.com/<site>)
- SmartRecruiters (e.g. careers.smartrecruiters.com/<slug>)
- Eightfold (e.g. <company>.eightfold.ai/careers)
- Workable (e.g. apply.workable.com/<slug>)
- MyNextHire (e.g. <company>.mynexthire.com)
- Uber Careers

Return a JSON object with:
- "url": the exact ATS career page or API URL (or empty string if not known)
- "ats": the name of the ATS ('Greenhouse', 'Ashby', 'Lever', 'Workday', 'SmartRecruiters', 'Eightfold', 'Workable', 'MyNextHire', 'Uber', or 'None')

Return ONLY the raw JSON object, no markdown."""
    try:
        text = pool.generate(prompt).strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        data = json.loads(text)
        url = data.get("url", "").strip()
        if url and url.startswith("http"):
            is_api, _, ats_name = ats_process_url(url)
            if is_api and ats_name != "Unknown":
                return ats_name, url
    except Exception:
        pass
    return None, None


def discover_company_ats(cfg: dict, company: dict, pool: ModelPool | None = None) -> dict | None:
    """Attempts to find and verify an ATS URL for a single company."""
    name = company.get("name", "")
    slugs = company.get("slug_hints", [])

    for slug in slugs:
        ats_name, url, count = probe_all_ats(slug)
        if url:
            return {
                "company_name": name,
                "url": url,
                "ats": ats_name,
                "jobs_count": count,
                "discovery_method": "direct_probe",
            }

    ats_name, url = gemini_ats_lookup(cfg, name, company.get("domain", ""), pool=pool)
    if url:
        return {
            "company_name": name,
            "url": url,
            "ats": ats_name,
            "jobs_count": -1,
            "discovery_method": "gemini_lookup",
        }

    return None


# ==============================================================================
# 3. Database Updating & File Export
# ==============================================================================

def save_discovered_to_db(cfg: dict, discovered_items: list[dict]) -> tuple[int, int]:
    """Upsert discovered URLs into MongoDB target_urls collection."""
    if not discovered_items:
        return 0, 0

    db = get_db(cfg)
    col = cfg["database"]["urls_collection"]
    inserted = updated = 0

    for item in discovered_items:
        url = item["url"]
        doc = {
            "url": url,
            "company_name": item["company_name"],
            "ats": item["ats"],
            "enabled": True,
            "discovered_at": now_iso(),
            "discovery_method": item.get("discovery_method", "unknown"),
        }
        existing = db[col].find_one({"url": url})
        if existing:
            db[col].update_one(
                {"_id": existing["_id"]},
                {"$set": {"enabled": True, "ats": item["ats"], "last_checked_at": now_iso()}},
            )
            updated += 1
        else:
            db[col].insert_one(doc)
            inserted += 1

    return inserted, updated


def export_to_file(filepath: str, discovered_items: list[dict]):
    """Export discovered URLs to a clean text file."""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("# JobBuddy Scraper - Discovered ATS URLs\n")
        f.write(f"# Total: {len(discovered_items)}\n\n")
        for item in discovered_items:
            f.write(f"# {item['company_name']} ({item['ats']})\n")
            f.write(f"{item['url']}\n\n")


# ==============================================================================
# 4. CLI Entry Point
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="JobBuddy ATS Discovery - Find career board URLs from prompts or company names."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prompt", type=str, help="Natural language prompt for target companies")
    group.add_argument("--names",  type=str, help="Comma-separated company names (e.g. 'Stripe, Figma')")
    group.add_argument("--file",   type=str, help="Path to text file containing company names/domains")

    parser.add_argument("--count",    type=int, default=25, help="Target company count when using --prompt (default: 25)")
    parser.add_argument("--output",   type=str, default="", help="Optional output text file path to save URLs")
    parser.add_argument("--no-db",    action="store_true", help="Do not push to MongoDB (preview/dry run only)")
    parser.add_argument("--config",   type=str, default="", help="Path to custom config JSON file (default: scraper.config.json)")
    parser.add_argument("--preset",   type=str, default="", help="Preset name from presets/ (e.g. 'india_fresher')")

    args = parser.parse_args()

    print("=" * 65)
    print("  JobBuddy - ATS URL Discovery Tool")
    print("=" * 65)

    cfg = load_config(config_path=args.config or None, preset=args.preset or None)

    # Step 1: Generate or load candidate companies
    if args.prompt:
        print(f"\n[Step 1/3] Asking Gemini to generate target companies...")
        print(f"  Prompt: \"{args.prompt}\"")
        companies = generate_companies_from_prompt(cfg, args.prompt, count=args.count)
    elif args.file:
        print(f"\n[Step 1/3] Loading companies from {args.file}...")
        companies = parse_companies_from_file(args.file)
    else:
        print(f"\n[Step 1/3] Parsing company names from input...")
        companies = parse_companies_from_string(args.names)

    print(f"  -> Generated/loaded {len(companies)} candidate companies.\n")
    if not companies:
        print("  [!] No companies found. Try a different prompt or check input.")
        return

    # Step 2: Probe ATS endpoints & fallback
    print(f"[Step 2/3] Probing ATS endpoints for candidate companies...")
    discovered = []
    not_found = []

    for i, comp in enumerate(companies, 1):
        name = comp["name"]
        print(f"  [{i}/{len(companies)}] Probing {name}...", end=" ", flush=True)
        res = discover_company_ats(cfg, comp)
        if res:
            discovered.append(res)
            jobs_str = f"({res['jobs_count']} active jobs)" if res['jobs_count'] >= 0 else "(router matched)"
            print(f"[OK] {res['ats']} {jobs_str}")
            print(f"       -> {res['url']}")
        else:
            not_found.append(name)
            print("[-] No supported ATS found")

    print(f"\n{'=' * 65}")
    print(f"  Discovery Summary: {len(discovered)} found, {len(not_found)} not found.")
    print(f"{'=' * 65}\n")

    if not discovered:
        print("  No valid ATS URLs discovered.")
        return

    # Step 3: Save to file and/or MongoDB
    if args.output:
        export_to_file(args.output, discovered)
        print(f"  [OK] Saved {len(discovered)} URLs to '{args.output}'.")

    if args.no_db:
        print("  [!] --no-db set. Skipped updating MongoDB.")
    else:
        print(f"[Step 3/3] Updating MongoDB 'target_urls' collection...")
        ins, upd = save_discovered_to_db(cfg, discovered)
        print(f"  [OK] MongoDB Updated: {ins} new inserted, {upd} existing updated.")
        print(f"  Total URLs now ready in MongoDB for stage1.py to scrape!\n")


if __name__ == "__main__":
    main()
