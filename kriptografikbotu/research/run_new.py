import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import engine, strategies
res = engine.run_all(strategies.NEW)
old = json.loads(pathlib.Path(__file__).with_name("results_v2.json").read_text(encoding="utf-8"))
old.update(res)
pathlib.Path(__file__).with_name("results_v2.json").write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")
for name, r in res.items():
    d, h = r["donemler"].get("gelistirme", {}), r["donemler"].get("kilitli_son_12_ay", {})
    print(f"{name:34s} {r['karar']:10s} dev {d.get('kural_yillik_%')}/{d.get('rastgele_%')} (%{d.get('rastgeleyi_gecen_varlik_%')}) "
          f"al-tut {d.get('al_tut_%')} | kilit {h.get('kural_yillik_%')}/{h.get('rastgele_%')} (%{h.get('rastgeleyi_gecen_varlik_%')}) al-tut {h.get('al_tut_%')}", flush=True)
