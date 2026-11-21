### Solar and household load forecasting with battery dispatch

**Author**  
Omkar Bhave · UC Berkeley ML Capstone · Assignment 20.1

#### Executive summary

Across 300 Ausgrid homes and 15.64 million half-hour readings, average rooftop solar generation peaked at noon and household demand peaked at 18:00 Sydney time. Solar exceeded demand in 19.8% of half-hours. On the held-out year, a simple day-ahead linear regression reduced RMSE for both targets relative to weekly persistence. Persistence had lower MAE for both targets.

#### Rationale

Rooftop solar can peak hours before household demand. A battery can shift some of that energy into the evening, when the household may otherwise buy electricity from the grid. Day-ahead forecasts can help decide when to charge and when to reserve energy for the evening peak.

#### Research Question

How do half-hourly gross solar generation and total household electricity use vary across the clock, seasons, and homes? How accurately can a simple regression using calendar information and recent meter history forecast the next day's 48 intervals for homes already in the meter panel?

#### Data Sources

The analysis uses Ausgrid's gross-metered solar homes in New South Wales from 1 July 2010 through 30 June 2013. The original cohort required a complete first year and excluded some early high- and low-performing households. The results describe this cohort and historical period. See [data attribution and file sizes](data/sample/ATTRIBUTION.md).

The repository includes a 103,387-byte real sample for an offline run. The [full processed export](data/processed/ausgrid_intervals.csv.gz) is included and can also be regenerated from the source archive. Weather forecasts were unavailable for analysis. See [provenance, preparation, and weather pilot notes](DATA_PREPARATION.md).

#### Methodology

- Convert interval-ending labels to UTC interval starts and recover Sydney wall-clock time for aggregation and feature engineering. Define total demand as general consumption plus controlled load where applicable. Exclude six daylight-saving transition dates and apply the source quality rules. Leave missing readings unfilled.
- Audit duplicates, invalid values and missing household-days against the expected grid. Use complete days for profiles, seasonal comparisons and correlations. Flag upper-tail readings by household and target using 1.5 times the IQR above Q3 on positive readings. Retain flagged values for analysis and modeling.
- Fit one pooled ordinary least squares regression for both targets. Features are both meter targets from the same Sydney half-hour seven days earlier, daily and annual cyclic calendar features, and a weekend indicator. These inputs are available by 18:00 on the day before delivery. Clip negative forecasts to zero.
- Train on July 2010–June 2011, validate on July 2011–June 2012, and test on July 2012–June 2013. Use the same complete household-days with complete weekly lags for regression and weekly persistence. No tuning was performed. See [validation and test results](results/assignment_20_1_full.json).

#### Results

- **Coverage.** The export contains 15,640,560 half-hour rows. There were zero duplicate keys, missing fields, non-finite readings, negative readings, off-grid timestamps, or partial household-days. After the six DST exclusions, 1,155 of 327,000 expected household-days (0.35%) were entirely absent. Gaps were most concentrated in early 2013.
- **Timing and surplus.** The average solar and demand peaks were six hours apart. Average daily load was 17.95 kWh on weekdays and 18.94 kWh on weekends. Summing only positive half-hour PV-minus-load margins gives 2.64 kWh per household-day on average, before any battery power, capacity, efficiency, or operating constraints.
- **Seasonality.** Average daily PV was 6.94 kWh in summer and 4.34 in winter. Average daily demand was 17.00 kWh in summer and 22.62 in winter. The clock-by-month plots show stronger winter morning and evening demand peaks.
- **Relationships and extremes.** Pooled daily solar and load had a Pearson correlation of 0.052. After subtracting each home's own mean from each target, it was −0.118. Median daily PV and load were 4.81 and 15.89 kWh, with 99th percentiles of 25.55 and 54.69 kWh. Solar was zero in 54.1% of half-hours. The per-home upper fence flagged 0.056% of positive PV readings and 9.01% of positive load readings, consistent with a much heavier upper tail in household demand by this diagnostic.

**Held-out year** · 5,146,896 eligible intervals per target. Errors are in kWh per half-hour.

| Target | Regression MAE | Weekly persistence MAE | Regression RMSE | Weekly persistence RMSE |
| --- | ---: | ---: | ---: | ---: |
| Gross solar | 0.0612 | 0.0593 | 0.1401 | 0.1530 |
| Household load | 0.2361 | 0.2252 | 0.3889 | 0.4473 |

Regression incurred 3.3% higher solar MAE and 4.9% higher load MAE. It had 8.5% lower solar RMSE and 13.1% lower load RMSE. The error profiles show that the MAE comparison varies by time of day. For load, regression improved around the evening peak but increased errors around midnight. For solar, small errors near the edges of the day contributed to higher all-day MAE.

#### Next steps

Align historical weather forecast inputs by issue time and lead time, and validate availability before using them at the decision cutoff. Compare forecast errors in daylight and tariff peak windows, then use held-out predictions to evaluate the [illustrative battery scenario](config/scenario.json).

#### Outline of project

- [Executed Assignment 20.1 notebook](notebooks/assignment_20_1.ipynb) with seven figures, written interpretations, and the baseline evaluation
- [Full-data numerical results](results/assignment_20_1_full.json)
- [Source preparation, meter definitions, and dispatch assumptions](DATA_PREPARATION.md)

Run from the repository root using Python 3.12 or newer. The reported run used Python 3.14.7. Both commands below keep the submitted full-run notebook outputs intact.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
AUSGRID_MODE=sample jupyter execute --timeout=600 --output=assignment_20_1_sample notebooks/assignment_20_1.ipynb
```

Run the full analysis against the included processed export. The notebook uses temporary disk space to group intervals by household.

```sh
AUSGRID_MODE=full jupyter execute --timeout=600 --output=assignment_20_1_reproduced notebooks/assignment_20_1.ipynb
```

Set `AUSGRID_SAVE_SUMMARY=1` if you also want to write the corresponding JSON summary under `results/`. When run interactively, the notebook uses the full export if present and otherwise defaults to the real sample. To rebuild the processed export from the source archive, see [data preparation](DATA_PREPARATION.md).

##### Contact and Further Information

Omkar Bhave · UC Berkeley ML Capstone. For source and licensing details, see [data attribution](data/sample/ATTRIBUTION.md).
