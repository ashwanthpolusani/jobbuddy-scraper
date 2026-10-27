"""
setup/push_urls.py - One-time setup script.
Reads a urls.txt file and pushes all URLs into MongoDB target_urls collection.
Run this once, then you can safely delete urls.txt from your repo.

Usage:
    python setup/push_urls.py --file scraper/urls.txt
    python setup/push_urls.py --file my_urls.txt --clear
"""
import argparse
import re
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.config import load_config
from scraper.db     import get_db, slug_to_company
from scraper.ats    import process_url as ats_process_url


def detect_ats(url: str) -> str:
    _, _, ats_name = ats_process_url(url)
    return ats_name


def parse_urls(filepath: str) -> list[str]:
    """Read URLs from a text file, skipping comments and blank lines."""
    urls = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls


def main():
    parser = argparse.ArgumentParser(description="Push URLs from a txt file to MongoDB.")
    parser.add_argument("--file",  required=True, help="Path to urls.txt file")
    parser.add_argument("--clear", action="store_true",
                        help="Clear ALL existing target_urls before inserting (use with caution!)")
    args = parser.parse_args()

    cfg = load_config()
    db  = get_db(cfg)
    col = cfg["database"]["urls_collection"]

    if args.clear:
        confirm = input(f"[!]  This will DELETE all documents in '{col}'. Type YES to confirm: ")
        if confirm.strip() != "YES":
            print("Aborted.")
            return
        db[col].delete_many({})
        print(f"  Cleared '{col}' collection.")

    urls = parse_urls(args.file)
    print(f"\n  Parsed {len(urls)} URLs from {args.file}")

    inserted = updated = skipped = 0
    for url in urls:
        ats     = detect_ats(url)
        company = slug_to_company(url)
        doc     = {"url": url, "ats": ats, "company_name": company, "enabled": True}

        existing = db[col].find_one({"url": url})
        if existing:
            db[col].update_one({"_id": existing["_id"]}, {"$set": {"enabled": True, "ats": ats}})
            updated += 1
        else:
            db[col].insert_one(doc)
            inserted += 1

    print(f"\n  [OK] Done.")
    print(f"    Inserted : {inserted}")
    print(f"    Updated  : {updated}")
    print(f"    Total    : {len(urls)}")
    print(f"\n  URLs are now in MongoDB '{col}' collection.")
    print(f"  You can safely delete {args.file} from your repo.\n")


if __name__ == "__main__":
    main()
