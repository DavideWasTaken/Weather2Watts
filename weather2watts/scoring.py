"""Scores for capacity-factor forecasts."""
import numpy as np


def mae(pred, obs):
    ok = np.isfinite(obs) & np.isfinite(pred)
    return float(np.mean(np.abs(pred[ok] - obs[ok]))) if ok.any() else float("nan")


def csi(pred, obs, threshold):
    """Critical success index for low-wind events (CF below threshold)."""
    ok = np.isfinite(obs) & np.isfinite(pred)
    f, o = pred[ok] < threshold, obs[ok] < threshold
    hits, misses, false = np.sum(f & o), np.sum(~f & o), np.sum(f & ~o)
    denom = hits + misses + false
    return float(hits / denom) if denom else float("nan")


def paired_diff_ci(err_a, err_b, block=14, n_boot=2000, seed=0):
    """95% CI of mean(err_a - err_b) by a moving-block bootstrap over inits.

    Consecutive 12-hourly inits share weather regimes, so samples are drawn in
    blocks of a week (14 inits) to keep that correlation.
    """
    ok = np.isfinite(err_a) & np.isfinite(err_b)
    d = (err_a - err_b)[ok]
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, len(d) - block + 1, (n_boot, -(-len(d) // block)))
    idx = (starts[..., None] + np.arange(block)).reshape(n_boot, -1)[:, :len(d)]
    means = d[idx].mean(1)
    return float(d.mean()), float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def recalibrate_cv(pred, obs, groups):
    """Linear recalibration a + b * pred, fitted leaving one group (month) out.

    Removes the lead-dependent bias and damping of a forecast with two
    parameters, which a forecaster would do with a few months of history.
    """
    out = np.full_like(pred, np.nan)
    ok = np.isfinite(obs) & np.isfinite(pred)
    for g in np.unique(groups):
        tr, te = ok & (groups != g), groups == g
        if tr.sum() < 10:
            continue
        b, a = np.polyfit(pred[tr], obs[tr], 1)
        out[te] = np.clip(a + b * pred[te], 0.0, 1.1)
    return out
