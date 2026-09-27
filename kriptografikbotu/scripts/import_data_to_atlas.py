"""Upload this PC's bot data (data/*.json, *.jsonl) to MongoDB Atlas, once, before the cloud worker starts.

    .venv\\Scripts\\python scripts\\import_data_to_atlas.py            # dry run: shows what would happen
    .venv\\Scripts\\python scripts\\import_data_to_atlas.py --yes      # upload
    .venv\\Scripts\\python scripts\\import_data_to_atlas.py --yes --overwrite   # replace newer data already in Atlas

The connection string is read from the environment or from the gitignored .env.atlas file
(STATE_MONGO_URL, STATE_DB_NAME) and is never printed. Logs are never uploaded (they can contain the
Telegram token). Before anything in Atlas is replaced, the current Atlas copy is saved to
data/atlas_yedek_<time>.json on this PC.
"""
import argparse
import json
import os
import pathlib
import sys
from datetime import datetime, timezone

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
    ap = argparse.ArgumentParser(description="data/ -> MongoDB Atlas (bot_files)")
    ap.add_argument("--yes", action="store_true", help="really upload (default: dry run)")
    ap.add_argument("--overwrite", action="store_true", help="also replace files that are newer in Atlas")
    args = ap.parse_args()

    load_env_file(ROOT / ".env.atlas")
    if not os.getenv("STATE_MONGO_URL"):
        print("STATE_MONGO_URL yok. .env.atlas dosyasına ya da ortam değişkenine yaz.")
        return 2
    sys.path.insert(0, str(ROOT))
    import cloud_store  # noqa: E402  (reads STATE_MONGO_URL at import)
    import config  # noqa: E402

    host = os.environ["STATE_MONGO_URL"].split("@")[-1].split("/")[0]
    coll = cloud_store._collection()
    coll.database.client.admin.command("ping")
    print(f"Atlas: {host} · veritabanı {cloud_store.DB_NAME} · koleksiyon {cloud_store.COLLECTION}")

    remote = {d["name"]: d for d in coll.find({}, {"name": 1, "updated": 1, "sha256": 1, "content": 1})}
    local = cloud_store._files()
    newer_remote = []
    print(f"\nBu bilgisayar ({config.DATA_DIR}): {len(local)} dosya · Atlas: {len(remote)} dosya\n")
    for p in sorted(local):
        data = p.read_bytes()
        mtime = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
        r = remote.get(p.name)
        if r is None:
            state = "yeni"
        elif r.get("sha256") == cloud_store._digest(data):
            state = "aynı"
        else:
            upd = r.get("updated")
            if upd and upd.replace(tzinfo=timezone.utc) > mtime:
                state = "Atlas'taki DAHA YENİ"
                newer_remote.append(p.name)
            else:
                state = "güncellenecek"
        too_big = " (çok büyük, atlanır)" if len(data) > cloud_store.MAX_BYTES else ""
        print(f"  {p.name:<32} {len(data) / 1024:>8.1f} KB  {state}{too_big}")
    only_remote = sorted(set(remote) - {p.name for p in local})
    if only_remote:
        print(f"\nYalnız Atlas'ta olanlar (dokunulmaz): {', '.join(only_remote)}")

    if not args.yes:
        print("\nDeneme çalıştırması: hiçbir şey yazılmadı. Yüklemek için --yes ekle.")
        return 0
    if newer_remote and not args.overwrite:
        print(f"\nDurdu: Atlas'ta daha yeni dosyalar var ({', '.join(newer_remote)}). Bulut botu çalışıyor olabilir.\n"
              "Bilgisayardaki veriyle değiştirmek istediğinden eminsen --overwrite ekle.")
        return 3

    if remote:
        backup = config.DATA_DIR / f"atlas_yedek_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        backup.write_text(json.dumps({n: d["content"] for n, d in remote.items()}, ensure_ascii=False), encoding="utf-8")
        print(f"\nAtlas'ın mevcut kopyası yedeklendi: {backup.name}")
    cloud_store._hashes.clear()
    for n, d in remote.items():  # unchanged files are skipped by sync()
        if n not in newer_remote or not args.overwrite:
            cloud_store._hashes[n] = d.get("sha256", "")
    count = cloud_store.sync()
    print(f"\n{count} dosya Atlas'a yüklendi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
