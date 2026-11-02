import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from energybench.config import COUNTRIES, EUROPE
from energybench.power import RidgePower, country_cells, fit_with_validation
from energybench.scoring import csi, mae, recalibrate_cv

ROOT = Path(__file__).resolve().parents[1]
LAT = np.arange(34.5, 72.1, 1.5)
LON = np.arange(-12.0, 34.6, 1.5)


def power_curve(ws):
    return np.clip(((ws - 3) / 9) ** 3, 0, 1)


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    """Synthetic world: generation is a power curve of the regional mean wind."""
    root = tmp_path_factory.mktemp("data")
    rng = np.random.default_rng(0)
    t6 = pd.date_range("2015-01-01", "2020-12-31T18", freq="6h")
    ws = (6 + 3 * np.sin(np.arange(len(t6))[:, None, None] / 7 + LON[None, None, :] / 10)
          + rng.normal(0, 1, (len(t6), len(LAT), len(LON)))).clip(0).astype(np.float32)
    np.savez(root / "era5.npz", ws=ws, times=t6.values, lat=LAT, lon=LON)

    th = pd.date_range("2015-01-01", "2020-09-30T23", freq="h", tz="UTC")
    pos = np.searchsorted(t6, th.tz_convert(None), side="right") - 1
    gen = {"utc_timestamp": th}
    for c, (col, _) in COUNTRIES.items():
        mean_ws = ws[pos][:, country_cells(LAT, LON, c)].mean(1)
        gen[col] = 1000 * power_curve(mean_ws)
    pd.DataFrame(gen).to_csv(root / "opsd_60min.csv", index=False)

    inits = pd.date_range("2020-01-01", "2020-09-30T12", freq="12h")
    leads = np.arange(6, 241, 6)
    i6 = t6.get_indexer(inits)
    for name, noise in [("IFS HRES", 0.5), ("GraphCast", 1.0)]:
        fc = np.stack([ws[i6 + L // 6] for L in leads], 1)
        fc = fc + rng.normal(0, noise, fc.shape) * (leads / 240)[None, :, None, None]
        np.savez(root / f"fc_{name}.npz", ws=fc.astype(np.float32), inits=inits.values,
                 leads=leads, lat=LAT, lon=LON)
    return root


def test_scores_basic():
    obs = np.array([0.1, 0.5, np.nan, 0.9])
    assert mae(obs, obs) == 0
    assert mae(obs + 0.1, obs) == pytest.approx(0.1)
    assert csi(np.array([0.0, 0.0, 1.0]), np.array([0.0, 1.0, 0.0]), 0.5) == pytest.approx(1 / 3)


def test_recalibration_removes_linear_bias():
    rng = np.random.default_rng(1)
    obs = rng.uniform(0, 1, 600)
    pred = 0.2 + 0.5 * obs
    groups = np.repeat(np.arange(6), 100)
    assert mae(recalibrate_cv(pred, obs, groups), obs) < 1e-6


def test_ridge_learns_power_curve():
    rng = np.random.default_rng(2)
    ws = rng.uniform(0, 15, (2000, 4, 5)).astype(np.float32)
    cells = np.ones((4, 5), bool)
    y = power_curve(ws.mean((1, 2)))
    model, _, _ = fit_with_validation(ws[:1500], y[:1500], ws[1500:1800], y[1500:1800], cells)
    assert mae(model.predict(ws[1800:]), y[1800:]) < 0.05
    assert isinstance(model, RidgePower)


def test_benchmark_end_to_end(data_dir, tmp_path):
    out = tmp_path / "res"
    subprocess.run([sys.executable, str(ROOT / "scripts/run_benchmark.py"), "--data", str(data_dir),
                    "--out", str(out)], check=True)
    S = json.loads((out / "scores.json").read_text())["scores"]
    eu = S["raw"]["IFS HRES"][EUROPE]
    # skill decays with lead and the less noisy model wins at long range
    assert eu["24"]["mae"] < eu["240"]["mae"]
    assert eu["240"]["mae"] < S["raw"]["GraphCast"][EUROPE]["240"]["mae"]
    assert S["baselines"]["ERA5 floor"][EUROPE]["24"]["mae"] < eu["240"]["mae"]
