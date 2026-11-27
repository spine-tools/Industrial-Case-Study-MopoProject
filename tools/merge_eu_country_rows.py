"""Merge country-level (DE/DK/NO/UK) rows from the EU case sector DBs into the
IC1 mixed-resolution sector DBs.

Only entities whose terminal name component is one of the target countries are
copied, together with their parameter values. All existing IC1 (BEC*/NLC*) rows
are left untouched, so BE/NL input is identical between the 17-region and the
21-region runs.

Why a direct SQL merge is safe here: ines_target.spatial_transformation takes
the direct-lookup branch when source_level == target_level, querying by
entity_byname. The EU DBs already store regions as plain 'DE'/'UK' and
composites as '<x>__DE', which is exactly what define_polygons emits for our
country-level polygons. No aggregation path is involved.

Source data: the sector databases of the Pan-European dataset
(https://doi.org/10.5281/zenodo.23496362, v0.6), which ships them already built
in .spinetoolbox/items/<sector>_db/. Unzip it into
Pan-European_Energy_System_Dataset/ in the repository root, or point
`eu_case_dir` in data-pipelines/europe/userconfig.yaml at its items folder.

Countries: every entry of `countries` in userconfig.yaml except BE and NL.

Usage:
    python tools/merge_eu_country_rows.py --apply   # copy rows (idempotent)
    python tools/merge_eu_country_rows.py --check   # exit 1 if rows are missing
"""
import argparse
import os
import sqlite3
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USERCONFIG = os.path.join(ROOT, "data-pipelines", "europe", "userconfig.yaml")
IC1_COUNTRIES = ("BE", "NL")  # modelled at cluster level by the IC1 importers


def load_config():
    with open(USERCONFIG, encoding="utf8") as fh:
        cfg = yaml.safe_load(fh)
    # Unquoted NO is parsed by YAML 1.1 as False; map it back defensively.
    ctry = ["NO" if c is False else str(c) for c in cfg.get("countries", [])]
    eu_dir = cfg.get("eu_case_dir", "Pan-European_Energy_System_Dataset/.spinetoolbox/items")
    if not os.path.isabs(eu_dir):
        eu_dir = os.path.join(ROOT, eu_dir)
    return tuple(c for c in ctry if c not in IC1_COUNTRIES), os.path.normpath(eu_dir)


COUNTRIES, EU_DIR = load_config()

# EU pipeline vs IC1 pipeline disagree on these names. IC1 userconfig.yaml and
# the IC1 DBs use an underscore before "production"; the EU DBs use a hyphen.
# Copying verbatim would create entities the rest of the config never matches.
NAME_FIXUPS = {
    "wood-and-wood-products-production-alternative": "wood-and-wood-products_production-alternative",
    "wood-and-wood-products-production-reference": "wood-and-wood-products_production-reference",
}

# (label, target DB in this project, source DB in the EU case items folder)
PAIRS = [
    ("heat_db",
     os.path.join(ROOT, ".spinetoolbox", "items", "heat_db", "heat_db.sqlite"),
     os.path.join(EU_DIR, "heat_db", "heat_db.sqlite")),
    ("transport_db",
     os.path.join(ROOT, ".spinetoolbox", "items", "transport_db", "transport_db.sqlite"),
     os.path.join(EU_DIR, "transport_db", "transport_db.sqlite")),
    ("industry_db",
     os.path.join(ROOT, ".spinetoolbox", "items", "industry_db", "industry_db.sqlite"),
     os.path.join(EU_DIR, "industry_db", "industry_db.sqlite")),
    ("other_industry_db",
     os.path.join(ROOT, ".spinetoolbox", "items", "other_industry_db", "Other_Industry_DB.sqlite"),
     os.path.join(EU_DIR, "other_industry_db", "Other_Industry_DB.sqlite")),
    ("hydro_db",
     os.path.join(ROOT, ".spinetoolbox", "items", "hydro_db", "hydro_db.sqlite"),
     os.path.join(EU_DIR, "hydro_db", "hydro_db.sqlite")),
]


def fix_name(name):
    for bad, good in NAME_FIXUPS.items():
        if bad in name:
            name = name.replace(bad, good)
    return name


def is_target(name):
    """True if the entity belongs to one of the target countries.

    Region entities are the bare country code; composite entities carry the
    country as the final '__'-separated component.
    """
    if name in COUNTRIES:
        return True
    return name.split("__")[-1] in COUNTRIES


