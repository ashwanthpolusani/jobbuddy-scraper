"""
scraper/db.py - Centralized MongoDB client, BSON Date TTL index management,
atomic upserts, batch tombstone memory, and site performance statistics.
All connections are thread-safe and use native BSON UTC dates for auto-cleanup.
"""
from datetime import datetime, timezone
import hashlib
import re
import threading
from pymongo import MongoClient
import certifi

_client = None
_db = None
_db_lock = threading.Lock()


def get_db(cfg: dict):
    """Thread-safe MongoDB database connection pool singleton."""
    global _client, _db
    if _db is not None:
        return _db
    with _db_lock:
        if _db is None:
            _client = MongoClient(
                cfg["_mongodb_uri"],
                serverSelectionTimeoutMS=10000,
                connectTimeoutMS=20000,
                maxIdleTimeMS=45000,
                maxPoolSize=10,
                tlsCAFile=certifi.where(),
            )
            _db = _client[cfg["database"]["name"]]
    return _db


# -- Helpers --------------------------------------------------------------------

def now_utc() -> datetime:
    """Returns native BSON datetime object required for MongoDB TTL auto-cleanup."""
    return datetime.now(timezone.utc)


def now_iso() -> str:
    """ISO format string for frontend / logging serialization."""
    return datetime.now(timezone.utc).isoformat()


def make_job_id(company: str, title: str, link: str) -> str:
    """Stable SHA-256 unique ID for deduplication."""
    clean_company = re.sub(r"[\s\-_]+", " ", str(company or "").lower()).strip()
    clean_title   = re.sub(r"[\s\-_]+", " ", str(title or "").lower()).strip()
    clean_link    = str(link or "").strip().rstrip("/")
    if clean_link and clean_link != "#":
        raw = f"{clean_company}|{clean_link}"
    else:
        raw = f"{clean_company}|{clean_title}"
    return hashlib.sha256(raw.encode()).hexdigest()


