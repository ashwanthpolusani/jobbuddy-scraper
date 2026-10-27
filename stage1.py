"""
stage1.py - Entry point for the Stage 1 scraper.
Queries ATS APIs with high-speed pure Python parsers ($0 AI cost).
Automatically falls back to Gemini AI extraction for unsupported / custom career pages.
Skips previously blocked jobs in 1 batch query via tombstone memory.
Applies fast parametric pre-filters, classifies categories, and upserts eligible jobs.
"""
import sys
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import argparse
import json
import os
import time
import urllib.parse

from scraper.config import load_config
from scraper.db     import (
    create_indexes, get_target_urls, now_utc,
    record_site_stats, slug_to_company, upsert_jobs,
    get_blocked_job_ids, make_job_id,
)
from scraper.ats             import process_url as ats_process_url
from scraper.filters.pre_filter  import pre_filter_jobs
from scraper.filters.eligibility import is_eligible
from scraper.filters.classifier  import normalize_job_classification
from scraper.jd_fetcher import JDFetcher
from scraper.gemini     import ModelPool
from scraper.prompts    import stage1_prompt as stage1_prompts


def extract_jobs_with_ai(cfg: dict, pool: ModelPool, fetcher: JDFetcher, url: str, company_name: str) -> list[dict]:
    """
    Intelligent fallback for custom / unsupported ATS career pages.
    Fetches raw career page HTML/text and asks Gemini (stage1_prompt) to extract structured job listings.
    """
    print(f"  [*] Attempting Gemini AI extraction fallback on career page...")
    raw_text = fetcher.fetch(url)
    if not raw_text or len(raw_text.strip()) < 100:
        print(f"  [!] Could not fetch readable content from career page.")
        return []

    # Limit text to 12,000 characters to ensure fast response well within token limits
    prompt = stage1_prompts.build(cfg, raw_text[:12000])
    try:
        resp_text = pool.generate(prompt)
        data = json.loads(resp_text)
        if isinstance(data, list):
            jobs = []
            for item in data:
                if isinstance(item, dict) and item.get("title"):
                    if item.get("error_type"):
                        continue
                    jobs.append({
                        "title": item.get("title", ""),
                        "company_name": item.get("company_name", company_name),
                        "location": item.get("location", ""),
                        "core_requirements": item.get("core_requirements", ""),
                        "link": item.get("link", url),
                        "link_type": item.get("link_type", "direct_apply"),
                        "category": item.get("category", "software_engineering"),
                        "experience_verdict": item.get("experience_verdict", "POSSIBLE"),
                    })
            print(f"  -> Gemini AI extracted {len(jobs)} candidate listings.")
            return jobs
    except Exception as e:
        print(f"  [!] Stage 1 Gemini extraction error: {e}")
    return []


def process_site_jobs(cfg: dict, site_jobs: list[dict], url: str, company_name: str) -> list[dict]:
    """
    Pure Python extraction and classification.
    Runs in microseconds per job with cached regex patterns.
    """
    eligible = []
    now = now_utc()
    for j in site_jobs:
        job = dict(j)
        job["source_url"] = url
        job["scraped_at"] = now
        if not job.get("company_name"):
            job["company_name"] = company_name

        normalize_job_classification(cfg, job)
        job.setdefault("experience_verdict", "POSSIBLE")
        job.setdefault("core_requirements", job.get("content", "")[:500])
        job.setdefault("location", "")

        # Resolve relative links
        if job.get("link") and not job["link"].startswith("http"):
            job["link"] = urllib.parse.urljoin(url, job["link"])

        ok, reason = is_eligible(cfg, job)
        if ok:
            eligible.append(job)

    return eligible