def read_source(path):
    con = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
    cur = con.cursor()
    classes = {r[0]: r[1] for r in cur.execute("SELECT id, name FROM entity_class")}
    alts = {r[0]: r[1] for r in cur.execute("SELECT id, name FROM alternative")}
    pdefs = {}
    for pid, ecid, pname in cur.execute(
            "SELECT id, entity_class_id, name FROM parameter_definition"):
        pdefs[pid] = (classes[ecid], pname)
    ents = {}
    for eid, cid, name in cur.execute("SELECT id, class_id, name FROM entity"):
        ents[eid] = (classes[cid], name)
    elements = {}
    for eid, elid, pos in cur.execute(
            "SELECT entity_id, element_id, position FROM entity_element"):
        elements.setdefault(eid, []).append((pos, elid))
    values = list(cur.execute(
        "SELECT parameter_definition_id, entity_id, alternative_id, type, value "
        "FROM parameter_value"))
    con.close()
    return classes, alts, pdefs, ents, elements, values


def merge(label, target_path, source_path, apply_changes):
    """Return the number of source rows still missing in the target."""
    s_classes, s_alts, s_pdefs, s_ents, s_elements, s_values = read_source(source_path)

    con = sqlite3.connect(target_path)
    cur = con.cursor()
    t_classes = {r[1]: r[0] for r in cur.execute("SELECT id, name FROM entity_class")}
    t_alts = {r[1]: r[0] for r in cur.execute("SELECT id, name FROM alternative")}
    t_pdefs = {}
    id_to_class = {v: k for k, v in t_classes.items()}
    for pid, ecid, pname in cur.execute(
            "SELECT id, entity_class_id, name FROM parameter_definition"):
        t_pdefs[(id_to_class[ecid], pname)] = pid
    t_ents = {}
    for eid, cid, name in cur.execute("SELECT id, class_id, name FROM entity"):
        t_ents[(id_to_class[cid], name)] = eid

    wanted = {eid: (cls, fix_name(nm)) for eid, (cls, nm) in s_ents.items()
              if is_target(nm)}

    # Composite entities reference 0-dimensional parents (commodity, vehicle,
    # technology, end-use) that carry no country suffix and so are not matched
    # by is_target(). Some of those parents exist only in the EU DB -- e.g.
    # vehicle 'van', 'maritime-NH3' and commodity 'MeOH', 'NH3'. Pull in any
    # parent that the target DB does not already have, otherwise the composite
    # is written with an incomplete entity_element row set and its parameter
    # values dangle. Resolve transitively.
    pending = list(wanted)
    while pending:
        sid = pending.pop()
        for _pos, elid in s_elements.get(sid, []):
            if elid in wanted:
                continue
            e_cls, e_nm = s_ents[elid]
            wanted[elid] = (e_cls, fix_name(e_nm))
            pending.append(elid)

    missing_cls = sorted({cls for cls, _ in wanted.values()} - set(t_classes))
    needed_alts = sorted({s_alts[v[2]] for v in s_values if v[1] in wanted}
                         - set(t_alts))
    needed_pdefs = sorted({s_pdefs[v[0]] for v in s_values if v[1] in wanted}
                          - set(t_pdefs))

    pre_total = cur.execute("SELECT count(*) FROM parameter_value").fetchone()[0]
    pre_ents = cur.execute("SELECT count(*) FROM entity").fetchone()[0]
    new_ents = [e for e in wanted.items() if (e[1][0], e[1][1]) not in t_ents]
    n_vals = sum(1 for v in s_values if v[1] in wanted)

    print("  %-18s src_ents=%-6d match=%-5d new_ents=%-5d vals=%-6d "
          "missing_class=%s missing_alt=%s missing_pdef=%s"
          % (label, len(s_ents), len(wanted), len(new_ents), n_vals,
             missing_cls or "-", needed_alts or "-", needed_pdefs or "-"))

    if not apply_changes:
        t_vals = set(cur.execute(
            "SELECT parameter_definition_id, entity_id, alternative_id FROM parameter_value"))
        miss_v = 0
        for pdid, seid, saltid, _t, _v in s_values:
            if seid not in wanted:
                continue
            cls, nm = wanted[seid]
            key = (t_pdefs.get(s_pdefs[pdid]), t_ents.get((cls, nm)), t_alts.get(s_alts[saltid]))
            if None in key or key not in t_vals:
                miss_v += 1
        con.close()
        print("     missing in target: entities=%d values=%d" % (len(new_ents), miss_v))
        return len(new_ents) + miss_v

    if missing_cls:
        print("     ABORT: entity classes absent in target: %s" % missing_cls)
        con.close()
        return 1

    for name in needed_alts:
        cur.execute("INSERT INTO alternative (name) VALUES (?)", (name,))
        t_alts[name] = cur.lastrowid
    for cls, pname in needed_pdefs:
        cur.execute("INSERT INTO parameter_definition (entity_class_id, name) "
                    "VALUES (?, ?)", (t_classes[cls], pname))
        t_pdefs[(cls, pname)] = cur.lastrowid

    # 1. entities (0-dim first so composites can reference them)
    order = sorted(wanted.items(), key=lambda kv: len(s_elements.get(kv[0], [])))
    id_map = {}
    for sid, (cls, name) in order:
        key = (cls, name)
        if key in t_ents:
            id_map[sid] = t_ents[key]
            continue
        cur.execute("INSERT INTO entity (class_id, name) VALUES (?, ?)",
                    (t_classes[cls], name))
        id_map[sid] = cur.lastrowid
        t_ents[key] = id_map[sid]

    # 2. entity_element rows for composites
    t_dims = {}
    for ecid, did, pos in cur.execute(
            "SELECT entity_class_id, dimension_id, position FROM entity_class_dimension"):
        t_dims[(ecid, pos)] = did
    el_rows = 0
    for sid, (cls, _name) in wanted.items():
        els = s_elements.get(sid)
        if not els:
            continue
        tid = id_map[sid]
        if cur.execute("SELECT count(*) FROM entity_element WHERE entity_id=?",
                       (tid,)).fetchone()[0]:
            continue
        ecid = t_classes[cls]
        for pos, s_elid in sorted(els):
            s_cls, s_nm = s_ents[s_elid]
            t_elid = t_ents.get((s_cls, fix_name(s_nm)))
            if t_elid is None:
                print("     WARN unresolved element %s/%s for %s" % (s_cls, s_nm, _name))
                continue
            cur.execute("INSERT INTO entity_element (entity_id, entity_class_id, "
                        "element_id, dimension_id, position) VALUES (?,?,?,?,?)",
                        (tid, ecid, t_elid, t_dims[(ecid, pos)], pos))
            el_rows += 1

    # 3. parameter values
    v_rows = 0
    for pdid, seid, saltid, vtype, vblob in s_values:
        if seid not in wanted:
            continue
        cls, pname = s_pdefs[pdid]
        tpd = t_pdefs[(cls, pname)]
        teid = id_map[seid]
        taid = t_alts[s_alts[saltid]]
        if cur.execute("SELECT count(*) FROM parameter_value WHERE "
                       "parameter_definition_id=? AND entity_id=? AND alternative_id=?",
                       (tpd, teid, taid)).fetchone()[0]:
            continue
        cur.execute("INSERT INTO parameter_value (parameter_definition_id, entity_id, "
                    "entity_class_id, type, value, alternative_id) VALUES (?,?,?,?,?,?)",
                    (tpd, teid, t_classes[cls], vtype,
                     sqlite3.Binary(vblob) if vblob is not None else None, taid))
        v_rows += 1

    con.commit()
    post_total = cur.execute("SELECT count(*) FROM parameter_value").fetchone()[0]
    post_ents = cur.execute("SELECT count(*) FROM entity").fetchone()[0]
    con.close()
    print("     APPLIED entities %d->%d  elements+%d  values %d->%d"
          % (pre_ents, post_ents, el_rows, pre_total, post_total))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.check):
        ap.error("pass --check or --apply")
    print("MERGE EU country rows (%s) countries=%s" % ("APPLY" if args.apply else "CHECK", ",".join(COUNTRIES)))
    print("  EU case items folder: %s" % EU_DIR)
    if not COUNTRIES:
        print("  no countries besides BE/NL in userconfig.yaml -> nothing to do")
        return 0
    absent = [p for _l, t, p in PAIRS if not os.path.exists(p)] + \
             [t for _l, t, p in PAIRS if not os.path.exists(t)]
    if absent:
        print("ERROR: missing database(s):\n  " + "\n  ".join(absent))
        print("Run this project's importers first, and run the EU case data-preparation\n"
              "pipelines so its sector databases exist; set `eu_case_dir` in userconfig.yaml.")
        return 2
    missing = 0
    for label, tgt, src in PAIRS:
        missing += merge(label, tgt, src, args.apply) or 0
    if args.check and missing:
        print("CHECK FAILED: %d rows missing" % missing)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
