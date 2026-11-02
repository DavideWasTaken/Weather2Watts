"""Tomorrow's (and the next 10 days') wind power for 15 European countries.

    python scripts/forecast_live.py            # latest IFS + AIFS runs -> results/live/

Needs only results/power_models.npz (committed), not the benchmark data.
Every run is also archived as CSV so the forecasts can be verified later.
"""
import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from energybench.live import LIVE_MODELS, fetch, power_forecast  # noqa: E402
from energybench.power import load_models  # noqa: E402

COLORS = {"ECMWF IFS": "#202124", "ECMWF AIFS": "#1a73e8"}
PANELS = ["Europe", "DE", "GB", "FR", "ES", "PL"]


def recalibrate(df, run, coeffs):
    """Apply backtest a + b * cf per country; lead days 1/3/5 cover <48 h, <96 h, beyond."""
    lead_h = (df.index - run) / pd.Timedelta(hours=1)
    day = np.where(lead_h < 48, "1", np.where(lead_h < 96, "3", "5"))
    out = df.copy()
    for c in df.columns:
        if c not in coeffs["1"]:
            continue
        a = np.array([coeffs[d][c][0] for d in day])
        b = np.array([coeffs[d][c][1] for d in day])
        out[c] = np.clip(a + b * df[c].to_numpy(), 0.0, 1.1)
    return out


def climatology(clim, regions, index):
    """Normal capacity factor (2015-2019 mean by month and hour) at each valid time."""
    vals = clim[index.month - 1, index.hour // 6]
    return pd.DataFrame(vals, index=index, columns=regions)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="results/power_models.npz")
    ap.add_argument("--out", default="results/live")
    ap.add_argument("--grib-dir", default="data/live")
    args = ap.parse_args()
    out, gdir = Path(args.out), Path(args.grib_dir)
    (out / "archive").mkdir(parents=True, exist_ok=True)
    gdir.mkdir(parents=True, exist_ok=True)

    models, lat, lon, clim = load_models(args.models)
    regions = list(models)
    recal_path = out / "recal.json"
    recal = json.loads(recal_path.read_text())["coefficients"] if recal_path.exists() else {}
    fcs, runs = {}, {}
    for key, name in LIVE_MODELS.items():
        run, path = fetch(key, gdir)
        raw = power_forecast(path, run, models, lat, lon)
        raw.to_csv(out / "archive" / f"{key}_{run:%Y%m%d%H}.csv", float_format="%.4f")
        # countries without observations (GB, and the Europe aggregate) stay raw
        fcs[name] = recalibrate(raw, run, recal[name]) if name in recal else raw
        runs[name] = run
        print(f"{name}: run {run:%Y-%m-%d %H}Z, {len(raw)} steps, recalibrated: {name in recal}")

    today = pd.Timestamp.now(tz="UTC").tz_convert(None).normalize()
    tomorrow = today + pd.Timedelta(days=1)
    first = next(iter(fcs.values()))
    normal = climatology(clim, regions, first.index)

    # figure: next 10 days, tomorrow shaded
    fig, axes = plt.subplots(2, 3, figsize=(14, 6.5), sharex=True, constrained_layout=True)
    for ax, r in zip(axes.flat, PANELS):
        ax.axvspan(tomorrow, tomorrow + pd.Timedelta(days=1), color="#fbbc04", alpha=0.15, lw=0)
        ax.plot(normal.index, normal[r], color="#9aa0a6", ls=":", label="normal (2015-2019)")
        for name, df in fcs.items():
            tag = " recal." if name in recal and r in recal[name]["1"] else ""
            ax.plot(df.index, df[r], color=COLORS[name], lw=2, label=f"{name} {runs[name]:%d %b %H}Z{tag}")
        ax.set_title(r if r != "Europe" else "Europe (15 countries)")
        ax.set_ylim(0, 1)
        ax.grid(alpha=0.3)
        ax.tick_params(axis="x", rotation=30)
        ax.legend(frameon=False, fontsize=7, loc="upper left")
    axes[0, 0].set_ylabel("wind capacity factor")
    axes[1, 0].set_ylabel("wind capacity factor")
    fig.suptitle(f"Wind power forecast, issued {today:%d %b %Y}. Shaded: tomorrow ({tomorrow:%a %d %b})")
    fig.savefig(out / "latest.png", dpi=120)

    # table: tomorrow's daily mean per region
    day = lambda df: df[(df.index >= tomorrow) & (df.index < tomorrow + pd.Timedelta(days=1))].mean()  # noqa: E731
    table = pd.DataFrame({name: day(df) for name, df in fcs.items()})
    table["normal"] = day(normal)
    names = list(fcs)
    lines = [f"Tomorrow, **{tomorrow:%A %d %B %Y}** (UTC daily mean capacity factor, %)", "",
             "| region | " + " | ".join(names) + " | normal | vs normal |",
             "|---|" + "---|" * (len(names) + 2)]
    for r in regions:
        mean = table.loc[r, names].mean()
        delta = (mean - table.loc[r, "normal"]) * 100
        arrow = "▲" if delta > 5 else ("▼" if delta < -5 else "≈")
        lines.append(f"| {r} | " + " | ".join(f"{table.loc[r, n] * 100:.0f}" for n in names)
                     + f" | {table.loc[r, 'normal'] * 100:.0f} | {arrow} {delta:+.0f} |")
    md = "\n".join(lines) + "\n"
    (out / "latest.md").write_text(md, encoding="utf-8")
    (out / "latest.json").write_text(json.dumps(dict(
        issued=str(today.date()), tomorrow=str(tomorrow.date()),
        runs={n: str(r) for n, r in runs.items()},
        forecasts={n: {r: [[str(t), round(float(v), 4)] for t, v in df[r].items()] for r in regions}
                   for n, df in fcs.items()},
    ), indent=1), encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
