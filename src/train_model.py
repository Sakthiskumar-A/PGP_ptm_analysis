"""Retraining pipeline: clean data -> train -> check -> save a versioned model file.

Usage (from the repo root):
    python src/train_model.py                      # reads data/raw (Excel) as in the notebooks
    python src/train_model.py --out models --no-promote

A live deployment replaces step 1 with its own loader (database / historian) and passes the
DataFrame to data_prep.clean_15min(raw=..., crown_1min=...); everything after that is the same.

Output in --out:
    recommender_<trained_until>.json    the model (numbers only; load with FinalRecommender.load)
    report_<trained_until>.json         training checks
    recommender_latest.json             copy of the newest model that PASSED the checks (what the API serves)
Exit code 1 if a check fails (the latest model is then left unchanged).
"""
import argparse
import json
import shutil
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import data_prep as dp            # noqa: E402
import recommender as rc          # noqa: E402

warnings.filterwarnings("ignore")


def checks(fr: rc.FinalRecommender, d: pd.DataFrame, recent_days: int = 30) -> dict:
    """Sanity and calibration checks a new model must pass before it is served."""
    u = rc.prepare_gas_features(d[d["usable"]])
    p = fr.gas_params
    # walk-forward calibration on the most recent usable days: ~25% of days should beat the target
    days = u.index[-recent_days:]
    tgt = rc.walk_forward_gas_targets(u, days)
    coverage = float((u.loc[days, "gas_g"] <= tgt).mean())
    res = {
        "usable_days >= 200": (fr.n_days, fr.n_days >= 200),
        "draw coefficient > 0": (p["draw_t"], p["draw_t"] > 0),
        "barrier-boost coefficient between -1.2 and -0.3": (p["bb_g"], -1.2 < p["bb_g"] < -0.3),
        "ageing coefficient >= 0": (p["age_m"], p["age_m"] >= 0),
        "MB3 gain 0.010-0.030 degC per kWh/h": (fr.mb3_gain, 0.010 < fr.mb3_gain < 0.030),
        "air per Mcal 1.15-1.40": (fr.air_per_mcal, 1.15 < fr.air_per_mcal < 1.40),
        f"coverage last {recent_days} days 10-45% (25% intended)": (coverage, 0.10 <= coverage <= 0.45),
    }
    return {k: {"value": float(v), "pass": bool(ok)} for k, (v, ok) in res.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="models")
    ap.add_argument("--no-promote", action="store_true", help="do not update recommender_latest.json")
    ap.add_argument("--write-processed", action="store_true", help="also refresh data/processed/")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    # 1. load + clean (Excel here; a live loader passes raw=DataFrame instead)
    q = dp.clean_15min()
    d = dp.build_daily(q)
    h = dp.build_hourly(q)
    if args.write_processed:
        dp.write_processed(q, d, h)

    # 2. train on all usable history
    fr = rc.FinalRecommender().fit(d, q, h)

    # 3. checks
    rep = checks(fr, d)
    ok = all(c["pass"] for c in rep.values())

    # 4. save
    tag = str(pd.Timestamp(fr.trained_until).date())
    model_path = out / f"recommender_{tag}.json"
    fr.save(model_path)
    report = {"trained_until": tag, "passed": ok, "checks": rep, "model_file": model_path.name}
    (out / f"report_{tag}.json").write_text(json.dumps(report, indent=2))
    for k, c in rep.items():
        print(f"[{'PASS' if c['pass'] else 'FAIL'}] {k}: {c['value']:.4g}")
    if ok and not args.no_promote:
        shutil.copy(model_path, out / "recommender_latest.json")
        print("promoted ->", out / "recommender_latest.json")
    elif not ok:
        print("checks failed: recommender_latest.json NOT updated")
        sys.exit(1)


if __name__ == "__main__":
    main()
