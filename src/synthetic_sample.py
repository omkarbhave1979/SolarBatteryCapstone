"""Build a deterministic 28-day fixture for a no-download smoke run."""
import csv
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLUMNS = ("household_id", "interval_start_utc", "solar_kwh", "load_kwh")


def main():
    target = ROOT / "data/sample/synthetic_meter.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    aest = timezone(timedelta(hours=10))
    start = datetime(2012, 9, 24, tzinfo=aest)
    with target.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(COLUMNS)
        for household in (1, 2):
            for slot in range(28 * 48):
                day, half_hour = divmod(slot, 48)
                hour = half_hour / 2 + 0.25
                sun = max(0, math.sin(math.pi * (hour - 6) / 12))
                cloud = 0.6 + 0.4 * (1 + math.cos(day * 1.7)) / 2
                solar = sun * cloud * (1.05 + 0.2 * household)
                load = (0.12 + 0.04 * household + 0.15 * math.exp(-((hour - 7) / 1.5)**2)
                        + 0.52 * math.exp(-((hour - 19) / 2)**2)
                        + 0.05 * (day % 7 >= 5) + 0.02 * math.sin(slot * 1.9))
                stamp = (start + timedelta(minutes=30 * slot)).astimezone(timezone.utc)
                writer.writerow([f"synthetic-{household}", stamp.isoformat(), f"{solar:.4f}", f"{load:.4f}"])


if __name__ == "__main__":
    main()
