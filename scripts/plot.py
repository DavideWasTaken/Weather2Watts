"""README figures and leaderboard from results/scores.json.

    python scripts/plot.py --results results
"""
import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

COLORS = {
    "IFS HRES": "#202124", "GraphCast": "#1a73e8", "GraphCast (oper.)": "#1a73e8",
    "Pangu-Weather": "#d93025", "Pangu-Weather (oper.)": "#d93025", "FuXi": "#188038",
    "GenCast (ens. mean)": "#9334e6",
}
BASE = {"climatology": dict(color="#9aa0a6", ls=":"), "persistence": dict(color="#9aa0a6", ls="--"),
        "ERA5 floor": dict(color="#f9ab00", ls="-.")}
DAYS = [1, 3, 5, 7, 10]


def curve(d, key="mae"):
    leads = sorted(int(k) for k in d)
    return np.array(leads) / 24, np.array([d[str(L)][key] for L in leads])


def style(name):
    return dict(color=COLORS[name], ls="--" if "oper." in name else "-", lw=2)


def at_day(d, day, key="mae"):
    v = d.get(str(day * 24), {}).get(key)
    return np.nan if v is None else v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    args = ap.parse_args()
    res_dir = Path(args.results)
    res = json.loads((res_dir / "scores.json").read_text())
    S, models = res["scores"], list(res["meta"]["models"])
    regions = list(res["meta"]["regions"])

    # 1. Europe skill curves, raw and recalibrated
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.6), sharey=True, constrained_layout=True)
    for ax, track, title in [(axes[0], "raw", "raw forecasts"), (axes[1], "recal", "after 2-parameter recalibration")]:
        for b, st in BASE.items():
            ax.plot(*curve(S["baselines"][b]["Europe"]), label=b, **st)
        for m in models:
            ax.plot(*curve(S[track][m]["Europe"]), label=m, **style(m))
        ax.set_title(f"European wind fleet, {title}")
        ax.set_xlabel("lead time [days]")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("MAE of capacity factor")
    axes[1].legend(frameon=False, fontsize=8, ncol=2)
    fig.savefig(res_dir / "europe_mae.png", dpi=130)

    # 2. skill vs climatology per country at day 3 (recalibrated track)
    countries = [r for r in regions if r != "Europe"]
    mat = np.array([[1 - at_day(S["recal"][m][c], 3) / at_day(S["baselines"]["climatology"][c], 3)
                     for c in countries] for m in models])
    fig, ax = plt.subplots(figsize=(12, 3.8), constrained_layout=True)
    im = ax.imshow(mat * 100, cmap="RdYlGn", vmin=0, vmax=80, aspect="auto")
    ax.set_xticks(range(len(countries)), countries)
    ax.set_yticks(range(len(models)), models)
    for i in range(len(models)):
        for j in range(len(countries)):
            ax.text(j, i, f"{mat[i, j] * 100:.0f}", ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, label="skill vs climatology [%]")
    ax.set_title("Day-3 wind power skill by country (MAE, recalibrated)")
    fig.savefig(res_dir / "country_skill_day3.png", dpi=130)

    # 3. case study: storm Ciara, February 2020
    p = np.load(res_dir / "predictions.npz", allow_pickle=True)
    inits, leads = pd.DatetimeIndex(p["inits"]), p["leads"]
    obs = pd.DataFrame(p["obs"], index=pd.DatetimeIndex(p["obs_times"]), columns=p["regions"])
    init = pd.Timestamp("2020-02-06T00")
    i = inits.get_loc(init)
    fig, axes = plt.subplots(1, 2, figsize=(13, 4), constrained_layout=True)
    for ax, r in zip(axes, ["DE", "GB"]):
        ri = list(p["regions"]).index(r)
        win = obs[r][init:init + pd.Timedelta(days=10)]
        ax.plot(win.index, win.values, color="k", lw=2.5, label="observed")
        for m in models:
            v = p[f"pred_{m}"][i, :, ri]
            ok = np.isfinite(v)
            ax.plot(init + pd.to_timedelta(leads[ok], "h"), v[ok], **{**style(m), "lw": 1.4}, label=m)
        ax.axvline(pd.Timestamp("2020-02-09T12"), color="#9aa0a6", lw=0.8)
        ax.set_title(f"{r} wind capacity factor, forecasts from {init:%d %b %Y %H}Z")
        ax.grid(alpha=0.3)
        ax.tick_params(axis="x", rotation=30)
    axes[0].legend(frameon=False, fontsize=8)
    fig.savefig(res_dir / "storm_ciara.png", dpi=130)

    # 4. why raw scores differ: 10 m wind bias and sharpness vs lead
    D = res["wind_diagnostics"]
    fig, axes = plt.subplots(1, 2, figsize=(13, 4), constrained_layout=True)
    for m in models:
        for ax, key in zip(axes, ["bias", "sharpness"]):
            ax.plot(*curve(D[m], key), label=m, **style(m))
    axes[0].axhline(0, color="#9aa0a6", lw=0.8)
    axes[1].axhline(1, color="#9aa0a6", lw=0.8)
    axes[0].set_title("10 m wind speed bias over Europe [m/s]")
    axes[1].set_title("sharpness: spatial std of forecast / ERA5")
    for ax in axes:
        ax.set_xlabel("lead time [days]")
        ax.grid(alpha=0.3)
    axes[1].legend(frameon=False, fontsize=8)
    fig.savefig(res_dir / "wind_bias_sharpness.png", dpi=130)

    # 5. leaderboard (markdown), ranked on the recalibrated D+5 error: at D+1-3
    #    the differences between models are within the bootstrap noise
    lines = ["| model | init | " + " | ".join(f"D+{d}" for d in DAYS)
             + " | raw D+3 | low-wind CSI D+3 | D+5 vs HRES, 95% CI |",
             "|---|---|" + "---|" * (len(DAYS) + 3)]
    V = res["europe_recal_mae_diff_vs_hres"]

    def vs_hres(name):
        if name not in V:
            return "–"
        m, lo, hi = V[name]["120"]
        mark = " ✓" if hi < 0 else (" ✗" if lo > 0 else "")
        return f"{m * 100:+.2f} [{lo * 100:+.2f}, {hi * 100:+.2f}]{mark}"

    rows = [(m, res["meta"]["models"][m]["init"], S["recal"][m]["Europe"], S["raw"][m]["Europe"])
            for m in models]
    rows += [(b, "–", S["baselines"][b]["Europe"], S["baselines"][b]["Europe"]) for b in BASE]
    rows.sort(key=lambda r: np.nan_to_num(at_day(r[2], 5), nan=9))
    fmt = lambda v: f"{v * 100:.2f}" if np.isfinite(v) else "–"  # noqa: E731
    for name, init_kind, d, raw in rows:
        cells = [fmt(at_day(d, x)) for x in DAYS]
        c = at_day(d, 3, "csi")
        lines.append(f"| {name} | {init_kind} | " + " | ".join(cells)
                     + f" | {fmt(at_day(raw, 3))} | {c:.2f} | {vs_hres(name)} |")
    table = "\n".join(lines)
    (res_dir / "leaderboard.md").write_text(table + "\n", encoding="utf-8")
    print(table)


if __name__ == "__main__":
    main()
