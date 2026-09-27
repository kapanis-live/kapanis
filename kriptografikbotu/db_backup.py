"""Daily backup of the whole MongoDB database (Atlas M0 has no automatic backups).

Every collection of STATE_DB_NAME (users, portfolios, analyses, bot_files, ...) is written as
Extended JSON lines into one gzip file: BACKUP_DIR/kapanis-YYYYMMDD-HHMM.jsonl.gz. The newest
BACKUP_KEEP files are kept. Each line is {"c": collection, "d": document}. Restore with
scripts/restore_backup.py. Files are chmod 600: they hold every user's data (AI keys stay encrypted).
Only runs where STATE_MONGO_URL is set (the cloud worker).
"""
import gzip
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import cloud_store

log = logging.getLogger(__name__)
BACKUP_DIR = Path(os.getenv("BACKUP_DIR") or Path(__file__).resolve().parent / "backups")
KEEP = int(os.getenv("BACKUP_KEEP", "14"))


def enabled() -> bool:
    return cloud_store.enabled()


def run(now: datetime | None = None) -> tuple[Path, dict[str, int]]:
    """Dump every collection; returns the file and the document count per collection."""
    from bson import json_util
    from pymongo import MongoClient

    now = now or datetime.now(timezone.utc)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    final = BACKUP_DIR / f"kapanis-{now:%Y%m%d-%H%M}.jsonl.gz"
    part = final.with_name(final.name + ".part")
    counts: dict[str, int] = {}
    client = MongoClient(cloud_store.URL, serverSelectionTimeoutMS=15000)
    try:
        db = client[cloud_store.DB_NAME]
        with gzip.open(part, "wt", encoding="utf-8") as out:
            for name in sorted(db.list_collection_names()):
                n = 0
                for doc in db[name].find():
                    out.write(json_util.dumps({"c": name, "d": doc}) + "\n")
                    n += 1
                counts[name] = n
    finally:
        client.close()
    os.chmod(part, 0o600)
    part.replace(final)  # a half-written dump never looks like a finished backup
    prune()
    log.info("Database backup %s: %s", final.name, counts)
    return final, counts


def prune() -> list[Path]:
    files = sorted(BACKUP_DIR.glob("kapanis-*.jsonl.gz"))
    old = files[:-KEEP] if KEEP > 0 else []
    for f in old:
        f.unlink(missing_ok=True)
    for f in BACKUP_DIR.glob("*.part"):
        f.unlink(missing_ok=True)
    return old


def read(path: Path):
    """Yields (collection, document) from a backup file."""
    from bson import json_util

    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                row = json_util.loads(line)
                yield row["c"], row["d"]
