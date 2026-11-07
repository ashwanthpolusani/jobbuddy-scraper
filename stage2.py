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
import hashlib
import json
import re
import time

from scraper.config  import load_config
from scraper.db      import get_db, now_utc, record_blocked_job, make_job_id
from scraper.gemini  import ModelPool, clean_llm_json
from scraper.jd_fetcher import JDFetcher, extract_core_requirements
from scraper.filters.eligibility import is_eligible
from scraper.filters.pre_filter  import normalize_title_for_dedup
from scraper.prompts import stage2_prompt as stage2_prompts


EXP_SAFE     = "SAFE"
EXP_POSSIBLE = "POSSIBLE"
EXP_BLOCKED  = "BLOCKED"


def make_role_fingerprint(company: str, title: str, jd_text: str = "") -> str:
    """Stable SHA-256 fingerprint identifying an identical role and JD across locations."""
    c = re.sub(r"[\s\-_]+", " ", str(company or "").lower()).strip()
    t = normalize_title_for_dedup(title).lower()
    text_sample = re.sub(r"\s+", " ", str(jd_text or "")[:1200].lower()).strip()
    raw = f"{c}|{t}|{text_sample}"
    return hashlib.sha256(raw.encode()).hexdigest()


def score_job(cfg: dict, jd_text: str, pool: ModelPool) -> dict | None:
    """Ask Gemini to verify experience level and extract core requirements."""
    if not jd_text:
        return None
    prompt = stage2_prompts.build(cfg, jd_text)
    try:
        text   = pool.generate(prompt)
        cleaned = clean_llm_json(text)
        result = json.loads(cleaned)
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
    max_runtime = cfg.get("runner", {}).get("stage2_max_runtime_minutes", cfg.get("runner", {}).get("max_runtime_minutes", 45)) * 60
    delete_blocked = cfg.get("experience", {}).get("delete_blocked_jobs", True)
    sleep_delay = cfg.get("runner", {}).get("sleep_between_stage2_jobs_seconds", 1)

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
        .find(query, {"_id": 1, "link": 1, "title": 1, "company_name": 1, "location": 1, "core_requirements": 1, "job_id": 1, "content": 1})
        .sort("scraped_at", 1)
        .limit(batch_size)
    )
    print(f"  {len(pending)} jobs pending Stage 2 verification (batch: {batch_size}).\n")

    if not pending:
        print("  All eligible jobs have already been verified by Stage 2.\n")
        return

    verified = blocked = skipped = deleted = processed_count = cached_verdicts_reused = 0
    role_verdict_cache: dict[str, dict] = {}
    start_time = time.time()
    stop_reason = f"Completed batch of {len(pending)} jobs"

    try:
        for i, job in enumerate(pending, 1):
            processed_count = i
            if time.time() - start_time > max_runtime:
                stop_reason = f"Hit stage2 max runtime limit ({cfg.get('runner', {}).get('stage2_max_runtime_minutes', 45)} minutes)"
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

            # Re-use content if already captured in Stage 1 to avoid redundant network / browser fetch
            cached_content = str(job.get("content") or "").strip()
            if len(cached_content) >= 200:
                print(f"  [Cache Hit] Using pre-cached JD content ({len(cached_content)} chars)")
                jd_text = cached_content
            else:
                jd_text = fetcher.fetch(link)

            if not jd_text:
                print(f"  Could not fetch JD - leaving unverified for next run.")
                db[jobs_col].update_one(
                    {"_id": doc_id},
                    {"$inc": {"stage2_retries": 1}, "$set": {
                        "last_stage2_error":    "Could not fetch JD",
                        "last_stage2_error_at": now_utc(),
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

            # Check if this role qualifies as an explicit visa sponsored foreign role
            is_visa_sponsored = False
            if "relocation or visa sponsorship" in reason.lower() or "visa sponsorship provided" in reason.lower():
                is_visa_sponsored = True

            # Role Dedup: Check in-memory verdict cache before firing Gemini
            role_fingerprint = make_role_fingerprint(company, title, jd_text)
            was_cached = False

            if role_fingerprint in role_verdict_cache:
                result = role_verdict_cache[role_fingerprint]
                was_cached = True
                cached_verdicts_reused += 1
                print(f"  [Role Dedup Cache Hit] Reusing Gemini verdict for '{title}': {result.get('experience_verdict')}")
            else:
                result = score_job(cfg, jd_text, pool)
                if result:
                    role_verdict_cache[role_fingerprint] = result

            if not result:
                print(f"  Gemini evaluation failed or rate-limited - leaving unverified for next run.")
                db[jobs_col].update_one(
                    {"_id": doc_id},
                    {"$inc": {"stage2_retries": 1}, "$set": {
                        "last_stage2_error":    "Gemini evaluation failed or rate-limited",
                        "last_stage2_error_at": now_utc(),
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
                if is_visa_sponsored:
                    update["visa_sponsored"] = True
                # Enrich job document with fetched JD content if missing or short
                if len(str(job.get("content") or "").strip()) < 200 and jd_text:
                    update["content"] = jd_text[:20000]

                db[jobs_col].update_one({"_id": doc_id}, {"$set": update})
                verified += 1

            # Only sleep when an actual API call was made to preserve speed on deduplicated batches
            if not was_cached:
                time.sleep(sleep_delay)
    finally:
        fetcher.close()

    elapsed_secs = time.time() - start_time
    usage = pool.usage_summary()
    total_gemini_calls = sum(usage.values())

    remaining_pending = db[jobs_col].count_documents({
        "link": {"$exists": True, "$ne": ""},
        "link_type": "direct_apply",
        "stage2_processed_at": {"$exists": False},
        "experience_verdict": {"$nin": ["BLOCKED", "REJECTED"]}
    })

    print(f"\n{'=' * 60}")
    print(f"  Stage 2 Execution Summary:")
    print(f"  Status / Stop Reason:       {stop_reason}")
    print(f"  Total Runtime:              {elapsed_secs:.1f}s ({(elapsed_secs / 60):.1f} mins)")
    print(f"  Jobs Processed in Batch:    {processed_count} of {len(pending)}")
    print(f"  Verified (SAFE/POSSIBLE):   {verified}")
    print(f"  Blocked & Tombstoned:       {blocked}")
    print(f"  Deleted (ineligible):       {deleted}")
    print(f"  Skipped (error/retry):      {skipped}")
    print(f"  Dedup Cache Hits Reused:    {cached_verdicts_reused}")
    print(f"  Remaining Pending in Queue: {remaining_pending}")
    print("-" * 60)
    print("  Gemini AI Telemetry:")
    print(f"  Total Gemini Calls Fired:   {total_gemini_calls}")
    for model, count in usage.items():
        print(f"    - {model:<24}: {count} calls")
    print(f"{'=' * 60}\n")

    # Record telemetry into MongoDB meta collection for frontend / monitoring visibility
    try:
        db["meta"].update_one(
            {"_id": "last_stage2_run"},
            {
                "$set": {
                    "timestamp": now_utc(),
                    "stop_reason": stop_reason,
                    "runtime_seconds": round(elapsed_secs, 1),
                    "jobs_processed": processed_count,
                    "verified": verified,
                    "blocked": blocked,
                    "deleted": deleted,
                    "skipped": skipped,
                    "cached_verdicts_reused": cached_verdicts_reused,
                    "remaining_pending": remaining_pending,
                    "gemini_calls_fired": total_gemini_calls,
                    "gemini_model_usage": usage,
                }
            },
            upsert=True
        )
    except Exception as e:
        print(f"  [!] Could not save stage2 telemetry to meta: {e}")


if __name__ == "__main__":
    main()
