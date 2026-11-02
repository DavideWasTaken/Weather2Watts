"""Recent observed wind generation from Energy-Charts (Fraunhofer ISE, ENTSO-E data)."""
import json
import time
import urllib.error
import urllib.request

import pandas as pd

API = "https://api.energy-charts.info/public_power?country={cc}&start={start}&end={end}"
WIND = ("Wind onshore", "Wind offshore")


def fetch_country(cc, start, end, retries=6):
    """Hourly wind generation [MW], centred on the hour, UTC-naive index."""
    url = API.format(cc=cc.lower(), start=start, end=end)
    for attempt in range(retries):
        try:
            raw = urllib.request.urlopen(url, timeout=180).read()
            break
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == retries - 1:
                raise
            time.sleep(15 * (attempt + 1))  # rate limited
    return parse(json.loads(raw.decode("utf-8-sig")))


def parse(d):
    t = pd.to_datetime(d["unix_seconds"], unit="s")
    parts = [pd.Series(p["data"], index=t, dtype="float64")
             for p in d["production_types"] if p["name"] in WIND]
    if not parts:
        return None
    gen = pd.concat(parts, axis=1).sum(axis=1, min_count=1)
    # stamps mark interval starts: move to midpoints, then average the midpoints in
    # [h - 30 min, h + 30 min) into hour h
    half = (t[1] - t[0]) / 2
    mid = gen.index + half + pd.Timedelta(minutes=30)
    return gen.groupby(mid.floor("h")).mean()


def capacity_factors(gen, cap_quantile=0.995, cap_window_days=365):
    """Same definition as generation.capacity_factors: trailing-year effective capacity."""
    cap = gen.rolling(f"{cap_window_days}D", min_periods=24 * 60).quantile(cap_quantile)
    return gen / cap
