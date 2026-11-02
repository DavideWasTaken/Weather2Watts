"""Observed wind generation -> capacity factors on the 6-hourly forecast clock."""
import pandas as pd

from .config import COUNTRIES, EUROPE


def capacity_factors(csv_path, cap_quantile=0.995, cap_window_days=365):
    """DataFrame (UTC, 00/06/12/18) x (countries + Europe) of capacity factors.

    Installed capacity is not published consistently for every country, and it
    grows during the year. We use the trailing one-year 99.5th percentile of
    hourly output as an "effective capacity". It only looks backwards, so no
    information from the future leaks into the 2020 targets.
    """
    cols = {c: col for c, (col, _) in COUNTRIES.items()}
    raw = pd.read_csv(csv_path, index_col=0, parse_dates=True, usecols=["utc_timestamp", *cols.values()])
    gen = raw.rename(columns={v: k for k, v in cols.items()})
    # OPSD stamps the *start* of each hour; average the hours either side of t
    # so the value is centred on the instantaneous forecast time.
    gen = (gen + gen.shift(1)) / 2
    cap = gen.rolling(f"{cap_window_days}D", min_periods=24 * 60).quantile(cap_quantile)
    cf = gen / cap
    complete = gen.notna().all(axis=1)
    cf[EUROPE] = (gen.sum(axis=1) / cap.sum(axis=1)).where(complete)
    cf.index = cf.index.tz_convert(None)
    return cf[cf.index.hour % 6 == 0].astype("float32")
