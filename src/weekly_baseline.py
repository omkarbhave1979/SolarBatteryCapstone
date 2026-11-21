"""Score a weekly persistence forecast on complete Sydney household-days."""
import argparse
import csv
import gzip
import json
from collections import Counter
from datetime import date, datetime, timedelta
from itertools import groupby
from pathlib import Path
from zoneinfo import ZoneInfo

SYDNEY = ZoneInfo("Australia/Sydney")
WEEK = timedelta(days=7)
SLOTS = list(range(48))
HEADER = ["household_id", "interval_start_utc", "solar_kwh", "load_kwh"]


def local_records(reader):
    for household, stamp, solar, load in reader:
        local = datetime.fromisoformat(stamp).astimezone(SYDNEY)
        yield (household, local.date()), local.hour * 2 + local.minute // 30, float(solar), float(load)


def score(reader, validation_start, test_start):
    history = {}
    last_day = {}
    counters = {name: Counter() for name in ("train", "validation", "test")}
    for (household, day), records in groupby(local_records(reader), key=lambda row: row[0]):
        if household in last_day and day <= last_day[household]:
            raise ValueError(f"Expected grouped, chronological days for household {household}: {day}")
        last_day[household] = day
        split = "train" if day < validation_start else "validation" if day < test_start else "test"
        stats = counters[split]
        stats["observed_household_days"] += 1
        prior_days = history.setdefault(household, {})
        prior = prior_days.get(day - WEEK)
        current = []
        slots = []
        for _, slot, solar, load in records:
            current.append((solar, load))
            slots.append(slot)
        cutoff = day - WEEK
        for expired in [old_day for old_day in prior_days if old_day < cutoff]:
            del prior_days[expired]
        if slots != SLOTS:
            stats["incomplete_target_days"] += 1
            continue
        prior_days[day] = current
        if prior is None:
            stats["missing_complete_lag_days"] += 1
            continue
        stats["scored_household_days"] += 1
        for (solar, load), (predicted_solar, predicted_load) in zip(current, prior):
            solar_error = abs(solar - predicted_solar)
            load_error = abs(load - predicted_load)
            stats["solar_abs"] += solar_error
            stats["load_abs"] += load_error
            stats["solar_squared"] += solar_error**2
            stats["load_squared"] += load_error**2

    result = {}
    for name, stats in counters.items():
        intervals = stats["scored_household_days"] * 48
        result[name] = {
            **{key: stats[key] for key in (
                "observed_household_days", "incomplete_target_days",
                "missing_complete_lag_days", "scored_household_days"
            )},
            "scored_intervals": intervals,
            **{
                f"{target}_{metric}_kwh": (
                    round((stats[f"{target}_{total}"] / intervals)**power, 6)
                    if intervals else None
                )
                for target in ("solar", "load")
                for metric, total, power in (("mae", "abs", 1), ("rmse", "squared", 0.5))
            },
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meter_csv", type=Path)
    parser.add_argument("--validation-start", type=date.fromisoformat, default=date(2011, 7, 1))
    parser.add_argument("--test-start", type=date.fromisoformat, default=date(2012, 7, 1))
    args = parser.parse_args()
    if args.validation_start >= args.test_start:
        parser.error("Validation must start before the test period.")
    open_csv = gzip.open if args.meter_csv.suffix == ".gz" else open
    with open_csv(args.meter_csv, "rt", newline="") as source:
        reader = csv.reader(source)
        if next(reader, None) != HEADER:
            parser.error("Expected the processed Ausgrid meter columns.")
        result = score(reader, args.validation_start, args.test_start)
    print(json.dumps({
        "method": "same household and Sydney wall-clock slot seven calendar days earlier",
        "validation_start_sydney": args.validation_start.isoformat(),
        "test_start_sydney": args.test_start.isoformat(),
        "splits": result,
    }, indent=2))


if __name__ == "__main__":
    main()