def main():
    parser = argparse.ArgumentParser(description="JobBuddy - Stage 1: High-Speed ATS & Intelligent Fallback Scraper")
    parser.add_argument("--limit",  type=int, default=0, help="Limit number of sites to scrape (0 for all)")
    parser.add_argument("--config", type=str, default="", help="Path to custom config JSON file (default: scraper.config.json)")
    parser.add_argument("--preset", type=str, default="", help="Preset name from presets/ (e.g. 'india_fresher')")
    parser.add_argument("--no-ai-fallback", action="store_true", help="Disable Gemini AI fallback for custom career pages")
    args = parser.parse_args()

    print("=" * 60)
    print("  JobBuddy - Stage 1: High-Speed ATS & Intelligent Fallback")
    print("=" * 60)

    cfg = load_config(config_path=args.config or None, preset=args.preset or None)
    rcfg = cfg.get("runner", {})
    ai_cfg = cfg.get("ai_models", {})

    chunk_index  = int(os.getenv("CHUNK_INDEX",  "0"))
    total_chunks = int(os.getenv("TOTAL_CHUNKS", "1"))
    max_runtime  = rcfg.get("max_runtime_minutes", 80) * 60
    allow_ai_fallback = ai_cfg.get("enable_stage1_ai_fallback", True) and not args.no_ai_fallback
    if allow_ai_fallback and not cfg.get("_gemini_api_key"):
        print("  [!] Notice: GEMINI_API_KEY not provided. Stage 1 Gemini AI fallback disabled.")
        allow_ai_fallback = False

    create_indexes(cfg)
    url_docs  = get_target_urls(cfg, chunk_index, total_chunks)
    if args.limit > 0:
        url_docs = url_docs[:args.limit]
        print(f"  [Limit] Restricted to first {len(url_docs)} sites.")

    print(f"  URLs to process: {len(url_docs)}")
    print(f"  Engine Mode: High-Speed Pure Python ATS (Gemini AI Fallback: {'Enabled' if allow_ai_fallback else 'Disabled'})\n")

    pool = None
    fetcher = None
    if allow_ai_fallback:
        pool = ModelPool(cfg)
        fetcher = JDFetcher()

    total_saved = 0
    start_time  = time.time()

    try:
        for i, doc in enumerate(url_docs, 1):
            if time.time() - start_time > max_runtime:
                print("  [FAIL-SAFE] Approaching time limit. Shutting down gracefully...")
                break

            url = doc["url"]
            company_name = doc.get("company_name", slug_to_company(url))
            print(f"\n[{i}/{len(url_docs)}] {company_name}")

            is_api, api_jobs, ats_name = ats_process_url(url)
            fetch_start = time.time()

            # If no ATS router matched, attempt Gemini AI extraction fallback if enabled
            if not is_api:
                if allow_ai_fallback and pool and fetcher:
                    api_jobs = extract_jobs_with_ai(cfg, pool, fetcher, url, company_name)
                    ats_name = "AI Extracted"
                    if not api_jobs:
                        record_site_stats(cfg, url, False, int((time.time() - fetch_start) * 1000),
                                          [], "AI fallback found no valid listings",
                                          ats_name="AI Extracted", company_name=company_name)
                        continue
                else:
                    print(f"  [!] Unsupported URL format - no ATS router matched.")
                    record_site_stats(cfg, url, False, 0, [], "Unsupported URL format",
                                      ats_name="Unknown", company_name=company_name)
                    continue
            else:
                print(f"  [*] ATS: {ats_name} API")

            jobs_seen = len(api_jobs)

            if not api_jobs:
                print(f"  -> 0 total open roles via {ats_name}.")
                record_site_stats(cfg, url, True, 0, [], None,
                                  ats_name=ats_name, jobs_seen=0, company_name=company_name)
                continue

            # Batched Tombstone Check: filter out previously blocked jobs in 1 query
            pairs = [(make_job_id(company_name, str(j.get("title") or ""), str(j.get("link") or "")), str(j.get("link") or "")) for j in api_jobs]
            blocked_set = get_blocked_job_ids(cfg, pairs)

            unblocked_jobs = []
            skipped_tombstones = 0
            for j, (jid, _) in zip(api_jobs, pairs):
                if jid in blocked_set:
                    skipped_tombstones += 1
                else:
                    unblocked_jobs.append(j)

            if skipped_tombstones > 0:
                print(f"  -> Skipped {skipped_tombstones} previously BLOCKED jobs via 1 batch tombstone query.")

            filtered = pre_filter_jobs(cfg, unblocked_jobs)
            fetch_time = int((time.time() - fetch_start) * 1000)
            print(f"  -> Fetched {jobs_seen} jobs in {fetch_time}ms. Pre-filtered to {len(filtered)} candidates.")

            if not filtered:
                record_site_stats(cfg, url, True, fetch_time, [], None,
                                  ats_name=ats_name, jobs_seen=jobs_seen, company_name=company_name)
                continue

            # Pure Python extraction and classification (Instant, cached patterns)
            eligible_jobs = process_site_jobs(cfg, filtered, url, company_name)

            if not eligible_jobs:
                print(f"  -> 0 valid jobs passed location/track eligibility.")
                record_site_stats(cfg, url, True, fetch_time, [], None,
                                  ats_name=ats_name, jobs_seen=jobs_seen,
                                  jobs_prefiltered=len(filtered), company_name=company_name)
            else:
                saved = upsert_jobs(cfg, eligible_jobs, ats_name=ats_name)
                total_saved += saved
                print(f"  [OK] {len(eligible_jobs)} eligible, {saved} upserted to DB.")
                record_site_stats(cfg, url, True, fetch_time, eligible_jobs, None,
                                  ats_name=ats_name, jobs_seen=jobs_seen,
                                  jobs_prefiltered=len(filtered), jobs_gemini_kept=len(eligible_jobs),
                                  company_name=company_name)

            time.sleep(rcfg.get("sleep_between_sites_seconds", 1))
    finally:
        if fetcher:
            fetcher.close()

    print(f"\n{'=' * 60}")
    print(f"  Stage 1 complete in {(time.time() - start_time):.1f}s. {total_saved} jobs saved/updated.")
    if pool:
        usage = pool.usage_summary()
        usage_str = ", ".join(f"{m}: {c}" for m, c in usage.items())
        print(f"  Stage 1 AI Requests: {usage_str}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
