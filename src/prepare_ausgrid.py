"""Audit the three annual meter files and generate complete household intervals."""
import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import zipfile
from collections import Counter
from contextlib import ExitStack
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from synthetic_sample import COLUMNS, ROOT

SYDNEY = ZoneInfo("Australia/Sydney")
UTC = timezone.utc
DAY = timedelta(days=1)
HALF_HOUR = timedelta(minutes=30)
CATEGORIES = {"GC", "GG", "CL"}
SLOTS = [f"{(i // 2) % 24}:{(i % 2) * 30:02}" for i in range(1, 49)]


def read_year(archive, name, start, stop):
    records = {}
    counts = Counter()
    metadata = {}
    with archive.open(name) as source:
        reader = csv.reader(io.TextIOWrapper(source, encoding="utf-8-sig"))
        next(reader)  # Ausgrid notice
        header = [cell.strip().lower() for cell in next(reader)]
        slots = [header.index(slot) for slot in SLOTS]
        quality = header.index("row quality") if "row quality" in header else None
        identity = [header.index(field) for field in
                    ("customer", "postcode", "generator capacity", "consumption category", "date")]
        for row in reader:
            if not any(row):
                continue
            customer, postcode, capacity, channel, raw_day = [row[i].strip() for i in identity]
            household = int(customer)
            date_format = "%d/%m/%Y" if "/" in raw_day else "%d-%b-%y"
            day = datetime.strptime(raw_day, date_format).date()
            if not start <= day < stop or channel not in CATEGORIES or not 1 <= household <= 300:
                raise ValueError(f"Unexpected key in {name} line {reader.line_num}")
            metadata.setdefault(household, set()).add((postcode, capacity))
            key = (household, day, channel)
            if key in records:
                raise ValueError(f"Duplicate key in {name}: {key}")
            counts[channel] += 1
            flag = row[quality].strip() if quality is not None else ""
            if flag:
                counts[f"quality:{flag}"] += 1
            values = []
            for i in slots:
                try:
                    value = float(row[i])
                except ValueError:
                    counts["blank_cells" if not row[i].strip() else "nonnumeric_cells"] += 1
                    value = None
                if value is not None and (not math.isfinite(value) or value < 0):
                    counts["negative_or_nonfinite_cells"] += 1
                    value = None
                values.append(value)
            records[key] = (values, bool(flag))
    return records, counts, metadata


def utc_intervals(day):
    midnight = datetime.combine(day, datetime.min.time())
    start = midnight.replace(tzinfo=SYDNEY)
    end = (midnight + DAY).replace(tzinfo=SYDNEY)
    if start.utcoffset() != end.utcoffset():
        return None
    utc_start = start.astimezone(UTC)
    return [(utc_start + slot * HALF_HOUR).isoformat() for slot in range(48)]


def audit_year(records, counts, metadata, start, stop, full_writer, sample_writer):
    controlled = {household for household, _, channel in records if channel == "CL"}
    households = set(metadata)
    usable = Counter()
    days = (stop - start).days
    calendars = {start + i * DAY: utc_intervals(start + i * DAY) for i in range(days)}
    sample_rows = 0
    for household in range(1, 301):
        channels = ("GG", "GC", "CL") if household in controlled else ("GG", "GC")
        for day, stamps in calendars.items():
            rows = [records.get((household, day, channel)) for channel in channels]
            for channel, row in zip(channels, rows):
                if row is None:
                    counts[f"missing_{channel}_days"] += 1
            if any(row is None for row in rows):
                continue
            if any(flag for _, flag in rows):
                counts["flagged_complete_channel_days_excluded"] += 1
                continue
            if stamps is None:
                continue
            sample_day = household in (1, 2) and date(2012, 7, 1) <= day < date(2012, 7, 29)
            for slot, readings in enumerate(zip(*(values for values, _ in rows))):
                if None in readings:
                    continue
                usable[household] += 1
                if full_writer or sample_day:
                    solar, *loads = readings
                    row = (household, stamps[slot], f"{solar:.10g}", f"{sum(loads):.10g}")
                    if full_writer:
                        full_writer.writerow(row)
                    if sample_day:
                        sample_writer.writerow(row)
                        sample_rows += 1

    excluded = [day.isoformat() for day, stamps in calendars.items() if stamps is None]
    return {
        "households": len(households),
        "households_with_controlled_load_rows": len(controlled),
        "households_with_multiple_postcode_or_capacity_pairs": sorted(
            h for h, values in metadata.items() if len(values) > 1
        ),
        "source_calendar_days": days,
        "source_dates_with_dst_transitions_excluded": excluded,
        "counts": dict(counts),
        "usable_intervals": sum(usable.values()),
        "households_complete_after_dst_exclusions": sum(
            count == (days - len(excluded)) * 48 for count in usable.values()
        ),
        "sample_rows": sample_rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ROOT / "data/raw/ausgrid.zip")
    parser.add_argument("--full", action="store_true", help="also write all eligible intervals")
    args = parser.parse_args()
    output = ROOT / "data/processed"
    output.mkdir(parents=True, exist_ok=True)
    report = {"years": {}}
    with args.archive.open("rb") as source:
        report["archive_sha256"] = hashlib.file_digest(source, "sha256").hexdigest()
    report["archive_bytes"] = args.archive.stat().st_size

    with TemporaryDirectory(dir=output) as staging:
        prepare(args, Path(staging), report)
        for result in Path(staging).iterdir():
            result.replace(output / result.name)
    print(json.dumps(report, indent=2))


def prepare(args, output, report):
    with ExitStack() as stack:
        archive = stack.enter_context(zipfile.ZipFile(args.archive))
        failed_member = archive.testzip()
        if failed_member:
            raise ValueError(f"Archive CRC check failed: {failed_member}")
        sample = stack.enter_context((output / "ausgrid_sample.csv").open("w", newline=""))
        sample_writer = csv.writer(sample)
        sample_writer.writerow(COLUMNS)
        full_writer = None
        if args.full:
            full = stack.enter_context(gzip.open(output / "ausgrid_intervals.csv.gz", "wt", newline=""))
            full_writer = csv.writer(full)
            full_writer.writerow(COLUMNS)
        for year in range(2010, 2013):
            name = f"Solar home {year}-{year + 1}.csv"
            start, stop = date(year, 7, 1), date(year + 1, 7, 1)
            records, counts, metadata = read_year(archive, name, start, stop)
            report["years"][str(year)] = audit_year(
                records, counts, metadata, start, stop, full_writer, sample_writer
            )
            del records

    (output / "ausgrid_audit.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
