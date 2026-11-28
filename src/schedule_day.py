"""Generate a next-day battery schedule from available household meter history."""
import argparse
import csv
from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
import sys

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LinearRegression, Ridge

from battery_dispatch import BatteryDispatch
from run_capstone import ROOT, design, predictions, read_panel
from weekly_baseline import SYDNEY

ARCHIVE = ROOT / "data/processed/ausgrid_intervals.csv.gz"

FIELDS = (
    "interval_start_sydney", "forecast_solar_kwh", "forecast_demand_kwh",
    "action", "battery_power_kw", "battery_end_kwh",
)


def schedule(meter_csv, household, delivery, starting_kwh, method, training_csv=ARCHIVE, *, demo_profile_date=None):
    start = datetime.combine(delivery, time.min, SYDNEY)
    end = datetime.combine(delivery + timedelta(days=1), time.min, SYDNEY)
    if start.utcoffset() != end.utcoffset():
        raise ValueError("This scheduler supports 48-slot days. Choose a date without a daylight-saving clock change.")

    battery = BatteryDispatch(json.loads((ROOT / "config/scenario.json").read_text()))
    if not np.isfinite(starting_kwh):
        raise ValueError("Starting charge must be a finite number.")
    initial = int(np.argmin(abs(battery.states - starting_kwh)))
    if not np.isclose(battery.states[initial], starting_kwh):
        raise ValueError("Starting charge must be between 1 and 9 kWh in 0.5 kWh increments.")

    homes, days, readings = read_panel(meter_csv)
    lookup = {(home, int(day)): index for index, (home, day) in enumerate(zip(homes, days))}
    if len(lookup) != len(days):
        raise ValueError("The meter file contains duplicate complete household-days.")
    delivery_day = delivery.toordinal()
    offsets = (7,) if method == "weekly_persistence" else (7, 2)
    if demo_profile_date is not None and method != "weekly_persistence":
        raise ValueError("The demonstration profile requires weekly persistence.")
    profile_day = (demo_profile_date or delivery).toordinal()
    required = [profile_day - offset for offset in offsets]
    missing = [date.fromordinal(day).isoformat() for day in required if (household, day) not in lookup]
    if missing:
        raise ValueError(f"Household {household} needs complete meter readings for {', '.join(missing)}. "
                         "Supply recent data in the processed Ausgrid CSV format or choose a date covered by the file.")

    lag_readings = readings[[lookup[household, day] for day in required]]
    if not np.isfinite(lag_readings).all() or (lag_readings < 0).any():
        raise ValueError("Required meter readings must be finite and nonnegative.")
    prior_week = lag_readings[:1]
    if method == "weekly_persistence":
        forecast = prior_week[0]
    else:
        report = json.loads((ROOT / "results/full_implementation.json").read_text())
        fit_before = date.fromisoformat(report["validation_start"]).toordinal()
        if delivery_day < date.fromisoformat(report["test_start"]).toordinal():
            raise ValueError("The validated model is available for dates in or after the held-out period. "
                             "Use weekly persistence for an earlier demonstration.")
        selected = report["selected_ml_model"]
        params = next(trial["parameters"] for trial in report["cross_validation"]["trials"]
                      if trial["method"] == selected and trial["selected_within_model"])
        recent = lag_readings[1:]
        if training_csv.resolve() != meter_csv.resolve():
            homes, days, readings = read_panel(training_csv)
        train_lookup = {(home, int(day)): index for index, (home, day) in enumerate(zip(homes, days))}
        if len(train_lookup) != len(days):
            raise ValueError("The training data contains duplicate complete household-days.")
        eligible = [(index, train_lookup[home, day - 7], train_lookup[home, day - 2])
                    for (home, day), index in train_lookup.items()
                    if day < fit_before and (home, day - 7) in train_lookup and (home, day - 2) in train_lookup]
        if not eligible:
            raise ValueError("The training file must include eligible readings from the original training period.")
        rows, week, two = np.asarray(eligible).T
        x = design(days[rows], readings[week], readings[two]).reshape(len(rows) * 48, -1)
        y = readings[rows].reshape(-1, 2)
        if selected == "gradient_boosting":
            subset = np.random.default_rng(20).choice(len(y), min(240_000, len(y)), replace=False)
            models = [
                HistGradientBoostingRegressor(
                    **params, max_iter=100, early_stopping=False, random_state=20
                ).fit(x[subset], y[subset, target])
                for target in range(2)
            ]
        else:
            estimator = Ridge(**params) if selected == "ridge" else LinearRegression()
            models = estimator.fit(x, y)
        features = design(np.array([delivery_day]), prior_week, recent)[0]
        forecast = predictions(selected, {selected: models}, features)

    solar, demand = forecast.T
    net = (demand - solar)[None, :]
    rates, _ = battery.rates(delivery)
    states = []
    battery.replay(net, net, np.array([initial]), rates, state_history=states)
    state_indices = np.searchsorted(battery.states, np.asarray(states)[:, 0])
    charge = battery.charge[state_indices[:-1], state_indices[1:]]
    discharge = battery.discharge[state_indices[:-1], state_indices[1:]]
    for slot, (pv, load, added, used, stored) in enumerate(zip(solar, demand, charge, discharge, states[1:])):
        yield (
            (start + timedelta(minutes=30 * slot)).isoformat(timespec="minutes"),
            round(float(pv), 4), round(float(load), 4),
            "charge" if added else "discharge" if used else "idle",
            round(float(2 * (added - used)), 4), float(stored[0]),
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("date", type=date.fromisoformat, help="Sydney delivery date in YYYY-MM-DD format")
    parser.add_argument("--household", required=True)
    parser.add_argument("--meter-csv", type=Path, default=ARCHIVE)
    parser.add_argument("--training-csv", type=Path, default=ARCHIVE, help="Training archive for the validated model")
    parser.add_argument("--starting-kwh", required=True, type=float, help="Expected stored energy at midnight")
    parser.add_argument("--forecast", choices=("weekly_persistence", "validated_model"), default="weekly_persistence")
    parser.add_argument("--output", type=Path, help="Write CSV to this file instead of standard output")
    args = parser.parse_args()
    try:
        rows = list(schedule(args.meter_csv, args.household, args.date, args.starting_kwh, args.forecast, args.training_csv))
        if args.output:
            with args.output.open("w", newline="") as output:
                writer = csv.writer(output)
                writer.writerow(FIELDS)
                writer.writerows(rows)
        else:
            writer = csv.writer(sys.stdout)
            writer.writerow(FIELDS)
            writer.writerows(rows)
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
