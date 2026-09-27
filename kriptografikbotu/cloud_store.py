"""Keep the bot's data/ folder in MongoDB when it runs in the cloud.

Heroku and Render wipe the local disk on every restart/deploy, but the bot keeps its portfolio, alarms,
decisions and settings in data/*.json. With STATE_MONGO_URL set:
  restore()  at start: files from MongoDB are written into data/ (MongoDB wins, it is the durable copy)
  sync()     every minute and at shutdown: changed data/*.json and *.jsonl files are uploaded
Logs and caches in sub-folders are not copied. Without STATE_MONGO_URL (this PC) nothing happens.
At most about a minute of changes can be lost if the process is killed without a shutdown.
"""
import hashlib
import logging
import os
from datetime import datetime, timezone

import config

log = logging.getLogger(__name__)
URL = os.getenv("STATE_MONGO_URL", "")
DB_NAME = os.getenv("STATE_DB_NAME", "kapanis")
COLLECTION = "bot_files"
MAX_BYTES = 15 * 1024 * 1024  # MongoDB documents are limited to 16 MB
_hashes: dict[str, str] = {}
_coll = None


def enabled() -> bool:
    return bool(URL)


def _collection():
    global _coll
    if _coll is None:
        from pymongo import MongoClient
        _coll = MongoClient(URL, serverSelectionTimeoutMS=15000)[DB_NAME][COLLECTION]
    return _coll


def _files():
    # atlas_yedek_*: local safety copies made by scripts/import_data_to_atlas.py, never uploaded back
    return [p for p in config.DATA_DIR.iterdir()
            if p.is_file() and p.suffix in (".json", ".jsonl") and not p.name.startswith("atlas_yedek_")]


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def restore() -> int:
    """Write every stored file into data/. Returns how many files were restored."""
    if not enabled():
        return 0
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    n = 0
    for doc in _collection().find({}, {"name": 1, "content": 1}):
        name = doc["name"]
        if "/" in name or "\\" in name or name.startswith("."):  # only plain file names, never a path
            continue
        data = doc["content"].encode("utf-8")
        (config.DATA_DIR / name).write_bytes(data)
        _hashes[name] = _digest(data)
        n += 1
    log.info("Cloud state: restored %d files from MongoDB", n)
    return n


def sync() -> int:
    """Upload the files that changed since the last sync. Returns how many were uploaded."""
    if not enabled():
        return 0
    n = 0
    for p in _files():
        data = p.read_bytes()
        if len(data) > MAX_BYTES:
            log.warning("Cloud state: %s is %d bytes, too large, not synced", p.name, len(data))
            continue
        h = _digest(data)
        if _hashes.get(p.name) == h:
            continue
        _collection().update_one({"name": p.name}, {"$set": {"name": p.name, "content": data.decode("utf-8"),
                                                             "sha256": h, "updated": datetime.now(timezone.utc)}},
                                 upsert=True)
        _hashes[p.name] = h
        n += 1
    if n:
        log.info("Cloud state: synced %d files", n)
    return n
