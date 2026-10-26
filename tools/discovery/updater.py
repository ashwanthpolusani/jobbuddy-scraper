"""
discovery/updater.py - Upserts discovered URLs into MongoDB and saves local file.
"""
from scraper.db import get_db, now_iso


def save_discovered_to_db(cfg: dict, discovered_items: list[dict]) -> tuple[int, int]:
    """
    Upsert discovered URLs into MongoDB target_urls collection.
    Returns (inserted_count, updated_count).
    """
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
