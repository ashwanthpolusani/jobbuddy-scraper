"""
stage2.py - Entry point for Stage 2 deep verification.
Fetches unverified jobs from MongoDB, fetches the full JD using persistent JDFetcher,
verifies candidate eligibility, asks Gemini to classify experience verdict,
records BLOCKED jobs into blocked_hashes tombstones (64 bytes),
and deletes them from jobs to keep DB pure without causing infinite re-processing loops.
"""
import sys
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import argparse
import json
import time

from scraper.config  import load_config
from scraper.db      import get_db, now_utc, record_blocked_job, make_job_id
from scraper.gemini  import ModelPool
from scraper.jd_fetcher import JDFetcher, extract_core_requirements
from scraper.filters.eligibility import is_eligible
from scraper.prompts import stage2_prompt as stage2_prompts


EXP_SAFE     = "SAFE"
EXP_POSSIBLE = "POSSIBLE"
EXP_BLOCKED  = "BLOCKED"


def score_job(cfg: dict, jd_text: str, pool: ModelPool) -> dict | None:
    """Ask Gemini to verify experience level and extract core requirements."""
    if not jd_text:
        return None
    prompt = stage2_prompts.build(cfg, jd_text)
    try:
        text   = pool.generate(prompt)
        result = json.loads(text)
        if isinstance(result, dict) and "experience_verdict" in result:
            return result
    except Exception as e:
        print(f"    [Stage 2 Gemini Error] {e}")
    return None


