"""
tools/cleanup_jobs_data.py - One-time migration to clean all existing jobs in MongoDB:
1. Strips all raw HTML, unescapes entities, and extracts clean bulleted requirements for core_requirements.
2. Auto-confirms explicit intern / trainee / new grad / apprentice roles from POSSIBLE to SAFE.
3. Updates MongoDB atomically and displays before/after statistics.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper.config import load_config
from scraper.db import get_db, now_utc
from scraper.jd_fetcher import extract_core_requirements

JUNIOR_TITLE_REGEX = re.compile(
    r"\b(intern|internship|trainee|apprentice|apprenticeship|co-op|new grad|campus hire|campus|fresher|entry[- ]level)\b",
    re.IGNORECASE
)

HTML_DETECTOR_REGEX = re.compile(
    r"(?:<[a-z/][^>]*>|&lt;|&gt;|&amp;|&quot;|div class|content-intro)",
    re.IGNORECASE
)

BOILERPLATE_PHRASES = [
    "who is", "about us", "about the company", "about the team",
    "founded in", "equal opportunity", "privacy policy"
]


def run_cleanup():
    print("=" * 70)
    print("  JobBuddy Scraper - MongoDB Data Cleanup & Sanitization")
    print("=" * 70)

    cfg = load_config(require_db=True, require_gemini=False)
    db = get_db(cfg)
    jobs_col = cfg["database"]["jobs_collection"]
    print(f"Connected to MongoDB '{db.name}', reading '{jobs_col}'...")

    jobs = list(db[jobs_col].find())
    total_jobs = len(jobs)
    print(f"Total jobs to inspect: {total_jobs}\n")

    cleaned_reqs_count = 0
    promoted_safe_count = 0
    total_updated_count = 0

    for i, job in enumerate(jobs, 1):
        doc_id = job["_id"]
        title = job.get("title", "")
        current_reqs = str(job.get("core_requirements") or "").strip()
        current_content = str(job.get("content") or "").strip()
        current_verdict = job.get("experience_verdict", "POSSIBLE")

        updates = {}

        # 1. Check if core_requirements needs cleanup
        needs_req_cleanup = False
        if not current_reqs:
            needs_req_cleanup = True
        elif HTML_DETECTOR_REGEX.search(current_reqs):
            needs_req_cleanup = True
        elif any(bp in current_reqs.lower() for bp in BOILERPLATE_PHRASES):
            needs_req_cleanup = True

        if needs_req_cleanup:
            # Prefer content if available, otherwise clean current_reqs
            source_text = current_content if len(current_content) > 50 else current_reqs
            new_reqs = extract_core_requirements(source_text, title=title)
            if new_reqs and new_reqs != current_reqs:
                updates["core_requirements"] = new_reqs
                cleaned_reqs_count += 1

        # 2. Check if job should be promoted to SAFE (Confirmed)
        if current_verdict == "POSSIBLE" and JUNIOR_TITLE_REGEX.search(title):
            updates["experience_verdict"] = "SAFE"
            if not job.get("verdict_reason"):
                updates["verdict_reason"] = "Role explicitly targets early-career, intern, or trainee talent."
            promoted_safe_count += 1

        if updates:
            updates["updated_at"] = now_utc()
            db[jobs_col].update_one({"_id": doc_id}, {"$set": updates})
            total_updated_count += 1

    print("\n" + "=" * 70)
    print("                    CLEANUP COMPLETE")
    print("=" * 70)
    print(f"Total Jobs Inspected:              {total_jobs}")
    print(f"Core Requirements Cleaned:         {cleaned_reqs_count}")
    print(f"Promoted to SAFE (Confirmed):       {promoted_safe_count}")
    print(f"Total Documents Modified:          {total_updated_count}")
    print("=" * 70)


if __name__ == "__main__":
    run_cleanup()

