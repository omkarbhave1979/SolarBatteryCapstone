"""Request a small historical ECMWF TIGGE pilot using an authorized ECDS account."""
import argparse
from datetime import date, timedelta
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycle-start", type=date.fromisoformat, default=date(2012, 6, 30))
    parser.add_argument("--days", type=int, choices=range(1, 8), default=3)
    parser.add_argument("--output", type=Path, default=Path("data/raw/tigge/pilot.grib"))
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"Output already exists: {args.output}")
    import cdsapi

    last_cycle = args.cycle_start + timedelta(days=args.days - 1)
    request = {
        "class": "ti",
        "expver": "prod",
        "date": f"{args.cycle_start}/{last_cycle}",
        "origin": "ecmf",
        "type": "cf",
        "levtype": "sfc",
        "param": "167/176/164",
        "step": "12/to/42/by/6",
        "time": "00:00:00",
        "grid": "0.5/0.5",
        "area": "-32/149/-36/153",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".part")
    try:
        cdsapi.Client(url="https://ecds.ecmwf.int/api").retrieve(
            "tigge-forecasts", request, str(temporary)
        )
        with temporary.open("rb") as stream:
            if stream.read(4) != b"GRIB":
                raise ValueError("Expected a GRIB response")
        temporary.replace(args.output)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
