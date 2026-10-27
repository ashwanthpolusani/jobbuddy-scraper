"""
cli.py - Master Unified CLI for JobBuddy Scraper
Handles preset switching, URL management, ATS discovery, and pipeline execution.
Everything a user or cloner needs can be run through this single entrypoint.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

PRESET_DESCRIPTIONS = {
    "india_fresher": "DEFAULT: Indian tech fresher (0-1 YOE) roles across India tech hubs, worldwide remote, & visa sponsorship.",
    "indian_internships": "College students seeking tech internships, co-ops, summer trainee roles (0 YOE)."
}


def list_presets():
    presets_dir = ROOT / "presets"
    if not presets_dir.exists():
        print("No presets directory found.")
        return

    print("=" * 70)
    print("  JobBuddy Scraper - Available Presets")
    print("=" * 70)
    for p in sorted(presets_dir.glob("*.json")):
        name = p.stem
        desc = PRESET_DESCRIPTIONS.get(name, "Custom profile preset.")
        marker = " (DEFAULT)" if name == "india_fresher" else ""
        print(f"  * {name:<24}{marker}")
        print(f"    {desc}\n")
    print("=" * 70)
    print("To activate any preset:")
    print("  python cli.py use-preset <preset_name>")
    print("=" * 70)


def use_preset(name: str):
    presets_dir = ROOT / "presets"
    clean_name = name.removesuffix(".json")
    preset_file = presets_dir / f"{clean_name}.json"

    if not preset_file.exists():
        print(f"Error: Preset '{name}' does not exist in presets/.")
        print(f"Run 'python cli.py list-presets' to see available options.")
        sys.exit(1)

    target_config = ROOT / "scraper.config.json"
    backup_config = ROOT / "scraper.config.json.backup"

    if target_config.exists():
        shutil.copy2(target_config, backup_config)
        print(f"[Backup] Saved previous config to scraper.config.json.backup")

    shutil.copy2(preset_file, target_config)
    print(f"[Activated] Preset '{clean_name}' successfully copied to scraper.config.json!")
    desc = PRESET_DESCRIPTIONS.get(clean_name, "")
    if desc:
        print(f"Profile: {desc}")
    print("\nYou can now run:")
    print("  python cli.py run --limit 3")


def validate_config():
    cfg_path = ROOT / "scraper.config.json"
    if not cfg_path.exists():
        print(f"Error: scraper.config.json not found.")
        sys.exit(1)

    try:
        from scraper.config import load_config
        cfg = load_config(require_db=False, require_gemini=False)
        print("=" * 70)
        print("  Config Validation: [PASS]")
        print("=" * 70)
        print(f"  Role Title:      {cfg.get('skills', {}).get('role_title')}")
        print(f"  Experience:      {cfg.get('experience', {}).get('min_years')}-{cfg.get('experience', {}).get('max_years')} YOE ({cfg.get('experience', {}).get('target_level')})")
        print(f"  Primary Country: {cfg.get('locations', {}).get('primary_country')}")
        print(f"  Allowed Cities:  {', '.join(cfg.get('locations', {}).get('allowed_cities', []))}")
        print(f"  Domain:          {cfg.get('skills', {}).get('domain', 'tech')}")
        print(f"  Target Skills:   {', '.join(cfg.get('skills', {}).get('target_skills', [])[:5])}...")
        print(f"  Salary Required: {cfg.get('compensation', {}).get('require_salary_disclosed', False)}")
        print("=" * 70)
    except Exception as e:
        print(f"Config Validation Error: {e}")
        sys.exit(1)


def push_urls(filepath: str, clear: bool = False):
    script = ROOT / "tools" / "push_urls.py"
    cmd = [sys.executable, str(script), "--file", filepath]
    if clear:
        cmd.append("--clear")
    subprocess.run(cmd)


def discover_urls(prompt: str = "", names: str = "", file: str = "", count: int = 25, no_db: bool = False):
    script = ROOT / "tools" / "discover.py"
    cmd = [sys.executable, str(script)]
    if prompt:
        cmd.extend(["--prompt", prompt, "--count", str(count)])
    elif names:
        cmd.extend(["--names", names])
    elif file:
        cmd.extend(["--file", file])

    if no_db:
        cmd.append("--no-db")

    subprocess.run(cmd)


def run_pipeline(limit: int = 0, no_ai_fallback: bool = False):
    print("=" * 70)
    print("  Executing JobBuddy Scraper Pipeline")
    print("=" * 70)
    s1_cmd = [sys.executable, str(ROOT / "stage1.py")]
    if limit > 0:
        s1_cmd.extend(["--limit", str(limit)])
    if no_ai_fallback:
        s1_cmd.append("--no-ai-fallback")

    s1_res = subprocess.run(s1_cmd)
    if s1_res.returncode != 0:
        print(f"\n[ERROR] Stage 1 failed with exit code {s1_res.returncode}. Aborting Stage 2.")
        sys.exit(s1_res.returncode)

    s2_cmd = [sys.executable, str(ROOT / "stage2.py")]
    if limit > 0:
        s2_cmd.extend(["--limit", str(limit)])

    s2_res = subprocess.run(s2_cmd)
    if s2_res.returncode != 0:
        print(f"\n[ERROR] Stage 2 failed with exit code {s2_res.returncode}.")
        sys.exit(s2_res.returncode)


def main():
    parser = argparse.ArgumentParser(description="JobBuddy Scraper Master CLI")
    subparsers = parser.add_subparsers(dest="command")

    # Preset management
    subparsers.add_parser("list-presets", help="List all available candidate presets")
    use_p = subparsers.add_parser("use-preset", help="Activate a preset into scraper.config.json")
    use_p.add_argument("name", help="Name of preset (e.g. indian_internships, hr_talent_acquisition)")

    # Validation
    subparsers.add_parser("validate", help="Validate current scraper.config.json")

    # URL Management
    push_p = subparsers.add_parser("push-urls", help="Push URLs from text file into MongoDB target_urls")
    push_p.add_argument("--file", required=True, help="Path to text file containing URLs")
    push_p.add_argument("--clear", action="store_true", help="Clear existing target_urls first")

    # Discovery
    disc_p = subparsers.add_parser("discover", help="Discover ATS URLs using Gemini and web probing")
    disc_p.add_argument("--prompt", type=str, default="", help="Natural language prompt for companies")
    disc_p.add_argument("--names",  type=str, default="", help="Comma-separated company names")
    disc_p.add_argument("--file",   type=str, default="", help="Path to text file containing company names")
    disc_p.add_argument("--count",  type=int, default=25, help="Number of companies to generate")
    disc_p.add_argument("--no-db",  action="store_true", help="Dry run without saving to DB")

    # Run
    run_p = subparsers.add_parser("run", help="Run Stage 1 and Stage 2 pipeline")
    run_p.add_argument("--limit", type=int, default=0, help="Limit number of sites/jobs to process")
    run_p.add_argument("--no-ai-fallback", action="store_true", help="Disable Gemini AI fallback in Stage 1")

    args = parser.parse_args()

    if args.command == "list-presets":
        list_presets()
    elif args.command == "use-preset":
        use_preset(args.name)
    elif args.command == "validate":
        validate_config()
    elif args.command == "push-urls":
        push_urls(args.file, args.clear)
    elif args.command == "discover":
        if not (args.prompt or args.names or args.file):
            print("Error: discover requires --prompt, --names, or --file")
            sys.exit(1)
        discover_urls(args.prompt, args.names, args.file, args.count, args.no_db)
    elif args.command == "run":
        run_pipeline(args.limit, getattr(args, "no_ai_fallback", False))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
