import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from weather2watts.config import COUNTRIES, EUROPE
from weather2watts.power import RidgePower, country_cells, fit_with_validation
from weather2watts.scoring import csi, mae, recalibrate_cv

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


def test_regrid_matches_cell_mean():
    from weather2watts.live import regrid

    lat = 90 - 0.25 * np.arange(721)
    lon = -180 + 0.25 * np.arange(1440)
    const = np.full((2, 721, 1440), 7.0)
    assert np.allclose(regrid(const, lat, lon, LAT, LON), 7.0)
    # a field linear in longitude averages to its value at the cell centre, across the dateline too
    lin = np.broadcast_to(np.cos(np.deg2rad(lon)), (721, 1440))
    out = regrid(lin, lat, lon, np.array([45.0]), np.array([0.0, 179.25, -12.0]))
    assert np.allclose(out, np.cos(np.deg2rad([0.0, 179.25, -12.0])), atol=2e-3)


def test_energy_charts_parse_centres_hours():
    from weather2watts.observed import parse

    t0 = int(pd.Timestamp("2026-01-01T00:00").timestamp())
    secs = [t0 + 900 * i for i in range(8)]  # 15-min stamps 00:00 .. 01:45
    d = {"unix_seconds": secs, "production_types": [
        {"name": "Wind onshore", "data": [float(i) for i in range(8)]},
        {"name": "Wind offshore", "data": [1.0] * 7 + [None]},
        {"name": "Solar", "data": [99.0] * 8}]}
    gen = parse(d)
    # hour 01:00 averages the quarters whose midpoints are in [00:30, 01:30): 00:30..01:15
    assert gen[pd.Timestamp("2026-01-01T01:00")] == pytest.approx(np.mean([2, 3, 4, 5]) + 1)


def test_power_models_roundtrip(tmp_path):
    from weather2watts.power import load_models, save_models

    rng = np.random.default_rng(3)
    ws = rng.uniform(0, 15, (300, len(LAT), len(LON))).astype(np.float32)
    cells = country_cells(LAT, LON, "DE")
    m = RidgePower(cells, 0.01).fit(ws, power_curve(ws[:, cells].mean(1)))
    save_models(tmp_path / "pm.npz", {"DE": m}, LAT, LON, np.zeros((12, 4, 1)))
    loaded, lat, lon, clim = load_models(tmp_path / "pm.npz")
    assert np.allclose(loaded["DE"].predict(ws), m.predict(ws))
    assert clim.shape == (12, 4, 1)


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
