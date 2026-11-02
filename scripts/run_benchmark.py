"""Score every forecast model on real European wind generation.

    python scripts/run_benchmark.py --data data --out results

Track "raw":     ERA5-fitted power model applied to each model's raw forecast.
Track "recal":   plus a two-parameter per-lead recalibration (leave-one-month-out).
Baselines:       climatology (month x hour), persistence (observed CF at init),
                 ERA5 floor (the power model fed the *verifying analysis*: the
                 error left if the weather forecast were perfect).
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from energybench.config import COUNTRIES, EUROPE, MODELS, TRAIN, VAL  # noqa: E402
from energybench.generation import capacity_factors  # noqa: E402
from energybench.power import country_cells, fit_with_validation, save_models  # noqa: E402
from energybench.scoring import csi, mae, paired_diff_ci, recalibrate_cv  # noqa: E402

REGIONS = [EUROPE, *COUNTRIES]
REFERENCE = "IFS HRES"  # paired comparisons are against the operational physics model


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="results")
    args = ap.parse_args()
    data, out = Path(args.data), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    cf = capacity_factors(data / "opsd_60min.csv")
    era = np.load(data / "era5.npz")
    e_ws, e_t = era["ws"], pd.DatetimeIndex(era["times"])
    lat, lon = era["lat"], era["lon"]
    obs_era = cf.reindex(e_t)
    tr = (e_t >= TRAIN[0]) & (e_t <= TRAIN[1])
    va = (e_t >= VAL[0]) & (e_t <= VAL[1])
    e_pos = {t: i for i, t in enumerate(e_t)}

    # ---- power models, thresholds, climatology (all from 2015-2019 only) ----
    power, meta = {}, {}
    hist = cf[(cf.index >= TRAIN[0]) & (cf.index <= VAL[1])]
    clim = hist.groupby([hist.index.month, hist.index.hour]).mean()
    low = hist.quantile(0.10)
    for r in REGIONS:
        y = obs_era[r].to_numpy()
        m_tr, m_va = tr & np.isfinite(y), va & np.isfinite(y)
        cells = country_cells(lat, lon, r)
        power[r], alpha, val_mae = fit_with_validation(e_ws[m_tr], y[m_tr], e_ws[m_va], y[m_va], cells)
        meta[r] = dict(alpha=alpha, val_mae_era5=val_mae, cells=int(cells.sum()), low_wind_threshold=float(low[r]))
        print(f"{r:7s} cells {cells.sum():4d}  alpha {alpha:g}  ERA5 val MAE {val_mae:.4f}")
    clim_arr = np.array([[clim[r].get((m, h), np.nan) for r in REGIONS]
                         for m in range(1, 13) for h in (0, 6, 12, 18)]).reshape(12, 4, len(REGIONS))
    save_models(out / "power_models.npz", power, lat, lon, clim_arr.astype(np.float32))

    # ---- forecasts on a common set of inits ----
    fcs = {n: np.load(data / f"fc_{n}.npz") for n in MODELS if (data / f"fc_{n}.npz").exists()}
    inits = sorted(set.intersection(*(set(pd.DatetimeIndex(f["inits"])) for f in fcs.values())))
    inits = pd.DatetimeIndex(inits)
    print(f"{len(fcs)} models, {len(inits)} common inits {inits[0]} .. {inits[-1]}")

    scores = {"raw": {}, "recal": {}, "baselines": {}}
    diag = {}  # wind-speed bias and sharpness vs the verifying ERA5, over the whole box
    preds = {}
    eu_err = {}  # (model, lead) -> per-init absolute error, Europe, recalibrated

    def put(track, name, r, lead, p, o):
        d = scores[track].setdefault(name, {}).setdefault(r, {})
        d[str(lead)] = dict(mae=mae(p, o), csi=csi(p, o, low[r]), n=int(np.isfinite(o).sum()))

    all_leads = sorted(set().union(*(set(f["leads"].tolist()) for f in fcs.values())))
    for name, f in fcs.items():
        idx = pd.DatetimeIndex(f["inits"]).get_indexer(inits)
        ws = f["ws"][idx]  # (I, L, H, W)
        preds[name] = np.full((len(inits), len(all_leads), len(REGIONS)), np.nan, np.float32)
        for li, lead in enumerate(f["leads"]):
            valid = inits + pd.Timedelta(hours=int(lead))
            obs = cf.reindex(valid)
            ei = np.array([e_pos.get(t, -1) for t in valid])
            fc, truth = ws[ei >= 0, li], e_ws[ei[ei >= 0]]
            diag.setdefault(name, {})[str(lead)] = dict(
                bias=float((fc - truth).mean()),
                sharpness=float(fc.std(axis=(1, 2)).mean() / truth.std(axis=(1, 2)).mean()))
            for ri, r in enumerate(REGIONS):
                o = obs[r].to_numpy()
                p = power[r].predict(ws[:, li])
                put("raw", name, r, lead, p, o)
                rc = recalibrate_cv(p, o, valid.month.to_numpy())
                put("recal", name, r, lead, rc, o)
                if r == EUROPE:
                    eu_err[name, int(lead)] = np.abs(rc - o)
                preds[name][:, all_leads.index(lead), ri] = p
        print("scored", name, flush=True)

    # baselines on the same (init, lead) pairs
    for lead in all_leads:
        valid = inits + pd.Timedelta(hours=int(lead))
        obs = cf.reindex(valid)
        at_init = cf.reindex(inits)
        era_i = np.array([e_pos.get(t, -1) for t in valid])
        for r in REGIONS:
            o = obs[r].to_numpy()
            c = clim[r].reindex(pd.MultiIndex.from_arrays([valid.month, valid.hour])).to_numpy()
            put("baselines", "climatology", r, lead, c, o)
            put("baselines", "persistence", r, lead, at_init[r].to_numpy(), o)
            e = np.full(len(valid), np.nan)
            e[era_i >= 0] = power[r].predict(e_ws[era_i[era_i >= 0]])
            put("baselines", "ERA5 floor", r, lead, e, o)

    vs_ref = {}
    if REFERENCE in fcs:
        for (name, lead), err in eu_err.items():
            if name != REFERENCE and (REFERENCE, lead) in eu_err:
                vs_ref.setdefault(name, {})[str(lead)] = paired_diff_ci(err, eu_err[REFERENCE, lead])

    res = dict(meta=dict(regions=meta, inits=[str(inits[0]), str(inits[-1]), len(inits)],
                         models={n: {k: v for k, v in MODELS[n].items() if k != "path"} for n in fcs}),
               scores=scores, wind_diagnostics=diag,
               europe_recal_mae_diff_vs_hres=vs_ref)  # (mean, ci_low, ci_high); < 0 means better
    (out / "scores.json").write_text(json.dumps(res, indent=1))
    np.savez_compressed(out / "predictions.npz", inits=inits.values, leads=np.array(all_leads),
                        regions=np.array(REGIONS), **{f"pred_{n}": p for n, p in preds.items()},
                        obs=cf[REGIONS].to_numpy(), obs_times=cf.index.values)
    print("wrote", out / "scores.json")


if __name__ == "__main__":
    main()
