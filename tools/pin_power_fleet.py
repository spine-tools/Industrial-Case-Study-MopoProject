"""
pin_power_fleet.py - freeze Power_DB to the vre15 baseline fleet.

Why: power_DB.py assigns existing-plant retirement years with an unseeded
random.choice (see docs/FINDING_random_retirement_dates.md). Every pipeline run
therefore produces a different existing fleet, with multi-GW swings in exactly
the technologies our conclusions rest on (BE nuclear, NL coal). That noise is
larger than the mixed-resolution effect we want to measure.

This tool does NOT fix the root cause. It makes the power sector a *controlled
variable*: after running power_importer, overwrite the units_existing series in
Power_DB with the exact values used by the vre15 run, so any difference in the
mixed-resolution results is attributable to resolution, not to a random draw.

Usage:
    python tools/pin_power_fleet.py --check
    python tools/pin_power_fleet.py --apply

Source of truth:
    backups/spinetoolbox-items-pre-mixedres/items/power_db/power_db.sqlite
    (verified byte-identical entity set to the vre15 model: 201 existing units)
"""
import argparse
import json
import os
import sqlite3
import sys

PARAM = "units_existing"
SRC = "data-pipelines/europe/_power/power_fleet_pin.json"
LEGACY_SRC = "backups/spinetoolbox-items-pre-mixedres/items/power_db/power_db.sqlite"
DST = ".spinetoolbox/items/power_db/power_db.sqlite"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _abs(p):
    return p if os.path.isabs(p) else os.path.join(ROOT, p)


def read_series(path):
    """Return {(param, entity, alternative): (value_blob, type)}."""
    if not os.path.exists(path):
        sys.exit("missing database: %s" % path)
    if path.endswith(".json"):
        with open(path, encoding="utf-8") as fh:
            rows = json.load(fh)["series"]
        return {(PARAM, r["entity"], r["alternative"]): (r["value"].encode("utf-8"), r["type"])
                for r in rows}
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    rows = con.execute(
        """SELECT pd.name, e.name, a.name, pv.value, pv.type
           FROM parameter_value pv
           JOIN parameter_definition pd ON pd.id = pv.parameter_definition_id
           JOIN entity e ON e.id = pv.entity_id
           JOIN alternative a ON a.id = pv.alternative_id
           WHERE pd.name = ?""", (PARAM,)).fetchall()
    con.close()
    return {(r[0], r[1], r[2]): (r[3], r[4]) for r in rows}


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--export", metavar="JSON",
                   help="write the series of --src (sqlite) to a committed JSON pin file")
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--dst", default=DST)
    args = ap.parse_args()
    args.src, args.dst = _abs(args.src), _abs(args.dst)

    if args.export:
        src = args.src if args.src.endswith(".sqlite") else _abs(LEGACY_SRC)
        ser = read_series(src)
        out = {"parameter": PARAM, "source": src, "series": [
            {"entity": k[1], "alternative": k[2], "type": v[1],
             "value": v[0].decode("utf-8") if isinstance(v[0], bytes) else v[0]}
            for k, v in sorted(ser.items())]}
        with open(args.export, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(out, fh, indent=1)
        print("exported %d series to %s" % (len(ser), args.export))
        return 0

    src = read_series(args.src)
    dst = read_series(args.dst)
    print("source series: %d" % len(src))
    print("target series: %d" % len(dst))

    missing = sorted(set(src) - set(dst))
    extra = sorted(set(dst) - set(src))
    shared = sorted(set(src) & set(dst))
    differing = [k for k in shared if src[k][0] != dst[k][0]]

    print("only in source : %d" % len(missing))
    print("only in target : %d" % len(extra))
    print("shared         : %d" % len(shared))
    print("DIFFERING      : %d" % len(differing))
    for k in differing[:10]:
        print("    %s | %s" % (k[1], k[2]))
    if len(differing) > 10:
        print("    ... and %d more" % (len(differing) - 10))

    if missing:
        print()
        print("WARNING: %d series exist in the baseline but not in the current" % len(missing))
        print("Power_DB. Entities differ, so a value-only pin is incomplete.")
        for k in missing[:10]:
            print("    %s" % (k[1],))

    if args.check:
        print()
        print("CHECK ONLY - nothing written.")
        return 0 if not differing and not missing else 1

    if not differing:
        print()
        print("nothing to do - already pinned.")
        return 0

    con = sqlite3.connect(args.dst)
    n = 0
    for k in differing:
        val, typ = src[k]
        cur = con.execute(
            """UPDATE parameter_value SET value = ?, type = ?
               WHERE id = (
                 SELECT pv.id FROM parameter_value pv
                 JOIN parameter_definition pd ON pd.id = pv.parameter_definition_id
                 JOIN entity e ON e.id = pv.entity_id
                 JOIN alternative a ON a.id = pv.alternative_id
                 WHERE pd.name = ? AND e.name = ? AND a.name = ?)""",
            (sqlite3.Binary(val) if isinstance(val, bytes) else val, typ,
             k[0], k[1], k[2]))
        n += cur.rowcount
    con.commit()
    con.close()
    print()
    print("updated %d rows" % n)

    after = read_series(args.dst)
    bad = [k for k in set(src) & set(after) if src[k][0] != after[k][0]]
    print("VERIFY: differing after write = %d  -> %s"
          % (len(bad), "PASS" if not bad else "FAIL"))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
