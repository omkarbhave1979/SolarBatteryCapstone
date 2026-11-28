"""Train day-ahead forecasts and backtest battery dispatch on Ausgrid meter data."""
import argparse
import csv
import gzip
import json
from datetime import date
from itertools import groupby
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.model_selection import ParameterGrid, TimeSeriesSplit

from battery_dispatch import BatteryDispatch
from weekly_baseline import HEADER, SLOTS, local_records

ROOT = Path(__file__).resolve().parents[1]
METHODS = ("weekly_persistence", "linear_regression", "ridge", "gradient_boosting")


def read_panel(path):
    opener = gzip.open if path.suffix == ".gz" else open
    homes, days, readings = [], [], []
    with opener(path, "rt", newline="") as source:
        reader = csv.reader(source)
        if next(reader, None) != HEADER:
            raise ValueError("Expected the processed Ausgrid meter columns.")
        for (home, day), records in groupby(local_records(reader), key=lambda row: row[0]):
            records = list(records)
            if [slot for _, slot, _, _ in records] == SLOTS:
                homes.append(home)
                days.append(day.toordinal())
                readings.append(np.asarray([(solar, load) for _, _, solar, load in records], dtype=np.float32))
    return np.asarray(homes), np.asarray(days), np.asarray(readings)


def design(days, prior_week, prior_two_days):
    slot = np.broadcast_to(np.arange(48) / 48, prior_week.shape[:2])
    year = np.broadcast_to(days[:, None] / 365.2425, slot.shape)
    weekend = np.broadcast_to(((days - 1) % 7 >= 5)[:, None], slot.shape)
    return np.dstack((
        prior_week, prior_two_days, np.sin(2 * np.pi * slot), np.cos(2 * np.pi * slot),
        np.sin(2 * np.pi * year), np.cos(2 * np.pi * year), weekend,
    )).astype(np.float32)


def predictions(method, models, x):
    if method == "weekly_persistence":
        return x[:, :2]
    if method in ("linear_regression", "ridge"):
        return models[method].predict(x).clip(min=0)
    return np.column_stack([model.predict(x) for model in models[method]]).clip(min=0)


def metrics(actual, forecasts, mask):
    error = forecasts[mask] - actual[mask]
    if not len(error):
        return None
    return {
        target: {"mae": float(np.abs(values).mean()), "rmse": float(np.sqrt(np.square(values).mean()))}
        for target, values in zip(("solar", "load"), error.T)
    }


