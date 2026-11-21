# Data attribution

The half-hour meter readings come from Ausgrid's *Solar Home Electricity Data*. The README bundled with the [download archive](https://pierreh.eu/ausgrid-solar-data/) identifies the original Ausgrid release as [Creative Commons Attribution 3.0 Australia](https://creativecommons.org/licenses/by/3.0/au/). This is the license notice for the archive used here. The [Australian Government catalog record](https://data.gov.au/data/en/dataset/nsw-solar-home-electricty-data) was inaccessible during verification.

The full processed export reshapes readings into household-interval rows, converts Sydney interval endings to UTC interval starts, excludes documented quality and daylight-saving cases, combines consumption channels, and omits postcode and PV capacity fields. The tracked real sample additionally selects households 1 and 2 for four weeks starting 1 July 2012. Ausgrid does not endorse this project.

| File | Measured size | Repository handling |
| --- | ---: | --- |
| `data/sample/ausgrid_sample.csv` | 103,387 bytes | Tracked with attribution |
| `data/sample/synthetic_meter.csv` | 142,516 bytes | Tracked, generated independently by `src/synthetic_sample.py` |
| `data/processed/ausgrid_sample.csv` | 103,387 bytes | Local, byte-for-byte match of tracked real sample |
| `data/processed/ausgrid_intervals.csv.gz` | 78,488,965 bytes | Tracked with attribution, reproducible from archive |
| `data/raw/ausgrid.zip` | 57,038,633 bytes | Local, original download |

The full gzip is about 74.9 MiB. GitHub warns above 50 MiB and blocks ordinary Git files above 100 MiB. See [GitHub's file limits](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github).
