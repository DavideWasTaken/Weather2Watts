"""Backtest the live pipeline: past ECMWF IFS/AIFS runs vs observed generation.

    python scripts/backtest_live.py --days 90

Downloads the 00Z runs of the last N days from ECMWF's AWS mirror (only the
steps needed for D+1, D+3 and D+5), observed wind generation from Energy-Charts,
and scores both models with the 2015-2019 power models, raw and recalibrated.
"""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from energybench.config import COUNTRIES  # noqa: E402
from energybench.live import LIVE_MODELS, fetch_past, read_grib_wind, regrid  # noqa: E402
from energybench.observed import capacity_factors, fetch_country  # noqa: E402
from energybench.power import load_models  # noqa: E402
from energybench.scoring import mae, recalibrate_cv  # noqa: E402

LEAD_DAYS = [1, 3, 5]
STEPS = [24 * d + h for d in LEAD_DAYS for h in (0, 6, 12, 18)]


def valid_times(inits, day):
    """Flattened (init, hour) valid times of lead day `day`, init-major."""
    hours = np.array([24 * day + h for h in (0, 6, 12, 18)], dtype="timedelta64[h]")
    return pd.DatetimeIndex((inits.values[:, None] + hours[None]).ravel())


def history(model, runs, lat, lon, cache, workers):
    """(run, step, lat, lon) 1.5 deg wind speed, one cached npz per run."""
    cache.mkdir(parents=True, exist_ok=True)

    def one(run):
        f = cache / f"{model}_{run:%Y%m%d%H}.npy"
        if not f.exists():
            g = cache / f"{model}_{run:%Y%m%d%H}.grib2"
            for attempt in range(4):
                try:
                    fetch_past(model, run, STEPS, g)
                    break
                except Exception as e:
                    if attempt == 3:
                        print(f"  {model} {run} unavailable: {e!r}"[:120])
                        return None
                    time.sleep(5 * (attempt + 1))
            ws, steps, la, lo = read_grib_wind(g)
            assert list(steps) == STEPS, steps
            np.save(f, regrid(ws, la, lo, lat, lon).astype(np.float32))
            g.unlink()
        return np.load(f)

    out = []
    with ThreadPoolExecutor(workers) as pool:
        for i, r in enumerate(pool.map(one, runs), 1):
            out.append(r)
            if i % 10 == 0 or i == len(runs):
                print(f"{model}: {i}/{len(runs)} runs", flush=True)
    return out