def fit_forecast_models(x, actual, days, train):
    """Select hyperparameters on expanding, date-disjoint folds inside training."""
    unique_days = np.unique(days[train])
    if len(unique_days) < 5:
        raise ValueError("At least five eligible training dates are required for cross-validation.")
    candidates = {
        "linear_regression": [{}],
        "ridge": list(ParameterGrid({"alpha": [10.0, 1000.0]})),
        "gradient_boosting": list(ParameterGrid({"max_leaf_nodes": [15, 31], "learning_rate": [0.05, 0.1]})),
    }

    def fit(method, params, mask):
        design_matrix = x[mask].reshape(-1, x.shape[-1])
        targets = actual[mask].reshape(-1, 2)
        if method == "linear_regression":
            return LinearRegression().fit(design_matrix, targets)
        if method == "ridge":
            return Ridge(**params).fit(design_matrix, targets)
        indices = np.random.default_rng(20).choice(len(targets), min(240_000, len(targets)), replace=False)
        return [
            HistGradientBoostingRegressor(
                **params, max_iter=100, early_stopping=False, random_state=20
            ).fit(design_matrix[indices], targets[indices, target])
            for target in range(2)
        ]

    records = {(method, index): [] for method, grid in candidates.items() for index in range(len(grid))}
    folds = []
    for fit_dates, score_dates in TimeSeriesSplit(n_splits=3).split(unique_days):
        fit_end = unique_days[fit_dates[-1]]
        score_start, score_end = unique_days[score_dates[[0, -1]]]
        fit_mask = days <= fit_end
        score_mask = (days >= score_start) & (days <= score_end)
        fold_x = x[score_mask].reshape(-1, x.shape[-1])
        fold_y = actual[score_mask].reshape(-1, 2)
        baseline = np.sqrt(np.mean((fold_x[:, :2] - fold_y) ** 2, axis=0))
        folds.append({
            "train_through": str(date.fromordinal(fit_end)),
            "validation_start": str(date.fromordinal(score_start)),
            "validation_end": str(date.fromordinal(score_end)),
            "intervals": len(fold_y),
        })
        print(f"Cross-validating {folds[-1]['validation_start']} to {folds[-1]['validation_end']}", flush=True)
        for method, grid in candidates.items():
            for index, params in enumerate(grid):
                model = fit(method, params, fit_mask)
                forecast = predictions(method, {method: model}, fold_x)
                rmse = np.sqrt(np.mean((forecast - fold_y) ** 2, axis=0))
                records[method, index].append({
                    "solar_rmse": float(rmse[0]), "load_rmse": float(rmse[1]),
                    "normalized_rmse": float(np.mean(rmse / np.maximum(baseline, 1e-12))),
                })
    models, trials = {}, []
    for method, grid in candidates.items():
        method_trials = [
            {
                "method": method, "parameters": params, "fold_scores": records[method, index],
                "mean_normalized_rmse": float(np.mean([r["normalized_rmse"] for r in records[method, index]])),
            }
            for index, params in enumerate(grid)
        ]
        best = min(method_trials, key=lambda trial: trial["mean_normalized_rmse"])
        models[method] = fit(method, best["parameters"], train)
        trials.extend({**trial, "selected_within_model": trial is best} for trial in method_trials)
    return models, {"folds": folds, "trials": trials}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--meter-csv", type=Path, default=ROOT / "data/processed/ausgrid_intervals.csv.gz")
    parser.add_argument("--scenario", type=Path, default=ROOT / "config/scenario.json")
    parser.add_argument("--validation-start", type=date.fromisoformat, default=date(2011, 7, 1))
    parser.add_argument("--test-start", type=date.fromisoformat, default=date(2012, 7, 1))
    parser.add_argument("--output", type=Path, default=ROOT / "results/full_implementation.json")
    args = parser.parse_args()
    if args.validation_start >= args.test_start:
        parser.error("Validation must start before test.")
    homes, days, meter = read_panel(args.meter_csv)
    lookup = {(home, int(day)): i for i, (home, day) in enumerate(zip(homes, days))}
    if len(lookup) != len(days):
        parser.error("Duplicate complete household-days.")
    eligible = [
        (i, lookup[home, day - 7], lookup[home, day - 2])
        for i, (home, day) in enumerate(zip(homes, days))
        if (home, day - 7) in lookup and (home, day - 2) in lookup
    ]
    if not eligible:
        parser.error("No complete household-days with both required lags.")
    rows, lag_week, lag_two_days = np.array(eligible).T
    x = design(days[rows], meter[lag_week], meter[lag_two_days])
    actual = meter[rows]
    _, home_index = np.unique(homes[rows], return_inverse=True)
    days = days[rows]
    train = days < args.validation_start.toordinal()
    test = days >= args.test_start.toordinal()
    validation = ~train & ~test
    if not all(split.any() for split in (train, validation, test)):
        parser.error("Train, validation and test must each contain eligible household-days.")
    del meter
    models, cv = fit_forecast_models(x, actual, days, train)

    battery = BatteryDispatch(json.loads(args.scenario.read_text()))
    report = {"validation_start": str(args.validation_start), "test_start": str(args.test_start), "cross_validation": cv}
    validation_rmses = {}
    test_forecasts = {}
    for split, split_mask in (("validation", validation), ("test", test)):
        split_actual = actual[split_mask]
        split_x = x[split_mask].reshape(-1, x.shape[-1])
        peak = np.array([battery.rates(date.fromordinal(day))[1] for day in days[split_mask]])
        slots = np.arange(48)
        masks = {
            "all": np.ones(split_actual.shape[:2], dtype=bool),
            "06:00–18:00_sydney": np.broadcast_to((slots >= 12) & (slots < 36), split_actual.shape[:2]),
            "tariff_peak": peak,
        }
        split_report = report[split] = {"household_days": int(split_mask.sum()), "forecast": {}}
        for method in METHODS:
            forecast = predictions(method, models, split_x).reshape(split_actual.shape)
            scores = {name: metrics(split_actual, forecast, mask) for name, mask in masks.items()}
            split_report["forecast"][method] = scores
            if split == "validation":
                validation_rmses[method] = np.array([scores["all"][target]["rmse"] for target in ("solar", "load")])
            else:
                test_forecasts[method] = forecast[..., 1] - forecast[..., 0]
    reference = np.maximum(validation_rmses["weekly_persistence"], 1e-12)
    selected = min(METHODS[1:], key=lambda method: (validation_rmses[method] / reference).mean())
    report["selected_ml_model"] = selected
    print(f"Replaying held-out dispatch for {selected} and weekly persistence", flush=True)
    test_actual = actual[test]
    actual_net = test_actual[..., 1] - test_actual[..., 0]
    report["test"]["dispatch"] = backtest(
        battery, days[test], home_index[test], actual_net,
        {method: test_forecasts[method] for method in ("weekly_persistence", selected)},
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(args.output)


def backtest(battery, days, homes, actual, forecasts):
    methods = tuple(forecasts)
    size = int(homes.max()) + 1
    state = {method: np.full(size, battery.initial) for method in methods}
    last = np.zeros(size, dtype=int)
    accounted = {method: np.zeros(size) for method in methods}
    throughput = dict.fromkeys(methods, 0.0)
    meter_cost = dict.fromkeys(methods, 0.0)
    target_days = dict.fromkeys(methods, 0)
    baseline = np.zeros(size)
    starts = 0
    daily = []
    for day in np.unique(days):
        rows = np.flatnonzero(days == day)
        household = homes[rows]
        rates, _ = battery.rates(date.fromordinal(int(day)))
        no_battery = battery.cost(actual[rows], rates).sum(axis=1)
        baseline[household] += no_battery
        daily_cost = [float(no_battery.sum())]
        gap = last[household] != day - 1
        starts += int(gap.sum())
        for method, forecast in forecasts.items():
            previous = state[method][household]
            initial = np.where(gap, battery.initial, previous)
            costs, final, energy = battery.replay(forecast[rows], actual[rows], initial, rates)
            # Value changes in stored energy at the off-peak grid replenishment rate.
            # This settles inventory across gaps and at the end of the holdout.
            adjusted = costs - (battery.states[final] - battery.states[initial]) * battery.inventory_rate
            meter_cost[method] += float(costs.sum())
            target_days[method] += int((final == battery.initial).sum())
            state[method][household] = final
            accounted[method][household] += adjusted
            daily_cost.append(float(adjusted.sum()))
            throughput[method] += float(energy.sum())
        last[household] = day
        daily.append([len(rows), *daily_cost])
    total = float(baseline.sum())
    observed = np.unique(homes)
    # Resample contiguous calendar-date blocks, keeping households together
    # within each date and preserving paired comparisons across strategies.
    daily = np.asarray(daily)
    block = min(14, len(daily))
    count = (len(daily) + block - 1) // block
    rng = np.random.default_rng(24)
    first = rng.integers(0, len(daily) - block + 1, size=(2000, count, 1))
    indices = (first + np.arange(block)).reshape(2000, -1)[:, :len(daily)]
    resampled = daily[indices].sum(axis=1)
    paired = (resampled[:, 2] - resampled[:, 3]) / resampled[:, 0]
    return {
        "ml_vs_persistence_savings_aud_per_household_day": float((daily[:, 2] - daily[:, 3]).sum() / len(days)),
        "ml_vs_persistence_block_bootstrap_95pct": np.percentile(paired, [2.5, 97.5]).tolist(),
        "bootstrap_block_days": block,
        "households": len(observed),
        "household_days": len(days),
        "contiguous_segments": starts,
        "no_battery_cost_aud": total,
        **{
            method: {
                "meter_cost_aud": meter_cost[method],
                "days_ending_at_target_soc": target_days[method],
                "inventory_adjusted_cost_aud": float(accounted[method].sum()),
                "savings_aud": float(total - accounted[method].sum()),
                "median_household_savings_aud": float(np.median((baseline - accounted[method])[observed])),
                "battery_ac_throughput_kwh": throughput[method],
            }
            for method in methods
        },
    }


if __name__ == "__main__":
    main()
