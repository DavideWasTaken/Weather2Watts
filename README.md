# Weather2Watts

**An open benchmark of AI weather models on real wind power generation.**

[![ci](https://github.com/DavideWasTaken/Weather2Watts/actions/workflows/ci.yml/badge.svg)](https://github.com/DavideWasTaken/Weather2Watts/actions/workflows/ci.yml)
[![live forecast](https://github.com/DavideWasTaken/Weather2Watts/actions/workflows/live.yml/badge.svg)](results/live/latest.md)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![python](https://img.shields.io/badge/python-3.10%2B-blue)

**AI weather models are scored on Z500 and 2 m temperature. Energy traders care about one thing:
how many megawatts will the wind fleet produce?** Weather2Watts takes forecasts from GraphCast,
Pangu-Weather, FuXi, GenCast and ECMWF AIFS, plus the physics-based ECMWF IFS/HRES. It turns them
into wind power and scores them against the *real* hourly generation (ENTSO-E) of 15 European
countries. A daily live forecast compares ECMWF's AI and physics models out of sample.

<p align="center"><img src="results/europe_mae.png" width="100%"></p>

The idea comes from [Jua's EPT-2 report (arXiv:2507.09703)](https://arxiv.org/abs/2507.09703): the
models that matter for energy should be judged on energy-relevant targets, not on the variables
ML benchmarks happen to use. WeatherBench2 compares models on gridded weather and stationbench
compares them on station observations. Weather2Watts goes one step further downstream, to the
power grid. Everything is open data and runs on a laptop in about 5 minutes.

## Live: tomorrow's wind power

The same power models also run on today's forecasts. Twice a day a GitHub Action fetches the
latest ECMWF **IFS** (physics) and **AIFS** (AI) runs from ECMWF open data and converts them to
wind capacity factors for the 15 countries. It also commits the chart, a table for tomorrow
([`results/live/latest.md`](results/live/latest.md)) and an archive of every run, so the
forecasts can be checked against what actually happened.

<p align="center"><img src="results/live/latest.png" width="100%"></p>

### Does it work? A 90-day backtest

[`scripts/backtest_live.py`](scripts/backtest_live.py) replays the pipeline on the last 90 daily
00Z runs, fetched from ECMWF's cloud mirrors. It scores them against observed generation from
[Energy-Charts](https://energy-charts.info) (Fraunhofer ISE, ENTSO-E data) in the 14 countries
it covers; GB is not available there. The window was 30 Jul to 27 Oct 2026, and the table shows
MAE of the capacity factor in percentage points, averaged over countries, with bias in brackets:

| forecast | D+1 | D+3 | D+5 |
|---|---|---|---|
| ECMWF AIFS (recal) | **7.7** (+0.0) | **9.4** (+0.0) | **12.2** (+0.0) |
| ECMWF IFS (recal) | 8.1 (+0.0) | 10.2 (-0.0) | 13.7 (-0.0) |
| ECMWF AIFS (raw) | 8.3 (-3.5) | 10.2 (-5.0) | 12.9 (-5.9) |
| ECMWF IFS (raw) | 8.6 (-1.4) | 10.6 (-2.4) | 14.1 (-2.5) |
| climatology | 17.7 (-2.7) | 17.9 (-2.7) | 18.1 (-2.4) |
| persistence | 21.1 (+2.3) | 24.1 (+2.0) | 24.8 (+2.0) |

* **The live pipeline is as good as the historical benchmark.** For IFS, per-country errors are
  8.1 / 10.2 / 13.7 at D+1 / D+3 / D+5, against 7.3 / 9.1 / 13.2 in the 2020 benchmark. Day-ahead
  error is less than half that of climatology.
* **ECMWF's AI model beats its physics model for wind power,** in 12-14 of 14 countries at every
  lead after recalibration. The mean gain is 0.4 / 0.9 / 1.4 points, with 95% intervals that
  exclude zero (bootstrap over countries).
* **Both models under-forecast today's fleet,** AIFS by up to 6 points. Turbines installed since
  2019 deliver more power at the same wind than the 2015-2019 power models expect. The live
  forecast therefore applies the per-country, per-lead `a + b·cf` fitted in the backtest
  ([`results/live/recal.json`](results/live/recal.json)). GB and the Europe aggregate have no
  observations here, so they stay raw.

<p align="center"><img src="results/live/backtest.png" width="100%"></p>

## Leaderboard: European wind fleet, Jan–Sep 2020

Mean absolute error of the capacity factor in percentage points, for 548 forecasts initialized at
00/12 UTC, after a 2-parameter recalibration per lead time (see [method](#method)). Lower is better.

| model | init | D+1 | D+3 | D+5 | D+7 | D+10 | raw D+3 | low-wind CSI D+3 | D+5 vs HRES, 95% CI |
|---|---|---|---|---|---|---|---|---|---|
| *ERA5 floor* | – | 3.33 | 3.34 | 3.35 | 3.34 | 3.34 | 3.34 | 0.71 | – |
| GenCast (ens. mean) | ERA5 | 3.39 | 4.10 | **5.60** | **7.30** | **9.01** | 4.12 | 0.58 | -0.71 [-1.23, -0.21] ✓ |
| FuXi | ERA5 | **3.37** | **4.04** | 5.65 | 7.89 | 9.71 | 5.17 | 0.52 | -0.66 [-1.15, -0.16] ✓ |
| Pangu-Weather (oper.) | HRES | 3.64 | 4.22 | 5.69 | 8.34 | 11.53 | 4.91 | 0.54 | -0.62 [-1.16, -0.08] ✓ |
| GraphCast | ERA5 | 3.57 | 4.32 | 5.77 | 7.35 | 10.73 | 5.51 | 0.51 | -0.54 [-1.04, -0.01] ✓ |
| GraphCast (oper.)¹ | HRES | 3.52 | 4.12 | 5.83 | 8.03 | 10.78 | 5.11 | 0.61 | -0.48 [-0.93, -0.01] ✓ |
| Pangu-Weather | ERA5 | 3.56 | 4.25 | 5.90 | 8.31 | 11.42 | 4.75 | 0.49 | -0.41 [-0.93, +0.11] |
| IFS HRES | HRES | 3.66 | 4.23 | 6.31 | 8.28 | 11.46 | **4.28** | 0.59 | – |
| *climatology* | – | 10.71 | 10.71 | 10.70 | 10.75 | 10.77 | 10.71 | 0.00 | – |
| *persistence* | – | 9.62 | 14.53 | 14.20 | 13.60 | 14.90 | 14.53 | 0.16 | – |

✓ = significantly better than IFS HRES (paired moving-block bootstrap, one-week blocks).
At D+1 to D+3 no model is significantly better or worse than HRES, so the order of those columns
is noise. ¹ The operational GraphCast was fine-tuned on HRES data, and WeatherBench2 does not say
which years. Overlap with 2020 cannot be ruled out.

## Findings

**1. Out of the box, AI forecasts make *worse* wind-power forecasts than the physics model.**
If you feed raw forecasts into a power model built on reanalysis (the usual setup), IFS HRES gives
the best deterministic day-3 power forecast (4.28). GraphCast comes in at 5.51 and FuXi at 5.17.
The cause is a systematic low bias in 10 m wind that grows with lead time: GraphCast is about
−0.5 m/s over Europe and Pangu about −0.2 m/s. Power goes roughly with the cube of wind speed, so a
bias that barely moves an RMSE scorecard becomes several capacity-factor points.

<p align="center"><img src="results/wind_bias_sharpness.png" width="100%"></p>

**2. Two numbers per lead time fix it, and then AI wins beyond day 4.** A linear recalibration
(`a + b·forecast`, fitted leaving one month out) removes the bias. After it, five of the six AI
forecasts beat HRES at day 5 by 0.5 to 0.7 capacity-factor points, with 95% intervals excluding
zero.

**3. Day-ahead wind power is limited by the conversion model, not by the weather model.** Feed the
power model the *verifying* analysis, a perfect weather forecast, and the error is still 3.33.
At D+1 every model is within 0.35 points of that floor. For day-ahead trading the gains are in the
weather → power step, not in a better global model. This holds for our simple conversion model; a
better one would lower the floor.

**4. FuXi has a visible seam at day 5.** FuXi is a cascade of three models (0-5, 5-10, 10-15
days). Exactly where the medium-range model takes over, the 10 m wind bias jumps from −0.4 to
−2.1 m/s by day 10 and spatial variability drops to 62% of ERA5. Raw D+7 power error doubles
(17.7 vs about 9 for the others). Recalibration hides most of this in the MAE, but not in event
detection.

**5. For Pangu, ERA5 vs operational initialization barely matters for wind power.** Pangu is the
one clean comparison, with the same weights and only the initial state changing. The two runs stay
within about 0.2 points of each other at every lead (D+5: 5.90 vs 5.69). That is smaller than the
bootstrap uncertainty of either one against HRES. Here, the ERA5-initialized scores usually
reported in papers did not overstate Pangu's value for wind power.

**6. MAE-optimal and event-optimal are different forecasts.** Recalibration shrinks long-range
forecasts toward the mean. That minimizes MAE but stops them from ever predicting a lull.
Detection of low-wind events (capacity factor below the 2015-2019 10th percentile) falls from a
CSI of 0.22-0.36 (raw) to 0.00-0.19 (recalibrated) at D+7. If you trade on "Dunkelflaute" risk,
do not use the MAE-tuned forecast.

### Storm Ciara, February 2020

Forecasts from 6 Feb 00Z, three days before landfall. Every model gets the ramp-up. They differ in
how long the storm lasts and in the lull on 14-15 Feb.

<p align="center"><img src="results/storm_ciara.png" width="100%"></p>

### Per-country skill at day 3

<p align="center"><img src="results/country_skill_day3.png" width="100%"></p>

## Method

* **Truth.** Hourly wind generation from [Open Power System Data](https://data.open-power-system-data.org/time_series/2020-10-06)
  (ENTSO-E Transparency and TSOs) for DE, GB, FR, ES, IT, PL, SE, DK, NL, BE, IE, PT, AT, FI and NO.
  Capacity is published inconsistently and grows during the year, so the capacity factor uses an
  *effective capacity*: the trailing one-year 99.5th percentile of output. It only looks
  backwards, so no future information leaks in. "Europe" is the sum of all 15 countries.
* **Forecasts.** 10 m wind speed on the 1.5° grid from the public
  [WeatherBench2](https://weatherbench2.readthedocs.io) archive: IFS HRES, GraphCast (ERA5-init
  and operational), Pangu-Weather (ERA5- and HRES-init), FuXi and the GenCast ensemble mean. The
  same 548 initializations are used for every model. Valid times run to 30 Sep 2020, when the OPSD
  release ends.
* **Weather → power.** One ridge regression per country on `ws, ws², ws³` at every 1.5° cell in
  a box around the country's fleet. It is fitted on ERA5 2015-2018, with ridge strength chosen on
  2019. The power model is shared by all forecasts, so score differences come from the weather.
* **Two tracks.** *raw* applies the ERA5 power model directly. *recal* adds `a + b·pred` per model
  and lead, fitted leaving one calendar month out. Most production systems recalibrate, so *recal*
  is the headline.
* **Baselines.** Climatology (month × hour mean, 2015-2019), persistence (observed capacity factor
  at init time), and the ERA5 floor (power model fed the verifying ERA5, the error left with a
  perfect weather forecast).
* **Uncertainty.** Paired differences against HRES with a moving-block bootstrap (blocks of one
  week of initializations, 2000 resamples).

## Run it

```bash
pip install -e ".[dev]"
python scripts/download.py        # ~650 MB on disk; ERA5 + 7 forecast archives + OPSD, ~5 min
python scripts/run_benchmark.py   # ~1 min on CPU
python scripts/plot.py            # figures + results/leaderboard.md
pytest                            # synthetic end-to-end test, no downloads
```

Live forecast only (no benchmark data needed, ~5 MB download):

```bash
pip install -e ".[live]"
python scripts/forecast_live.py   # -> results/live/latest.{png,md,json}
python scripts/backtest_live.py   # optional, ~1.5 GB / 30 min: re-fits results/live/recal.json
```

**Add your model:** put its 10 m wind speed on the WB2 1.5° grid as a zarr and add one line to
`MODELS` in [`weather2watts/config.py`](weather2watts/config.py). Or write `data/fc_<name>.npz` with
`ws (init, lead, lat, lon)`, `inits`, `leads` (hours), `lat`, `lon`, cut to the box in
`config.BOX`. `run_benchmark.py` picks up every `fc_*.npz` it finds.

## Limitations

* **Nine months, one region, one variable.** This is 2020 only, because that is where OPSD and the
  WB2 archives overlap, and it covers wind only. WB2's AI archives carry no surface radiation, so
  solar is left out.
* **1.5° grid and 10 m wind.** Turbines sit at about 100 m and in valleys and coastlines a 1.5°
  cell cannot resolve. The ridge absorbs some of this, but the ERA5 floor shows how much is left.
* **The effective-capacity proxy lags sudden capacity jumps,** for example new Dutch offshore
  farms. That makes NL the noisiest country.
* **GenCast enters as an ensemble mean,** which is naturally smooth and favoured by MAE. A proper
  probabilistic track (CRPS over its members, which WB2 also hosts) is the obvious next step.
* **Training-data overlap** with the 2020 test period is ruled out for GraphCast (trained through
  2019), Pangu-Weather and FuXi (through 2017), per WeatherBench2. We could not confirm it for
  GenCast or operational GraphCast.

## Data licenses and credits

OPSD time series: see the [OPSD terms](https://data.open-power-system-data.org/time_series/)
(sourced from ENTSO-E and TSOs). Forecasts and ERA5: [WeatherBench2](https://github.com/google-research/weatherbench2),
which redistributes ECMWF and model-developer data under their respective licenses. Live
forecasts: [ECMWF open data](https://www.ecmwf.int/en/forecasts/datasets/open-data), © ECMWF,
CC BY 4.0. Inspired by
[EPT-2](https://arxiv.org/abs/2507.09703) and [stationbench](https://github.com/juaAI/stationbench).
Code: MIT.