def observed(start, end, cache):
    if cache.exists():
        return pd.read_csv(cache, index_col=0, parse_dates=True)
    cols = {}
    for cc in COUNTRIES:
        try:
            gen = fetch_country(cc, start, end)
        except Exception as e:
            print(f"  {cc}: no data ({e})")
            continue
        if gen is not None:
            cols[cc] = capacity_factors(gen)
            print(f"  {cc}: {gen.notna().sum()} hours")
        time.sleep(3)
    cf = pd.DataFrame(cols)
    cf.to_csv(cache, float_format="%.4f")
    return cf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--models", default="results/power_models.npz")
    ap.add_argument("--cache", default="data/backtest")
    ap.add_argument("--out", default="results/live")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    cache, out = Path(args.cache), Path(args.out)
    cache.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)

    models, lat, lon, clim = load_models(args.models)
    today = pd.Timestamp.now(tz="UTC").tz_convert(None).normalize()
    # last init whose D+5 day is already observed
    runs = pd.date_range(end=today - pd.Timedelta(days=max(LEAD_DAYS) + 1), periods=args.days, freq="D")
    print(f"inits {runs[0]:%Y-%m-%d} .. {runs[-1]:%Y-%m-%d}")

    start = (runs[0] - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
    cf = observed(start, today.strftime("%Y-%m-%d"), cache / f"observed_{today:%Y%m%d}.csv")
    countries = [c for c in COUNTRIES if c in cf]

    rows, series = [], {}
    recal = {}  # model -> lead day -> country -> [a, b], fitted on the whole window for live use
    pos = {s: i for i, s in enumerate(STEPS)}
    preds = {}
    for key, name in LIVE_MODELS.items():
        hist = history(key, runs, lat, lon, cache, args.workers)
        ok = [i for i, h in enumerate(hist) if h is not None]
        ws = np.stack([hist[i] for i in ok])  # (run, step, lat, lon)
        preds[name] = (runs[ok], {c: models[c].predict(ws.reshape(-1, *ws.shape[2:])).reshape(len(ok), len(STEPS))
                                  for c in countries})

    common = sorted(set.intersection(*(set(r) for r, _ in preds.values())))
    common = pd.DatetimeIndex(common)
    for name, (r_ok, p) in preds.items():
        sel = r_ok.get_indexer(common)
        for d in LEAD_DAYS:
            idx = [pos[24 * d + h] for h in (0, 6, 12, 18)]
            valid = valid_times(common, d)
            weeks = valid.isocalendar().week.to_numpy()
            for c in countries:
                o = cf[c].reindex(valid).to_numpy()
                f = p[c][sel][:, idx].ravel()
                rows.append(dict(model=name, lead=d, country=c, track="raw", mae=mae(f, o),
                                 bias=float(np.nanmean(f - o))))
                rc = recalibrate_cv(f, o, weeks)
                rows.append(dict(model=name, lead=d, country=c, track="recal", mae=mae(rc, o), bias=float(np.nanmean(rc - o))))
                series[name, d, c] = (valid, f, o)
                ok = np.isfinite(f) & np.isfinite(o)
                b, a = np.polyfit(f[ok], o[ok], 1)
                recal.setdefault(name, {}).setdefault(str(d), {})[c] = [round(float(a), 4), round(float(b), 4)]

    # baselines on the same valid times: persistence (CF observed at init) and 2015-2019 climatology
    for d in LEAD_DAYS:
        valid = valid_times(common, d)
        init_t = pd.DatetimeIndex(np.repeat(common.values, 4))
        for c in countries:
            o = cf[c].reindex(valid).to_numpy()
            pers = cf[c].reindex(init_t).to_numpy()
            cl = clim[valid.month.to_numpy() - 1, valid.hour.to_numpy() // 6, list(models).index(c)]
            for b, f in [("persistence", pers), ("climatology", cl)]:
                rows.append(dict(model=b, lead=d, country=c, track="raw", mae=mae(f, o), bias=float(np.nanmean(f - o))))

    df = pd.DataFrame(rows)
    df.to_csv(out / "backtest.csv", index=False, float_format="%.4f")
    mean = df.groupby(["model", "track", "lead"])[["mae", "bias"]].mean().reset_index()

    # summary table: mean over countries
    lines = [f"Backtest: {len(common)} daily 00Z runs, {common[0]:%d %b} – {common[-1]:%d %b %Y}, "
             f"{len(countries)} countries ({', '.join(countries)}). MAE of capacity factor in % points, "
             "mean over countries (bias in brackets).", "",
             "| forecast | " + " | ".join(f"D+{d}" for d in LEAD_DAYS) + " |", "|---|" + "---|" * len(LEAD_DAYS)]
    for (m, tr), g in mean.groupby(["model", "track"], sort=False):
        label = m if m in ("persistence", "climatology") else f"{m} ({tr})"
        g = g.set_index("lead")
        lines.append(f"| {label} | " + " | ".join(
            f"{g.loc[d, 'mae'] * 100:.1f} ({g.loc[d, 'bias'] * 100:+.1f})" for d in LEAD_DAYS) + " |")
    md = "\n".join(lines) + "\n"
    (out / "backtest.md").write_text(md, encoding="utf-8")
    (out / "backtest.json").write_text(json.dumps(dict(
        inits=[str(common[0].date()), str(common[-1].date()), len(common)], countries=countries,
        summary=mean.to_dict(orient="records")), indent=1))
    (out / "recal.json").write_text(json.dumps(dict(
        window=[str(common[0].date()), str(common[-1].date())], coefficients=recal), indent=1))
    print(md)

    # figure: DE and ES D+1 time series + per-country D+1 MAE
    fig, axes = plt.subplots(3, 1, figsize=(14, 10), constrained_layout=True)
    for ax, c in zip(axes[:2], [c for c in ("DE", "ES") if c in countries]):
        valid, _, o = series["ECMWF IFS", 1, c]
        order = np.argsort(valid)
        ax.plot(valid[order], o[order], color="k", lw=2, label="observed (Energy-Charts)")
        for name, col in [("ECMWF IFS", "#5f6368"), ("ECMWF AIFS", "#1a73e8")]:
            v, f, _ = series[name, 1, c]
            ax.plot(v[order], f[order], color=col, lw=1.2, label=f"{name}, D+1 raw")
        ax.set_title(f"{c}: day-ahead wind capacity factor")
        ax.grid(alpha=0.3)
        ax.legend(frameon=False, fontsize=8, ncol=3)
    d1 = df[(df.lead == 1) & ((df.track == "recal") | df.model.isin(["persistence", "climatology"]))]
    piv = d1.pivot_table(index="country", columns="model", values="mae").loc[countries] * 100
    colors = {"ECMWF AIFS": "#1a73e8", "ECMWF IFS": "#202124", "climatology": "#dadce0", "persistence": "#9aa0a6"}
    piv.plot.bar(ax=axes[2], color=[colors[c] for c in piv.columns], width=0.8)
    axes[2].set_title("D+1 MAE by country (IFS/AIFS recalibrated)")
    axes[2].set_ylabel("MAE [% CF]")
    axes[2].grid(alpha=0.3, axis="y")
    fig.savefig(out / "backtest.png", dpi=110)


if __name__ == "__main__":
    main()