def slug_to_company(url: str) -> str:
    """Best-effort company name extracted from an ATS URL."""
    patterns = [
        r"boards(?:\-api)?(?:\.eu)?\.greenhouse\.io/(?:v1/boards/|embed/job_board\?for=)?([^/?#]+)",
        r"greenhouse\.io/(?:embed/job_board\?for=)?([^/?#]+)",
        r"lever\.co/(?:v0/postings/)?([^/?#]+)",
        r"ashbyhq\.com/(?:posting-api/job-board/)?([^/?#]+)",
        r"smartrecruiters\.com/(?:careers/|v1/companies/)?([^/?#]+)",
        r"apply\.workable\.com/([a-zA-Z0-9\-]+)",
        r"([a-zA-Z0-9\-]+)\.workable\.com",
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            slug = m.group(1).strip()
            if slug not in ("jobs", "careers", "embed", "v1", "v0", "api"):
                return slug.replace("-", " ").replace("_", " ").title()
    m = re.search(r"https://([a-zA-Z0-9\-]+)\.[^/]+myworkdayjobs\.com", url)
    if m:
        return m.group(1).replace("-", " ").replace("_", " ").title()
    m = re.search(r"https?://(?:www\.)?([a-zA-Z0-9-]+)\.", url)
    if m:
        sub = m.group(1).strip()
        if sub not in ("jobs", "careers", "boards", "apply", "api"):
            return sub.replace("-", " ").replace("_", " ").title()
    return ""


# -- Indexes --------------------------------------------------------------------


def record_scraper_metadata(cfg: dict):
    """
    Stores active scraper profile, target cities, and category layout in MongoDB 'meta' collection.
    Allows the frontend webapp to be 100% plug-and-play and dynamically render filters.
    """
    db = get_db(cfg)
    try:
        db["meta"].update_one(
            {"_id": "active_profile"},
            {
                "$set": {
                    "role_title": cfg.get("skills", {}).get("role_title", "Tech Professional"),
                    "target_level": cfg.get("experience", {}).get("target_level", "fresher"),
                    "primary_country": cfg.get("locations", {}).get("primary_country", "India"),
                    "allowed_cities": cfg.get("locations", {}).get("allowed_cities", ["All India"]),
                    "enabled_categories": cfg.get("categories", {}).get("enabled", []),
                    "allow_remote": cfg.get("locations", {}).get("remote_rules", {}).get("allow_worldwide_remote", True),
                    "accept_visa": cfg.get("locations", {}).get("international_visa_rules", {}).get("accept_visa_sponsorship", True),
                    "updated_at": now_utc(),
                }
            },
            upsert=True
        )
    except Exception as e:
        print(f"  [!] Could not write scraper metadata: {e}")


def create_indexes(cfg: dict):
    """Ensure optimal indexes exist with BSON Date TTL. Idempotent."""
    db  = get_db(cfg)
    j   = cfg["database"]["jobs_collection"]
    s   = cfg["database"]["stats_collection"]
    b   = cfg["database"].get("blocked_collection", "blocked_hashes")
    jobs_ttl  = cfg["database"]["jobs_ttl_days"]  * 86400
    stats_ttl = cfg["database"]["stats_ttl_days"] * 86400
    blocked_ttl = 90 * 86400  # 90 days memory for rejected jobs
    try:
        db[j].create_index("job_id",       unique=True, background=True)
        db[j].create_index("category",                  background=True)
        db[j].create_index("company_name",              background=True)
        db[j].create_index("ats_name",                  background=True)
        db[j].create_index("scraped_at",   expireAfterSeconds=jobs_ttl,  background=True)

        db[s].create_index("url",                        background=True)
        db[s].create_index("run_date",     expireAfterSeconds=stats_ttl, background=True)

        db[b].create_index("blocked_at",   expireAfterSeconds=blocked_ttl, background=True)
        db[b].create_index("link",                       background=True)
        record_scraper_metadata(cfg)
        print("  [OK] MongoDB indexes (with BSON Date TTL & blocked_hashes) and scraper metadata verified.")
    except Exception as e:
        print(f"  [!] Index creation warning: {e}")


# -- Blocked Tombstone Memory ---------------------------------------------------

def is_job_blocked(cfg: dict, job_id: str, link: str = "") -> bool:
    """Checks if a job was previously marked BLOCKED so we skip it immediately."""
    db = get_db(cfg)
    b_col = cfg["database"].get("blocked_collection", "blocked_hashes")
    if db[b_col].find_one({"_id": job_id}):
        return True
    if link and link != "#":
        if db[b_col].find_one({"link": link}):
            return True
    return False


def get_blocked_job_ids(cfg: dict, pairs: list[tuple[str, str]]) -> set[str]:
    """
    Batched check against blocked_hashes collection.
    Takes a list of (job_id, link) tuples and returns a set of blocked job_ids.
    Replaces N individual network queries with 1 single query.
    """
    if not pairs:
        return set()
    db = get_db(cfg)
    b_col = cfg["database"].get("blocked_collection", "blocked_hashes")

    ids = [jid for jid, _ in pairs if jid]
    links = [link for _, link in pairs if link and link != "#"]

    query_parts = []
    if ids:
        query_parts.append({"_id": {"$in": ids}})
    if links:
        query_parts.append({"link": {"$in": links}})

    if not query_parts:
        return set()

    query = {"$or": query_parts} if len(query_parts) > 1 else query_parts[0]

    try:
        blocked_docs = list(db[b_col].find(query, {"_id": 1, "link": 1}))
        blocked_ids = {doc["_id"] for doc in blocked_docs}
        blocked_links = {doc.get("link") for doc in blocked_docs if doc.get("link")}

        matched = set()
        for jid, link in pairs:
            if jid in blocked_ids or (link and link in blocked_links):
                matched.add(jid)
        return matched
    except Exception as e:
        print(f"  [!] Blocked jobs batch query warning: {e}")
        return set()


def record_blocked_job(cfg: dict, job_id: str, link: str, reason: str = ""):
    """Stores a 64-byte tombstone for a rejected job to avoid infinite daily re-evaluation."""
    db = get_db(cfg)
    b_col = cfg["database"].get("blocked_collection", "blocked_hashes")
    try:
        db[b_col].update_one(
            {"_id": job_id},
            {
                "$set": {
                    "link": link,
                    "reason": reason,
                    "blocked_at": now_utc(),
                }
            },
            upsert=True
        )
    except Exception as e:
        print(f"  [!] Could not record blocked job tombstone: {e}")


# -- Target URLs ----------------------------------------------------------------

def get_target_urls(cfg: dict, chunk_index: int = 0, total_chunks: int = 1) -> list[dict]:
    """Fetch enabled target URLs from MongoDB with modulo sharding."""
    db  = get_db(cfg)
    col = cfg["database"]["urls_collection"]
    all_urls = list(db[col].find({"enabled": True}, {"_id": 0, "url": 1, "ats": 1, "company_name": 1}))

    if total_chunks > 1:
        sharded = [u for i, u in enumerate(all_urls) if i % total_chunks == chunk_index]
        print(f"  [Matrix] Shard {chunk_index + 1}/{total_chunks}: {len(sharded)} URLs assigned.")
        return sharded

    return all_urls


# -- Upsert Jobs (Atomic) -------------------------------------------------------

def upsert_jobs(cfg: dict, jobs: list[dict], ats_name: str = "") -> int:
    """
    Atomic upsert using update_one(..., upsert=True).
    Eliminates race conditions and DuplicateKeyError across matrix shards.
    Stores native datetime in scraped_at and first_seen for TTL index support.
    """
    if not jobs:
        return 0
    db  = get_db(cfg)
    col = cfg["database"]["jobs_collection"]
    saved = 0
    now = now_utc()

    for job in jobs:
        try:
            company = job.get("company_name", "")
            title   = job.get("title", "")
            link    = str(job.get("link", "") or "").strip()
            job_id  = make_job_id(company, title, link)

            # Check tombstone memory (blocked_hashes) to prevent re-inserting rejected jobs
            if is_job_blocked(cfg, job_id, link):
                continue

            job["job_id"]   = job_id
            job["ats_name"] = ats_name
            job["scraped_at"] = now

            # Filter doc for atomic upsert
            filter_doc = {"job_id": job_id}
            set_doc = {k: v for k, v in job.items() if k != "first_seen"}
            set_on_insert = {"first_seen": now}

            db[col].update_one(
                filter_doc,
                {"$set": set_doc, "$setOnInsert": set_on_insert},
                upsert=True
            )
            saved += 1
        except Exception as e:
            print(f"  [!] Job upsert error on '{job.get('title')}': {e}")
            continue

    return saved


# -- Site Stats -----------------------------------------------------------------

def record_site_stats(
    cfg: dict,
    url: str,
    fetch_success: bool,
    fetch_time_ms: int,
    jobs: list[dict],
    error: str | None,
    ats_name: str = "ATS API",
    jobs_seen: int = 0,
    jobs_prefiltered: int = 0,
    jobs_gemini_kept: int = 0,
    company_name: str = "",
):
    """Write per-URL performance metrics to site_stats collection with BSON Date."""
    db  = get_db(cfg)
    col = cfg["database"]["stats_collection"]
    link_types: dict[str, int] = {}
    for j in jobs:
        lt = j.get("link_type", "unknown")
        link_types[lt] = link_types.get(lt, 0) + 1

    cname = company_name.strip() if company_name else slug_to_company(url)

    stat = {
        "url":                url,
        "company_name":       cname,
        "ats_name":           ats_name,
        "run_date":           now_utc(),
        "fetch_success":      fetch_success,
        "fetch_time_ms":      fetch_time_ms,
        "jobs_seen":          jobs_seen,
        "jobs_prefiltered":   jobs_prefiltered,
        "jobs_gemini_kept":   jobs_gemini_kept,
        "quality_jobs_saved": len(jobs),
        "link_types":         link_types,
        "error":              error,
    }
    try:
        db[col].insert_one(stat)
    except Exception as e:
        print(f"  [!] Could not write site_stats: {e}")
