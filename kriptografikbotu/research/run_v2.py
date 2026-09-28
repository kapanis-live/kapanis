"""Strategy Engine 2.0, step 1: run every candidate through the same standard. Writes results_v2.json."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import engine  # noqa: E402
import strategies  # noqa: E402

res = engine.run_all(strategies.ALL)
pathlib.Path(__file__).with_name("results_v2.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
for name, r in res.items():
    d, h = r["donemler"].get("gelistirme", {}), r["donemler"].get("kilitli_son_12_ay", {})
    print(f"{name:38s} {r['karar']:10s} yıl {r['rastgeleyi_gecen_yil']:6s} | geliştirme kural {d.get('kural_yillik_%')} "
          f"al-tut {d.get('al_tut_%')} rastgele {d.get('rastgele_%')} | kilitli kural {h.get('kural_yillik_%')} "
          f"rastgele {h.get('rastgele_%')} | işlem {r['islemler_gelistirme']}", flush=True)