def main():
    parser = argparse.ArgumentParser(description="JobBuddy - Stage 2: Deep Experience Verification")
    parser.add_argument("--limit",  type=int, default=0, help="Limit number of jobs to verify (0 uses batch size or all with --all)")
    parser.add_argument("--all",    action="store_true", help="Process all pending jobs in the queue without stopping at batch limit")
    parser.add_argument("--config", type=str, default="", help="Path to custom config JSON file (default: scraper.config.json)")
    parser.add_argument("--preset", type=str, default="", help="Preset name from presets/ (e.g. 'india_fresher')")
    args = parser.parse_args()

    print("=" * 60)
    print("  JobBuddy - Stage 2: Deep Experience Verification")
    print("=" * 60)

    cfg   = load_config(config_path=args.config or None, preset=args.preset or None, require_gemini=True, require_db=True)
    db    = get_db(cfg)
    pool  = ModelPool(cfg)
    fetcher = JDFetcher()
    jobs_col = cfg["database"]["jobs_collection"]
    batch_size = cfg["ai_models"].get("stage2_batch_size", 150)
    max_runtime = cfg.get("runner", {}).get("max_runtime_minutes", 80) * 60
    delete_blocked = cfg.get("experience", {}).get("delete_blocked_jobs", True)
    sleep_delay = cfg.get("runner", {}).get("sleep_between_stage2_jobs_seconds", 3)

    if getattr(args, "all", False):
        batch_size = 100000
        print(f"  [All] Processing all eligible pending jobs without batch limit.")
    elif args.limit > 0:
        batch_size = args.limit
        print(f"  [Limit] Batch size set to {batch_size}")

    query = {
        "link":               {"$exists": True, "$ne": ""},
        "link_type":          "direct_apply",
        "stage2_processed_at": {"$exists": False},
        "experience_verdict": {"$nin": ["BLOCKED", "REJECTED"]},
    }

    pending = list(
        db[jobs_col]
        .find(query, {"_id": 1, "link": 1, "title": 1, "company_name": 1, "location": 1, "core_requirements": 1, "job_id": 1})
        .sort("scraped_at", -1)
        .limit(batch_size)
    )
    print(f"  {len(pending)} jobs pending Stage 2 verification (batch: {batch_size}).\n")

    if not pending:
        print("  All eligible jobs have already been verified by Stage 2.\n")
        return

    verified = blocked = skipped = deleted = 0
    start_time = time.time()

    try:
        for i, job in enumerate(pending, 1):
            if time.time() - start_time > max_runtime:
                print("  [FAIL-SAFE] Approaching runtime limit. Shutting down gracefully...")
                break

            title   = job.get("title", "")
            company = job.get("company_name", "")
            loc     = job.get("location", "")
            link    = job.get("link", "")
            doc_id  = job["_id"]
            jid     = job.get("job_id") or make_job_id(company, title, link)

            # 1. Location & Visa Gate check
            ok, reason = is_eligible(cfg, job)
            if not ok:
                print(f"[{i}/{len(pending)}] [Deleted] Ineligible: {title} ({loc}) -> {reason}")
                record_blocked_job(cfg, jid, link, f"Ineligible location/visa: {reason}")
                db[jobs_col].delete_one({"_id": doc_id})
                deleted += 1
                continue

            print(f"[{i}/{len(pending)}] {title} @ {company} ({loc})")
            print(f"  -> {link}")

            jd_text = fetcher.fetch(link)
            if not jd_text:
                print(f"  Could not fetch JD - marking POSSIBLE to avoid repeat loop.")
                fallback_reqs = extract_core_requirements(job.get("core_requirements", ""), title=title)
                db[jobs_col].update_one(
                    {"_id": doc_id},
                    {"$set": {
                        "stage2_processed_at": now_utc(),
                        "stage2_verified": True,
                        "experience_verdict": EXP_POSSIBLE,
                        "core_requirements": fallback_reqs
                    }}
                )
                skipped += 1
                continue

            # 2. Check full JD text for hidden clearance / domestic-only / visa sponsorship
            ok, reason = is_eligible(cfg, {"title": title, "location": loc, "core_requirements": jd_text})
            if not ok:
                print(f"  [Deleted] Ineligible from JD content: {reason}")
                record_blocked_job(cfg, jid, link, f"Ineligible JD text: {reason}")
                db[jobs_col].delete_one({"_id": doc_id})
                deleted += 1
                continue

            result = score_job(cfg, jd_text, pool)
            if not result:
                print(f"  Gemini returned no valid result - marking POSSIBLE.")
                db[jobs_col].update_one(
                    {"_id": doc_id},
                    {"$set": {
                        "stage2_processed_at": now_utc(),
                        "stage2_verified": True,
                        "experience_verdict": EXP_POSSIBLE
                    }}
                )
                skipped += 1
                continue

            verdict = result.get("experience_verdict", EXP_POSSIBLE)
            reason  = result.get("verdict_reason", "")
            reqs    = result.get("core_requirements", "")

            icons = {"SAFE": "[OK]", "POSSIBLE": "[?]", "BLOCKED": "[X]"}
            print(f"  {icons.get(verdict, '?')} Verdict: {verdict} | {reason}")

            if verdict == EXP_BLOCKED:
                record_blocked_job(cfg, jid, link, f"Experience BLOCKED: {reason}")
                blocked += 1
                if delete_blocked:
                    db[jobs_col].delete_one({"_id": doc_id})
                    print(f"  [Tombstone Saved & Deleted] Job memory saved in blocked_hashes; deleted from jobs.")
                else:
                    db[jobs_col].update_one(
                        {"_id": doc_id},
                        {"$set": {
                            "experience_verdict": verdict,
                            "verdict_reason": reason,
                            "stage2_processed_at": now_utc(),
                        }}
                    )
            else:
                update = {
                    "experience_verdict": verdict,
                    "verdict_reason":     reason,
                    "stage2_verified":    True,
                    "stage2_verified_at": now_utc(),
                    "stage2_processed_at": now_utc(),
                }
                if reqs:
                    update["core_requirements"] = reqs

                db[jobs_col].update_one({"_id": doc_id}, {"$set": update})
                verified += 1

            time.sleep(sleep_delay)
    finally:
        fetcher.close()

    print(f"\n{'=' * 60}")
    print(f"  Stage 2 complete.")
    print(f"  Verified (SAFE/POSSIBLE): {verified}")
    print(f"  Blocked & Tombstoned:    {blocked}")
    print(f"  Deleted (ineligible):     {deleted}")
    print(f"  Skipped:                  {skipped}")
    usage = pool.usage_summary()
    for model, count in usage.items():
        print(f"  {model}: {count} requests")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
