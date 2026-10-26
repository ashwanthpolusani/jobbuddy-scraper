"""
discover.py - CLI tool to discover ATS URLs from prompts, company names, or files,
and automatically update them into MongoDB target_urls.

Usage examples:
    # 1. Discover from a natural language prompt:
    python discover.py --prompt "Top 30 AI and SaaS startups in India hiring engineers"

    # 2. Discover from comma-separated company names:
    python discover.py --names "Figma, Stripe, Postman, Sarvam AI, DevRev"

    # 3. Discover from a text file:
    python discover.py --file companies.txt

    # 4. Preview only without saving to DB:
    python discover.py --prompt "YC W24 AI startups" --no-db
"""
import argparse
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from scraper.config import load_config
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.discovery.generator import (
    generate_companies_from_prompt,
    parse_companies_from_file,
    parse_companies_from_string,
)
from tools.discovery.prober import discover_company_ats
from tools.discovery.updater import save_discovered_to_db, export_to_file


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
    parser.add_argument("--preset",   type=str, default="", help="Preset name from presets/ (e.g. 'experienced_swe_india')")

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
