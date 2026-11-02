"""Fetch everything the benchmark needs into data/ (~150 MB on disk after the Europe cut).

    python scripts/download.py            # ERA5 2015-2020, all forecast models, OPSD
    python scripts/download.py --only FuXi
"""
import argparse
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from weather2watts.config import (BOX, ERA5_PATH, MAX_LEAD_H, MODELS, OPSD_URL,  # noqa: E402
                                TEST_INITS, VAR, WB2)


def europe_index(ds):
    lat, lon = ds.latitude.values, ((ds.longitude.values + 180) % 360) - 180
    li = np.where((lat >= BOX[0]) & (lat <= BOX[1]))[0]
    lo = np.where((lon >= BOX[2]) & (lon <= BOX[3]))[0]
    lo = lo[np.argsort(lon[lo])]
    return li, lo, lat[li], lon[lo]


def cut(a, li, lo):
    """(..., lon, lat) global -> (..., lat, lon) Europe."""
    return np.swapaxes(a[..., lo, :][..., li], -1, -2)


def retry(fn, *a):
    for attempt in range(5):
        try:
            return fn(*a)
        except Exception as e:
            if attempt == 4:
                raise
            print(f"  retry after {e!r}", flush=True)
            time.sleep(2 ** attempt)


def parallel(fn, jobs, workers, label):
    t0, out = time.time(), [None] * len(jobs)
    with ThreadPoolExecutor(workers) as pool:
        for n, (i, res) in enumerate(pool.map(lambda ij: (ij[0], retry(fn, ij[1])), enumerate(jobs)), 1):
            out[i] = res
            if n % 50 == 0 or n == len(jobs):
                print(f"{label}: {n}/{len(jobs)} ({time.time() - t0:.0f}s)", flush=True)
    return out


def era5(out, workers):
    ds = xr.open_zarr(WB2 + ERA5_PATH)
    li, lo, lat, lon = europe_index(ds)
    da = ds[VAR].sel(time=slice("2015-01-01", "2020-12-31T18"))
    times = da.time.values
    blocks = [(i, min(i + 64, len(times))) for i in range(0, len(times), 64)]
    parts = parallel(lambda b: cut(da.isel(time=slice(*b)).values, li, lo), blocks, workers, "ERA5")
    np.savez(out / "era5.npz", ws=np.concatenate(parts).astype(np.float32), times=times, lat=lat, lon=lon)


def forecast(name, out, workers):
    ds = xr.open_zarr(WB2 + MODELS[name]["path"])
    li, lo, lat, lon = europe_index(ds)
    da = ds[VAR].sel(time=slice(*TEST_INITS))
    da = da.sel(time=da.time.dt.hour.isin([0, 12]))
    leads = da.prediction_timedelta.values.astype("timedelta64[h]").astype(int)
    keep = np.where((leads > 0) & (leads <= MAX_LEAD_H))[0]
    da = da.isel(prediction_timedelta=keep)
    parts = parallel(lambda i: cut(da.isel(time=i).values, li, lo), list(range(da.sizes["time"])),
                     workers, name)
    np.savez(out / f"fc_{name}.npz", ws=np.stack(parts).astype(np.float32), inits=da.time.values,
             leads=leads[keep], lat=lat, lon=lon)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--only", nargs="*", help="subset of: ERA5, OPSD, or model names")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    want = lambda k: not args.only or k in args.only  # noqa: E731

    if want("OPSD") and not (out / "opsd_60min.csv").exists():
        urllib.request.urlretrieve(OPSD_URL, out / "opsd_60min.csv")
    if want("ERA5"):
        era5(out, args.workers)
    for name in MODELS:
        if want(name):
            forecast(name, out, args.workers)


if __name__ == "__main__":
    main()
