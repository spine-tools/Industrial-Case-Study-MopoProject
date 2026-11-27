"""Generate a pinned initial_representative_periods_<wy>.csv for TulipaClustering.

WHY THIS EXISTS
---------------
tulipa_call.jl chooses representative days by clustering. With one
representative it picked 12 January - midwinter - which showed solar at 44% of
its annual mean, wind at 246%, and cooling demand at EXACTLY ZERO. The model
then built +32.8 units of onshore wind, zero solar PV and zero batteries. Those
were artefacts of the sample, not results.

Re-clustering with k=2 would not reliably fix this: k=2 can return two
winter/shoulder days and reproduce the same bug. So the days are PINNED here.

tulipa_call.jl picks this file up via its `isfile(initial_path)` branch and
derives the representative count from it, so it also overrides
number_of_representatives.

SCHEMA
------
TulipaClustering's validate_initial_representatives() requires the seed to carry
the SAME key columns and FULL profile rows as the clustering data - not merely a
list of period indices. Periods are renumbered 1..N and timesteps 1..24 within
each period.

COLUMN ORDER MATTERS. validate_df_and_find_key_columns() derives the key columns
POSITIONALLY, as propertynames(df) minus {period, value}, and
validate_initial_representatives() compares the two lists with `!=` - an
ORDER-SENSITIVE comparison. split_into_periods! leaves the clustering data with
key columns [:timestep, :profile_name], so the seed must be written as

    period, timestep, profile_name, value

The intuitive (profile_name, period, timestep, value) yields
[:profile_name, :timestep] and fails with:

    ArgumentError: Key columns of initial represenatives do not match
    clustering data
    Expected was: [:timestep, :profile_name]
    Found was: [:profile_name, :timestep]

USAGE
-----
    .\\.venv\\Scripts\\python.exe tools\\make_cluster_seed.py
    .\\.venv\\Scripts\\python.exe tools\\make_cluster_seed.py --days 12 231
"""

from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLUSTER_DIR = os.path.join(
    REPO, "Pan-European-Framework-Energy-System-Planning", "src", "_clustering"
)
PERIOD_DURATION = 24  # hours; must match number_of_timesteps in tulipa_call.jl

# 12 Jan = the original midwinter medoid; 231 = 19 Aug, the summer day that the
# 3-representative clustering run selected.
DEFAULT_DAYS = [12, 231]
SCENARIO_CONFIG = os.path.join(
    REPO, "Pan-European-Framework-Energy-System-Planning", "src",
    "_planning-input-processsing", "scenario_config.yml")


def config_defaults():
    """representative_days / representative_weather_year from scenario_config.yml."""
    try:
        import yaml
        with open(SCENARIO_CONFIG, encoding="utf8") as fh:
            cfg = yaml.safe_load(fh) or {}
    except (OSError, ImportError):
        cfg = {}
    return (cfg.get("representative_weather_year", "wy2009"),
            [int(d) for d in cfg.get("representative_days", DEFAULT_DAYS)])


def build(weather_year: str, days: list[int]) -> None:
    src = os.path.join(CLUSTER_DIR, "profiles", "profiles_%s.csv" % weather_year)
    dst = os.path.join(
        CLUSTER_DIR, "results", "initial_representative_periods_%s.csv" % weather_year
    )

    with open(src, newline="") as fh:
        rows = list(csv.DictReader(fh))

    names = sorted({r["profile_name"] for r in rows})
    by_key = {(r["profile_name"], int(r["timestep"])): r["value"] for r in rows}
    n_steps = len({int(r["timestep"]) for r in rows})
    max_day = n_steps // PERIOD_DURATION

    for day in days:
        if not 1 <= day <= max_day:
            sys.exit("day %d out of range 1..%d" % (day, max_day))

    out = []
    for new_period, day in enumerate(days, start=1):
        first = (day - 1) * PERIOD_DURATION + 1
        for name in names:
            for offset in range(PERIOD_DURATION):
                key = (name, first + offset)
                if key not in by_key:
                    sys.exit("missing %s timestep %d" % (name, first + offset))
                out.append(
                    {
                        "period": new_period,
                        "timestep": offset + 1,
                        "profile_name": name,
                        "value": by_key[key],
                    }
                )

    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", newline="") as fh:
        # Order is load-bearing - see SCHEMA in the module docstring.
        writer = csv.DictWriter(
            fh, fieldnames=["period", "timestep", "profile_name", "value"]
        )
        writer.writeheader()
        writer.writerows(out)

    print("wrote %d rows -> %s" % (len(out), dst))
    print("  %d periods x %d profiles x %d timesteps" % (len(days), len(names), PERIOD_DURATION))

    # Keep representative_periods.csv in step with the seed.
    #
    # That file is written ONLY by the unseeded branch of tulipa_call.jl, so
    # when we seed, it keeps whatever the LAST unseeded run left behind.
    # clustering_output.py reads it for block_start, so a stale copy silently
    # stamps the representative periods onto the WRONG DAYS: seeding (12, 231)
    # against a stale [12, 49, 231] produced 12 Jan and 18 Feb - two winter
    # days, with the summer day absent - and every other check still passed.
    rp_path = os.path.join(CLUSTER_DIR, "results", "representative_periods.csv")
    with open(rp_path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([weather_year])
        for day in days:
            writer.writerow([day])
    print("wrote %s -> %s" % ([int(d) for d in days], rp_path))

    # Report each pinned day against the annual mean, so an unrepresentative
    # pick is visible immediately rather than after a multi-hour solve.
    annual: dict[str, list[float]] = {}
    for r in rows:
        annual.setdefault(r["profile_name"], []).append(float(r["value"]))

    header = "%-14s %8s" % ("profile", "annual")
    for day in days:
        header += " %9s" % ("day%d" % day)
    print()
    print(header)
    for name in names:
        line = "%-14s %8.4f" % (name[:14], statistics.mean(annual[name]))
        for new_period, _day in enumerate(days, start=1):
            vals = [
                float(r["value"])
                for r in out
                if r["profile_name"] == name and r["period"] == new_period
            ]
            line += " %9.4f" % statistics.mean(vals)
        print(line)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    wy, days = config_defaults()
    ap.add_argument("--weather-year", default=wy)
    ap.add_argument(
        "--days",
        type=int,
        nargs="+",
        default=days,
        help="1-based day-of-year indices to pin (default: %(default)s)",
    )
    args = ap.parse_args()
    build(args.weather_year, args.days)


if __name__ == "__main__":
    main()
