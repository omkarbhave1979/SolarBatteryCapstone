# Solar and household load forecasting with battery dispatch

UC Berkeley ML capstone data preparation. The two prediction targets are half-hourly gross rooftop PV generation and total household electricity consumption. The dispatch stage will use day-ahead forecasts to schedule a behind-the-meter battery.

## Evaluator data

`data/sample/ausgrid_sample.csv` contains two Ausgrid households over four consecutive Sydney calendar weeks beginning 1 July 2012. It requires no account or download. `data/sample/synthetic_meter.csv` is a deterministic two-household fixture for smoke runs. The real and synthetic CSVs have the same columns:

| Column | Definition |
| --- | --- |
| household_id | Ausgrid household ID or prefixed synthetic ID |
| interval_start_utc | ISO 8601 timestamp at the start of the half-hour interval |
| solar_kwh | Gross PV energy during the interval |
| load_kwh | General consumption plus separately metered controlled load where present |

These are meter targets. The final pipeline uses meter and calendar features for forecasting and simulates day-ahead dispatch. See the [forecast notebook](notebooks/02_forecast_modeling.ipynb) and [dispatch notebook](notebooks/03_battery_dispatch.ipynb). Historical weather features are pending. For time-based splits and lags, sort within household by timestamp and check for gaps. Split by time before fitting transforms. For dispatch, convert interval starts to Australia/Sydney for tariff windows and multiply charge/discharge kW by 0.5 hours to obtain interval kWh.

## Reproduce the meter preparation

Run from the project directory with Python 3.11 or newer and curl.

```sh
sh src/download_ausgrid.sh
python3 src/prepare_ausgrid.py
cmp data/processed/ausgrid_sample.csv data/sample/ausgrid_sample.csv
python3 src/prepare_ausgrid.py --full
```

The audit checks ZIP CRCs, records SHA-256, and scans all three annual CSVs. The raw archive includes an unrelated monthly dataset, which is outside the half-hour audit. Annual audit counts cover channel rows, missing expected channel-days, blank and invalid cells, quality flags, and usable intervals. Missing count keys indicate zero. The optional full export writes a gzip CSV. Keep the raw archive and intermediate files local. The full processed gzip and compact samples are included with attribution. GitHub's regular Git limit is 100 MiB per file [GitHub file limits](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github).

Ausgrid's notes describe Sydney local standard/daylight time and interval-ending labels. The source supplies 48 labeled half hours per day. This pipeline subtracts 30 minutes to obtain interval starts and converts using Sydney's historical offset, excluding the six offset-change dates because the source notes leave the treatment of missing/repeated slots unspecified. It drops invalid intervals and nonblank quality-flagged channel-days. A household with a CL record in a source year is expected to have CL throughout that year. For household-years with no CL records, load is GC only. A missing CL day in a household-year with CL leaves a gap. A quality flag column is absent in the first file, so those rows are retained subject to numerical validation. Household IDs missing a required channel or date remain visible in the aggregate missing counts.

Source and license are recorded in [data attribution](data/sample/ATTRIBUTION.md). See [the measured audit](data/ausgrid_audit.json) for the archive checksum and annual results.

## Historical weather

The [ECMWF Data Store TIGGE archive](https://ecds.ecmwf.int/datasets/tigge-forecasts?tab=download) lists historical ECMWF ensemble forecasts and six-hourly lead times. On 20 November 2026 an anonymous pilot submission returned HTTP 401, authentication required. No forecast files were retrieved. Sign in to ECMWF Data Store, accept the dataset terms, and configure a local token using [ECDS API setup](https://ecds.ecmwf.int/how-to-api). Install the `cdsapi` package in a virtual environment and run `python3 src/download_tigge.py` to submit the pilot. Request compatibility and archive coverage still need authenticated validation.

The pilot requests 00 UTC cycles from 30 June through 2 July 2012, lead hours 12–42 in six-hour steps, and a regional grid for 2 m temperature, surface net solar radiation and total cloud cover. The default window targets the first three Sydney-local days of the real sample using the previous local day's cycle. Confirm the regional grid covers household postcodes before scaling to all homes. Use the most recent cycle demonstrably available by a fixed 18:00 Sydney decision cutoff. Keep initialization, original availability assumptions, lead time, valid time and grid coordinates. Use only one cycle per forecast decision. For radiation, use consecutive accumulations from the same cycle to derive six-hour average W/m² where the GRIB metadata confirms cumulative J/m². Carry six-hour windows explicitly when aligning to half-hour rows. Operational release latency and TIGGE archive publication delay are distinct. The archive reports missing historical surface control forecasts, so inspect inventory and document gaps before expanding retrieval. Keep any weather outputs local pending validation against the dataset terms. [TIGGE FAQ](https://confluence.ecmwf.int/spaces/TIGGE/pages/40797492/FAQ) · [TIGGE license](https://ecds.ecmwf.int/licences/tigge-licence)

## Dispatch scenario

[Scenario configuration](config/scenario.json) defines illustrative, flat export and weekday time-of-use import rates in AUD. Weekdays use ISO numbering and the peak is 16:00–21:00 Sydney time. All modeled household load uses this scenario tariff. Holiday overrides, actual controlled-load rates, fixed charges, and battery degradation are outside the scenario. The simulated battery has a 10 kWh nameplate, 1–9 kWh state-of-charge bounds, 5 kW AC charge and discharge limits, 95% efficiency in each direction, and 5 kWh initial charge and end-of-day target. Grid charging and direct PV export are allowed. Battery export is disabled. Dispatch should prevent simultaneous charge/discharge and import/export.

## Weekly persistence baseline

The first day-ahead benchmark predicts each Sydney half-hour using the same household's matching wall-clock half-hour seven calendar days earlier. All 48 inputs are available before the prior day's 18:00 decision cutoff. The first source year is the training period, the second is validation, and the third is held out for test. No fitting is needed for persistence. Score only complete target days with complete lag days, and compare later models on the same household-days. Entirely absent days are outside the observed-day counts.

Run from the project directory:

```sh
python3 src/weekly_baseline.py data/sample/ausgrid_sample.csv --validation-start 2012-07-15 --test-start 2012-07-22
python3 src/weekly_baseline.py data/processed/ausgrid_intervals.csv.gz
```
