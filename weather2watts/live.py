"""Live wind-power forecasts from ECMWF open data (CC BY 4.0).

ECMWF publishes its physics model (IFS) and its AI model (AIFS) on a 0.25 deg
grid a few hours after each run. We compute 10 m wind speed on that grid,
average it onto the benchmark's 1.5 deg cells exactly as WeatherBench2 does,
and feed it to the power models fitted in run_benchmark.py.
"""
from pathlib import Path

import numpy as np
import pandas as pd

LIVE_MODELS = {"ifs": "ECMWF IFS", "aifs-single": "ECMWF AIFS"}
STEPS = list(range(0, 241, 6))

# 1.5 deg cell = 7 points of the 0.25 deg grid; the two edge points are shared
# with the neighbouring cell and count half (first-order conservative regrid).
_EDGE = np.array([0.5, 1, 1, 1, 1, 1, 0.5])


def regrid(field, lat_src, lon_src, lat_t, lon_t):
    """(..., lat, lon) on a 0.25 deg global grid -> (..., len(lat_t), len(lon_t)) cell means.

    lat_src may be in either order; lon_src must be increasing and span 360 deg.
    """
    step = abs(lat_src[1] - lat_src[0])
    rows = np.array([np.argmin(np.abs(lat_src - la)) for la in lat_t])[:, None] + np.arange(-3, 4)
    lon0 = lon_src[0]
    cols = np.array([int(round(((lo - lon0) % 360) / step)) for lo in lon_t])[:, None] + np.arange(-3, 4)
    cols %= len(lon_src)
    wlat = _EDGE * np.cos(np.deg2rad(lat_src[rows]))        # (nlat_t, 7)
    blk = field[..., rows, :][..., cols]                       # (..., nlat_t, 7, nlon_t, 7)
    w = wlat[:, :, None, None] * _EDGE[None, None, None, :]
    return (blk * w).sum((-3, -1)) / w.sum((-3, -1))


def read_grib_wind(path):
    """10 m wind speed (step, lat, lon) plus grid, from a GRIB2 file with 10u/10v."""
    import eccodes

    fields = {}
    with open(path, "rb") as f:
        while (h := eccodes.codes_grib_new_from_file(f)) is not None:
            ni, nj = eccodes.codes_get(h, "Ni"), eccodes.codes_get(h, "Nj")
            lat0 = eccodes.codes_get(h, "latitudeOfFirstGridPointInDegrees")
            lon0 = eccodes.codes_get(h, "longitudeOfFirstGridPointInDegrees")
            d = eccodes.codes_get(h, "iDirectionIncrementInDegrees")
            key = (eccodes.codes_get(h, "shortName"), eccodes.codes_get(h, "step"))
            fields[key] = eccodes.codes_get_values(h).reshape(nj, ni)
            eccodes.codes_release(h)
    steps = sorted({s for _, s in fields})
    ws = np.stack([np.hypot(fields["10u", s], fields["10v", s]) for s in steps])
    lat = lat0 - d * np.arange(nj)
    lon = ((lon0 + d * np.arange(ni) + 180) % 360) - 180
    order = np.argsort(lon)
    return ws[..., order], np.array(steps), lat, lon[order]


# The same files are mirrored on several clouds; any one of them can throttle
# (S3 "SlowDown", connection limits on data.ecmwf.int), so try them in turn.
SOURCES = ("google", "aws", "ecmwf")


def _client(source):
    from ecmwf.opendata import Client

    # fail fast on a throttled mirror instead of the client's default 500 retries
    return Client(source=source, maximum_retries=2, retry_after=10, use_server_retry_after=False)


def _first_working(fn):
    errors = []
    for src in SOURCES:
        try:
            return fn(_client(src))
        except Exception as e:  # noqa: PERF203
            errors.append(f"{src}: {e!r}"[:200])
    raise RuntimeError("all ECMWF open-data mirrors failed:\n" + "\n".join(errors))


def fetch(model, folder, steps=STEPS):
    """Download the latest complete run of `model`; returns (run time, grib path)."""
    def go(client):
        run = client.latest(model=model, type="fc", step=max(steps), param="10u")
        path = Path(folder) / f"{model}_{run:%Y%m%d%H}.grib2"
        if not path.exists():
            client.retrieve(model=model, type="fc", date=run, step=steps, param=["10u", "10v"], target=str(path))
        return pd.Timestamp(run), path

    return _first_working(go)


def fetch_past(model, run, steps, path):
    """Download a past run (the cloud mirrors keep months of history)."""
    def go(client):
        client.retrieve(model=model, type="fc", date=run.strftime("%Y%m%d"), time=run.hour,
                        step=steps, param=["10u", "10v"], target=str(path))
        return path

    return _first_working(go)


def power_forecast(path, run, models, lat_t, lon_t):
    """DataFrame (valid time x region) of capacity factors from one GRIB file."""
    ws, steps, lat, lon = read_grib_wind(path)
    ws15 = regrid(ws, lat, lon, lat_t, lon_t).astype(np.float32)
    valid = run + pd.to_timedelta(steps, "h")
    return pd.DataFrame({r: m.predict(ws15) for r, m in models.items()}, index=valid)
