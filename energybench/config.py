"""Models, countries and periods of the benchmark."""

WB2 = "https://storage.googleapis.com/weatherbench2/datasets/"
OPSD_URL = ("https://data.open-power-system-data.org/time_series/2020-10-06/"
            "time_series_60min_singleindex.csv")

# 10 m wind speed on the WB2 1.5 deg grid. `init` is what the forecast starts from:
# ERA5-initialised runs are what most papers report, but ERA5 is not available
# in real time, so only HRES-initialised runs are operationally achievable.
MODELS = {
    "IFS HRES": dict(path="hres/2016-2022-0012-240x121_equiangular_with_poles_conservative.zarr", init="HRES", kind="physics"),
    "GraphCast": dict(path="graphcast/2020/date_range_2019-11-16_2021-02-01_12_hours-240x121_equiangular_with_poles_conservative.zarr", init="ERA5", kind="AI"),
    "GraphCast (oper.)": dict(path="graphcast_hres_init/2020/date_range_2019-11-16_2021-02-01_12_hours-240x121_equiangular_with_poles_conservative.zarr", init="HRES", kind="AI"),
    "Pangu-Weather": dict(path="pangu/2018-2022_0012_240x121_equiangular_with_poles_conservative.zarr", init="ERA5", kind="AI"),
    "Pangu-Weather (oper.)": dict(path="pangu_hres_init/2020_0012_240x121_equiangular_with_poles_conservative.zarr", init="HRES", kind="AI"),
    "FuXi": dict(path="fuxi/2020-240x121_equiangular_with_poles_conservative.zarr", init="ERA5", kind="AI"),
    "GenCast (ens. mean)": dict(path="gencast/2020-240x121_equiangular_with_poles_conservative_mean.zarr", init="ERA5", kind="AI"),
}
ERA5_PATH = "era5/1959-2022-6h-240x121_equiangular_with_poles_conservative.zarr"
VAR = "10m_wind_speed"

# OPSD column (total wind where complete, onshore otherwise) and a lat/lon box
# around the country's fleet, offshore areas included.
COUNTRIES = {
    "DE": ("DE_wind_generation_actual", (47.0, 56.0, 5.0, 15.5)),
    "GB": ("GB_GBN_wind_generation_actual", (49.5, 61.0, -8.0, 2.5)),
    "FR": ("FR_wind_onshore_generation_actual", (42.0, 51.5, -5.0, 8.5)),
    "ES": ("ES_wind_onshore_generation_actual", (36.0, 44.0, -9.5, 3.5)),
    "IT": ("IT_wind_onshore_generation_actual", (36.5, 47.5, 6.5, 18.5)),
    "PL": ("PL_wind_onshore_generation_actual", (49.0, 55.0, 14.0, 24.5)),
    "SE": ("SE_wind_onshore_generation_actual", (55.0, 66.0, 11.0, 24.0)),
    "DK": ("DK_wind_generation_actual", (54.5, 58.0, 7.5, 13.0)),
    "NL": ("NL_wind_generation_actual", (50.5, 54.5, 3.0, 7.5)),
    "BE": ("BE_wind_onshore_generation_actual", (49.5, 52.0, 2.5, 6.5)),
    "IE": ("IE_wind_onshore_generation_actual", (51.5, 55.5, -10.5, -5.5)),
    "PT": ("PT_wind_onshore_generation_actual", (37.0, 42.5, -9.5, -6.0)),
    "AT": ("AT_wind_onshore_generation_actual", (46.5, 49.0, 9.5, 17.0)),
    "FI": ("FI_wind_onshore_generation_actual", (60.0, 69.0, 21.0, 30.0)),
    "NO": ("NO_wind_onshore_generation_actual", (58.0, 71.0, 5.0, 31.0)),
}
EUROPE = "Europe"  # sum of all countries above, fitted on the whole box
BOX = (34.5, 72.0, -12.0, 34.5)  # lat_min, lat_max, lon_min, lon_max cut from the global grid
MARGIN = 1.5  # extra degrees around each country box

TRAIN = ("2015-03-01", "2018-12-31T18")  # power-model fit (first months: capacity proxy warm-up)
VAL = ("2019-01-01", "2019-12-31T18")    # ridge strength selection
TEST_INITS = ("2020-01-01", "2020-09-30T12")  # OPSD ends 2020-09-30
MAX_LEAD_H = 240
