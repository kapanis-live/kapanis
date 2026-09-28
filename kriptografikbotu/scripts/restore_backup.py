"""Put a daily database backup (db_backup.py) back into MongoDB.

    python scripts/restore_backup.py backups/kapanis-20260927-0330.jsonl.gz                 # dry run: counts only
    python scripts/restore_backup.py FILE --yes --db kapanis_geri                            # into an empty new database
    python scripts/restore_backup.py FILE --yes --only users,portfolios --overwrite          # replace those collections

The safe way is to restore into a new database name first, check it, then point DB_NAME/STATE_DB_NAME at it.
Without --overwrite a collection that already has documents is skipped, never mixed.
With --overwrite that collection is emptied first (its current documents are gone).
The connection string comes from STATE_MONGO_URL (environment or .env.atlas) and is never printed.
"""
import argparse
import os
import pathlib
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_env_file(path: pathlib.Path):
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    ap = argparse.ArgumentParser(description="backup file -> MongoDB")
    ap.add_argument("file")
    ap.add_argument("--yes", action="store_true", help="really write (default: dry run)")
    ap.add_argument("--db", help="target database (default STATE_DB_NAME or kapanis)")
    ap.add_argument("--only", help="comma separated collections")
    ap.add_argument("--overwrite", action="store_true", help="empty non-empty target collections first")
    args = ap.parse_args()

    load_env_file(ROOT / ".env.atlas")
    sys.path.insert(0, str(ROOT))
    import db_backup  # noqa: E402

    path = pathlib.Path(args.file)
    if path.name.endswith(".enc"):  # the encrypted copy from Telegram: needs BACKUP_PASSWORD
        if not os.getenv("BACKUP_PASSWORD"):
            print("Şifreli yedek: BACKUP_PASSWORD ortam değişkenini ayarla.")
            return 2
        path = db_backup.decrypt(path, os.environ["BACKUP_PASSWORD"])
        print(f"Şifre çözüldü: {path}")
    args.file = str(path)
    only = {c.strip() for c in args.only.split(",")} if args.only else None
    docs: dict[str, list] = defaultdict(list)
    for coll, doc in db_backup.read(pathlib.Path(args.file)):
        if only is None or coll in only:
            docs[coll].append(doc)
    print(f"Yedek: {args.file}")
    for c, rows in sorted(docs.items()):
        print(f"  {c}: {len(rows)} belge")
    if not args.yes:
        print("\nDeneme çalıştırması: hiçbir şey yazılmadı. Yazmak için --yes ekle.")
        return 0

    url = os.getenv("STATE_MONGO_URL")
    if not url:
        print("STATE_MONGO_URL yok. .env.atlas dosyasına ya da ortam değişkenine yaz.")
        return 2
    from pymongo import MongoClient

    target = args.db or os.getenv("STATE_DB_NAME") or "kapanis"
    db = MongoClient(url, serverSelectionTimeoutMS=15000)[target]
    print(f"\nHedef veritabanı: {target}")
    for c, rows in sorted(docs.items()):
        existing = db[c].estimated_document_count()
        if existing and not args.overwrite:
            print(f"  {c}: atlandı ({existing} belge zaten var; --overwrite ile değiştirilir)")
            continue
        if existing:
            db[c].delete_many({})
        if rows:
            db[c].insert_many(rows, ordered=False)
        print(f"  {c}: {len(rows)} belge yazıldı")
    print("Not: indeksler web servisi açılınca kendi kendine yeniden oluşturulur.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
