import spinedb_api as api
from spinedb_api import DatabaseMapping
import sys
import os
import pandas as pd
import numpy as np
import json
import yaml
from typing import Optional

TARGET_RESOLUTION = "ic1"
SOURCE_RESOLUTION_PRIORITY = ["nuts3", "nuts1", "nuts0"]

def add_entity(db_map : DatabaseMapping, class_name : str, element_names : tuple) -> None:
    _, error = db_map.add_entity_item(entity_byname=element_names, entity_class_name=class_name)
    if error is not None:
        raise RuntimeError(error)

def add_parameter_value(db_map : DatabaseMapping,class_name : str,parameter : str,alternative : str,elements : tuple,value : any) -> None:
    db_value, value_type = api.to_database(value)
    _, error = db_map.add_parameter_value_item(entity_class_name=class_name,entity_byname=elements,parameter_definition_name=parameter,alternative_name=alternative,value=db_value,type=value_type)
    if error:
        raise RuntimeError(error)

def add_alternative(db_map : DatabaseMapping,name_alternative : str) -> None:
    _, error = db_map.add_alternative_item(name=name_alternative)
    if error is not None:
        raise RuntimeError(error)

def warn(msg: str) -> None:
    print(f"WARNING: {msg}")

def add_entity_if_missing(db_map: DatabaseMapping, class_name: str, element_names: tuple) -> None:
    try:
        add_entity(db_map, class_name, element_names)
    except RuntimeError as e:
        # Keep the pipeline robust for repeated writes while still surfacing real errors.
        msg = str(e).lower()
        if not ("already" in msg or "duplicate" in msg or "unique" in msg):
            raise

def find_column_case_insensitive(df: pd.DataFrame, candidates: list) -> Optional[str]:
    lower_lookup = {str(c).lower(): c for c in df.columns}
    for candidate in candidates:
        hit = lower_lookup.get(candidate.lower())
        if hit is not None:
            return hit
    return None

def detect_resolution_from_sheet_name(sheet_name: str) -> Optional[str]:
    lower_name = sheet_name.lower()
    for res in [TARGET_RESOLUTION] + SOURCE_RESOLUTION_PRIORITY:
        if lower_name.endswith(f"_{res}"):
            return res
    return None

def pick_sheet_for_prefix(sheet_dict: dict, prefix: str):
    lower_to_original = {name.lower(): name for name in sheet_dict.keys()}

    target_name = f"{prefix}_{TARGET_RESOLUTION}".lower()
    if target_name in lower_to_original:
        return lower_to_original[target_name], TARGET_RESOLUTION, False

    for source_resolution in SOURCE_RESOLUTION_PRIORITY:
        source_name = f"{prefix}_{source_resolution}".lower()
        if source_name in lower_to_original:
            return lower_to_original[source_name], source_resolution, True

    warn(f"No sheet found for prefix '{prefix}' with expected suffixes ({TARGET_RESOLUTION}/nuts3/nuts1/nuts0).")
    return None, None, False

def load_region_transformations_to_ic1(file_path: str) -> dict:
    if not os.path.exists(file_path):
        warn(f"Region transformation file not found: {file_path}. IC1 fallback transformation disabled.")
        return {}

    transform_sheets = pd.read_excel(file_path, sheet_name=None)
    lower_sheet_lookup = {name.lower(): name for name in transform_sheets.keys()}

    transformations = {}
    for source_resolution in SOURCE_RESOLUTION_PRIORITY:
        sheet_key = f"{source_resolution}_{TARGET_RESOLUTION}".lower()
        original_sheet_name = lower_sheet_lookup.get(sheet_key)
        if original_sheet_name is None:
            continue

        map_df = transform_sheets[original_sheet_name].copy()
        source_col = find_column_case_insensitive(map_df, ["source"])
        target_col = find_column_case_insensitive(map_df, ["target"])
        if source_col is None or target_col is None:
            warn(f"Sheet '{original_sheet_name}' is missing 'source'/'target' columns and will be ignored.")
            continue

        map_df = map_df[[source_col, target_col]].rename(columns={source_col: "source", target_col: "target"})
        map_df["source"] = map_df["source"].astype(str).str.strip()
        map_df["target"] = map_df["target"].astype(str).str.strip()
        map_df = map_df[(map_df["source"] != "") & (map_df["target"] != "")]
        map_df = map_df.drop_duplicates()
        transformations[source_resolution] = map_df

    return transformations

def get_region_column_for_resolution(df: pd.DataFrame, resolution: str) -> Optional[str]:
    if resolution == "nuts0":
        return find_column_case_insensitive(df, ["nuts0", "country_code"])
    return find_column_case_insensitive(df, [resolution])

def normalize_sheet_to_ic1(df: pd.DataFrame, source_resolution: str, transformations: dict, numeric_columns: list, context_name: str) -> pd.DataFrame:
    out_df = df.copy()
    region_col = get_region_column_for_resolution(out_df, source_resolution)
    if region_col is None:
        warn(f"[{context_name}] Could not find a region column for '{source_resolution}'. Skipping this dataset.")
        return pd.DataFrame(columns=list(df.columns) + [TARGET_RESOLUTION])

    out_df[region_col] = out_df[region_col].astype(str).str.strip()

    if source_resolution == TARGET_RESOLUTION:
        if region_col != TARGET_RESOLUTION:
            out_df[TARGET_RESOLUTION] = out_df[region_col]
        return out_df

    map_df = transformations.get(source_resolution)
    if map_df is None:
        warn(f"[{context_name}] Missing mapping sheet for '{source_resolution}_ic1'. Skipping this dataset.")
        return pd.DataFrame(columns=list(df.columns) + [TARGET_RESOLUTION])

    mapped = out_df.merge(map_df, how="left", left_on=region_col, right_on="source")
    unmapped = mapped["target"].isna()
    if unmapped.any():
        missing_regions = sorted(mapped.loc[unmapped, region_col].dropna().astype(str).unique().tolist())
        warn(f"[{context_name}] {len(missing_regions)} regions could not be mapped to IC1 and will be dropped. Examples: {missing_regions[:10]}")
        mapped = mapped[~unmapped].copy()

    split_count = map_df.groupby("source")["target"].nunique().to_dict()
    mapped["_split"] = mapped[region_col].map(split_count).fillna(1.0).astype(float)

    for col in numeric_columns:
        if col in mapped.columns:
            mapped[col] = pd.to_numeric(mapped[col], errors="coerce") / mapped["_split"]

    mapped[TARGET_RESOLUTION] = mapped["target"]
    mapped = mapped.drop(columns=["source", "target", "_split"], errors="ignore")
    return mapped

def warn_material_mismatches(sheet_dict: dict) -> None:
    materials = {}
    for name, df in sheet_dict.items():
        if df is None or df.empty:
            materials[name] = set()
            continue
        if "Industry" not in df.columns:
            warn(f"[{name}] Missing 'Industry' column; skipping material consistency checks for this sheet.")
            materials[name] = set()
            continue
        mat_set = set(df["Industry"].astype(str).str.strip().tolist())
        mat_set.discard("")
        materials[name] = mat_set

    names = list(materials.keys())
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            only_a = sorted(list(materials[a] - materials[b]))
            only_b = sorted(list(materials[b] - materials[a]))
            if only_a:
                warn(f"Materials in {a} but not in {b}: {only_a[:10]} (total {len(only_a)})")
            if only_b:
                warn(f"Materials in {b} but not in {a}: {only_b[:10]} (total {len(only_b)})")

def add_tech_parameters(target_db,industry,node,sheets):

    planning_years =  ["2030","2040","2050"]
    # lifetime
    entity_name = "technology"
    entity_byname = (industry,)
    df = sheets["ind_process_route_life"]
    value_life = df[(df.Industry==industry)]["life"].tolist()[0]
    add_parameter_value(target_db, entity_name, "lifetime", "Base", entity_byname, value_life)

    # capex
    entity_name = "technology__to_commodity"
    entity_byname = (industry,node)
    df = sheets["ind_process_routes_capex"]
    array_p = (df[(df.Industry==industry)][planning_years].values.flatten().round(2)*8760.0).tolist()
    print(array_p)
    param_type = "map" if not all(array_p[0] == i for i in array_p) else "float"
    print(param_type,industry)
    if array_p[0] > 0.0:
        if param_type == "map":
            value_param =  dict(zip([f"y{year}" for year in planning_years],array_p))
            map_param = {"type": "map", "index_type": "str", "index_name": "period", "data": value_param}
            add_parameter_value(target_db, entity_name, "investment_cost", "Base", entity_byname, map_param)
        elif param_type == "float":
            add_parameter_value(target_db, entity_name, "investment_cost", "Base", entity_byname, array_p[0])

    # fom
    entity_name = "technology__to_commodity"
    entity_byname = (industry,node)
    df = sheets["ind_process_routes_fom"]
    array_p = (df[(df.Industry==industry)][planning_years].values.flatten().round(2)*8760.0).tolist()
    param_type = "map" if not all(array_p[0] == i for i in array_p) else "float"
    if array_p[0] > 0.0:
        if param_type == "map":
            value_param =  dict(zip([f"y{year}" for year in planning_years],array_p))
            map_param = {"type": "map", "index_type": "str", "index_name": "period", "data": value_param}
            add_parameter_value(target_db, entity_name, "fixed_cost", "Base", entity_byname, map_param)
        elif param_type == "float":
            add_parameter_value(target_db, entity_name, "fixed_cost", "Base", entity_byname, array_p[0])


    # co2_captured
    df = sheets["ind_process_routes_co2_capture"]   
    value_param = {f"y{year}":df[(df.Industry==industry)][year].tolist()[0] for year in planning_years}
    if value_param["y2030"] > 0.0:
        entity_name = "technology__to_commodity"
        entity_byname = (industry,"CO2")
        add_entity(target_db, entity_name, entity_byname)
        entity_name = "technology__to_commodity__to_commodity"
        entity_byname = (industry,node,"CO2")
        add_entity(target_db, entity_name, entity_byname)
        map_param = {"type": "map", "index_type": "str", "index_name": "period", "data": value_param}
        add_parameter_value(target_db, entity_name, "CO2_captured", "Base", entity_byname, np.array(list(value_param.values())).mean().round(3))

def conversion_sectors(target_db,sheet,com_sheet,nodes):

    for i in list(set(sheet.from_node.unique().tolist() + sheet.to_node.unique().tolist())):
        condition = False
        if i in sheet.from_node.unique().tolist():
            condition = True
        else:
            if i in nodes:
                condition = True
        if condition:
            entity_name = "commodity"
            entity_byname = (i,)
            add_entity(target_db, entity_name, entity_byname)

    for i in sheet.index:

        if sheet.at[i,"to_node"] in nodes:
            try:
                entity_name = "technology"
                entity_byname = (sheet.at[i,"Industry"],)
                add_entity(target_db, entity_name, entity_byname)
                entity_name = "technology__to_commodity"
                entity_byname = (sheet.at[i,"Industry"],sheet.at[i,"to_node"])
                add_entity(target_db, entity_name, entity_byname)
                add_parameter_value(target_db, entity_name, "capacity", "Base", entity_byname,1.0)
                add_tech_parameters(target_db,sheet.at[i,"Industry"],sheet.at[i,"to_node"],com_sheet)
            except:
                print("error conversion")
                pass

            value_dict = {f"y{year}":1/sheet.at[i,year] for year in ["2030","2040","2050"]}
            entity_name = "commodity__to_technology__to_commodity"
            entity_byname = (sheet.at[i,"from_node"],sheet.at[i,"Industry"],sheet.at[i,"to_node"])
            if value_dict["y2030"] > 0.0:
                add_entity(target_db, entity_name, entity_byname)
                map_param = {"type": "map", "index_type": "str", "index_name": "period", "data": value_dict}
                add_parameter_value(target_db, entity_name, "conversion_rate", "Base", entity_byname, np.array(list(value_dict.values())).mean().round(3))
                entity_name = "commodity__to_technology"
                entity_byname = (sheet.at[i,"from_node"],sheet.at[i,"Industry"])
                add_entity(target_db, entity_name, entity_byname)

#old
#def capacity_sectors(target_db,sheet,nodes):
#
#    for i in sheet.index:
#
#        if sheet.at[i,"to_node"] in nodes:
#            print("node:",sheet.at[i,"to_node"])
#            entity_name = "region"
#            poly_column = "ic1" if "ic1" in sheet.columns else "country_code"
#            poly_name = sheet.at[i,poly_column] 
#            entity_byname = (poly_name,)
#            try:
#                add_entity(target_db, entity_name, entity_byname)
#            except:
#                pass
#
#            entity_name = "technology__region"
#            entity_byname = (sheet.at[i,"Industry"],poly_name)
#            print(entity_name, entity_byname)
#            add_entity(target_db, entity_name, entity_byname)
#            add_parameter_value(target_db, entity_name, "units_existing", "Base", entity_byname, {"type": "map", "index_type": "str", "index_name": "period", "data": {"y2030":sheet.at[i,"2018"]*1000.0/8760.0 if "kt" in sheet.at[i,"unit"] else sheet.at[i,"2018"]/8760.0}})

def capacity_sectors(target_db, sheet, nodes, region_column=TARGET_RESOLUTION):
    """
    Creates technology__region entities and writes units_existing.
    For ic1 resolution (and others), sums duplicate rows that map to the same (Industry, region).
    """

    required_cols = {"to_node", "Industry", "unit", "2018", region_column}
    if sheet is None or sheet.empty:
        warn("capacity_sectors: input sheet is empty. Skipping capacity write.")
        return
    missing_cols = [c for c in required_cols if c not in sheet.columns]
    if missing_cols:
        warn(f"capacity_sectors: missing columns {missing_cols}. Skipping capacity write.")
        return

    # filter to only rows relevant for the selected nodes
    df = sheet[sheet["to_node"].isin(nodes)].copy()

    poly_column = region_column
    if poly_column not in df.columns:
        warn(f"capacity_sectors: region column '{poly_column}' missing. Skipping capacity write.")
        return

    # normalize keys (otherwise mismatch might happen due to whitespace)
    df["Industry"] = df["Industry"].astype(str).str.strip()
    df[poly_column] = df[poly_column].astype(str).str.strip()

    # compute the y2030 values (same as original pipeline)
    unit_is_kt = df["unit"].astype(str).str.contains("kt", na=False)
    df["_y2030"] = np.where(
        unit_is_kt,
        df["2018"].astype(float) * 1000.0 / 8760.0,
        df["2018"].astype(float) / 8760.0
    )

    # aggregate duplicates (otherwise pipeline breaks, one unique match per region-tech)
    grouped = df.groupby(["Industry", poly_column], as_index=False)["_y2030"].sum()
    print("capacity_sectors: rows before =", len(df), "after grouping =", len(grouped))
    
    # write entities + parameter values once per group
    for _, row in grouped.iterrows():
        tech = row["Industry"]
        region = row[poly_column]
        y2030_value = float(row["_y2030"])

        # region entity
        add_entity_if_missing(target_db, "region", (region,))

        # Ensure parent technology exists even if conversion sheet differs from capacity materials.
        add_entity_if_missing(target_db, "technology", (tech,))

        # technology__region entity
        add_entity_if_missing(target_db, "technology__region", (tech, region))

        # units_existing parameter
        add_parameter_value(
            target_db,
            "technology__region",
            "units_existing",
            "Base",
            (tech, region),
            {
                "type": "map",
                "index_type": "str",
                "index_name": "period",
                "data": {"y2030": y2030_value},
            },
        )

# old
#def demand_sectors(target_db,sheet,nodes):
#
#    for i in sheet.index:
#        if sheet.at[i,"to_node"] in nodes:
#            print("node:",sheet.at[i,"to_node"])
#            entity_name = "region"
#            poly_column = "ic1" if "ic1" in sheet.columns else "country_code"
#            poly_name = sheet.at[i,poly_column] 
#            entity_byname = (poly_name,)
#            try:
#                add_entity(target_db, entity_name, entity_byname)
#            except:
#                pass
#
#            if sheet.at[i,"to_node"] not in []:
#                entity_name = "commodity__region"
#                entity_byname = (sheet.at[i,"to_node"],poly_name)
#                add_entity(target_db, entity_name, entity_byname)
#                multiplier = 1000.0/8760.0 if "kt" in sheet.at[i,"unit"] else 1/8760.0
#                map_param = {"type": "map", "index_type": "str", "index_name": "year", "data": {"y2030":None,"y2040":None,"y2050":None}}
#                map_param["data"]["y2030"] = -1*multiplier*float(sheet.at[i,"2030"])
#                map_param["data"]["y2050"] = -1*multiplier*float(sheet.at[i,"2050"])
#                map_param["data"]["y2040"] = (map_param["data"]["y2030"] + map_param["data"]["y2050"])/2
#                if sheet.at[i,"to_node"] != "HC":
#                    add_parameter_value(target_db, entity_name, "demand", "Base", entity_byname, -1*multiplier*float(sheet.at[i,"2030"])) # same demand for every year

def demand_sectors(target_db, sheet, nodes, region_column=TARGET_RESOLUTION):

    required_cols = {"to_node", "unit", "2030", "2050", region_column}
    if sheet is None or sheet.empty:
        warn("demand_sectors: input sheet is empty. Skipping demand write.")
        return
    missing_cols = [c for c in required_cols if c not in sheet.columns]
    if missing_cols:
        warn(f"demand_sectors: missing columns {missing_cols}. Skipping demand write.")
        return

    # filter to relevant nodes
    df = sheet[sheet["to_node"].isin(nodes)].copy()

    poly_column = region_column
    if poly_column not in df.columns:
        warn(f"demand_sectors: region column '{poly_column}' missing. Skipping demand write.")
        return

    # normalize keys, same as function capacity_sectors
    df["to_node"] = df["to_node"].astype(str).str.strip()
    df[poly_column] = df[poly_column].astype(str).str.strip()

    # calculate demand values using logic from original pipeline
    # multiplier: kt -> 1000/8760, else 1/8760
    unit_is_kt = df["unit"].astype(str).str.contains("kt", na=False)
    multiplier = np.where(unit_is_kt, 1000.0 / 8760.0, 1.0 / 8760.0)

    # negative demand
    df["_d2030"] = -multiplier * df["2030"].astype(float)
    df["_d2050"] = -multiplier * df["2050"].astype(float)
    df["_d2040"] = (df["_d2030"] + df["_d2050"]) / 2.0

    # prevent duplicates, same as function capacity_sectors
    grouped = (
        df.groupby(["to_node", poly_column], as_index=False)[["_d2030", "_d2040", "_d2050"]]
        .sum()
    )

    # write entities + parameter values once per group
    for _, row in grouped.iterrows():
        commodity = row["to_node"]
        region = row[poly_column]

        # region entity
        add_entity_if_missing(target_db, "region", (region,))

        # commodity__region entity (unique now)
        entity_name = "commodity__region"
        entity_byname = (commodity, region)
        add_entity_if_missing(target_db, entity_name, entity_byname)

        # same as original pipeline -> write only the 2030 value
        # original pipeline: "same demand for every year"
        # original pipeline: HC is exception
        if commodity != "HC":
            add_parameter_value(
                target_db,
                entity_name,
                "demand",
                "Base",
                entity_byname,
                float(row["_d2030"]),
            )

def add_scenario(db_map : DatabaseMapping,name_scenario : str) -> None:
    _, error = db_map.add_scenario_item(name=name_scenario)
    if error is not None:
        raise RuntimeError(error)

def commit_session_safe(db_map: DatabaseMapping, message: str) -> None:
    try:
        db_map.commit_session(message)
    except Exception as e:
        if "NothingToCommit" in e.__class__.__name__:
            print(f"Nothing to commit for '{message}'. Continuing...")
        else:
            raise
    
def remove_items(db_map : DatabaseMapping):
    for entity_name in ["steam","heat"]:
        for entity_map in db_map.get_entity_items(entity_class_name="commodity",name=entity_name):
            item_id = entity_map["id"]
            db_map.remove_item("entity",item_id)

def main():

    # Spine Inputs
    dbs_dict = {
        "part1" : [sys.argv[1],"ic1",
                   ["cement","chemical-chlorine","chemical-olefins","chemical-PE","chemical-PEA",
                    "fertiliser-ammonia-NH3","glass-container","glass-fibre","glass-float",
                    "HC","steel-primary","steel-secondary","MeOH"]],
        "part2" : [sys.argv[2],"nuts0",
                   ["alumina","aluminium-primary","aluminium-secondary","integrated-stealworks-steel",
                    "other-industrial-sectors","ceramics-and-other-non-metalic-minerals",
                    "other-chemicals","pharmaceuticals","food-beverages-tobacco",
                    "machinery-equipment","other-non-ferrous-metals","paper","electric-arc-steel",
                    "printing-and-media","pulp","leather-and-textile",
                    "transport-equipment","wood-and-wood-products"]],
        }
    ind_df = pd.read_excel(sys.argv[3],sheet_name=None)
    region_transformations = load_region_transformations_to_ic1("region_transformation_IC1.xlsx")

    for part in dbs_dict:
        print(f"############### Filling the output DB ############### {part}")
        url_db_out = dbs_dict[part][0]
        resolution = dbs_dict[part][1]
        nodes = dbs_dict[part][2]
        with DatabaseMapping(url_db_out) as target_db:

            ## Empty the database
            target_db.purge_items('entity')
            target_db.purge_items('parameter_value')
            target_db.purge_items('alternative')
            target_db.purge_items('scenario')
            target_db.refresh_session()

            versionconfig = yaml.safe_load(open(sys.argv[-1], "rb"))
            add_scenario(target_db, f"v_{versionconfig['industry']['version']}")

            with open("industry_template_DB.json", 'r') as f:
                db_template = json.load(f)
            # Importing Map
            api.import_data(target_db,
                        entity_classes=db_template["entity_classes"],
                        parameter_definitions=db_template["parameter_definitions"],
                        )

            for alternative_name in ["Base"]:
                add_alternative(target_db,alternative_name)


            conversion_sectors(target_db,ind_df["ind_process_routes_sec"],ind_df,nodes)
            commit_session_safe(target_db, "conversion added")
            print("conversion added")

            cap_sheet_name, cap_source_resolution, cap_needs_transform = pick_sheet_for_prefix(ind_df, "ind_production_2018")
            if cap_sheet_name is None:
                warn(f"[{part}] capacity skipped because no source sheet could be selected.")
                cap_df_ic1 = pd.DataFrame()
            else:
                cap_df_raw = ind_df[cap_sheet_name]
                cap_df_ic1 = normalize_sheet_to_ic1(
                    cap_df_raw,
                    cap_source_resolution,
                    region_transformations,
                    ["2018"],
                    f"{part}:capacity:{cap_sheet_name}"
                )
                if cap_needs_transform:
                    print(f"[{part}] capacity transformed from {cap_source_resolution} to {TARGET_RESOLUTION} using {cap_sheet_name}")
                else:
                    print(f"[{part}] capacity used native {TARGET_RESOLUTION} sheet {cap_sheet_name}")

            demand_sheet_name, demand_source_resolution, demand_needs_transform = pick_sheet_for_prefix(ind_df, "ind_production_30_50")
            if demand_sheet_name is None:
                warn(f"[{part}] demand skipped because no source sheet could be selected.")
                demand_df_ic1 = pd.DataFrame()
            else:
                demand_df_raw = ind_df[demand_sheet_name]
                demand_df_ic1 = normalize_sheet_to_ic1(
                    demand_df_raw,
                    demand_source_resolution,
                    region_transformations,
                    ["2030", "2050"],
                    f"{part}:demand:{demand_sheet_name}"
                )
                if demand_needs_transform:
                    print(f"[{part}] demand transformed from {demand_source_resolution} to {TARGET_RESOLUTION} using {demand_sheet_name}")
                else:
                    print(f"[{part}] demand used native {TARGET_RESOLUTION} sheet {demand_sheet_name}")

            warn_material_mismatches(
                {
                    "conversion": ind_df["ind_process_routes_sec"],
                    "capacity": cap_df_ic1,
                    "demand": demand_df_ic1,
                }
            )

            capacity_sectors(target_db, cap_df_ic1, nodes, TARGET_RESOLUTION)
            commit_session_safe(target_db, "capacity added")
            print("capacity added")
            demand_sectors(target_db, demand_df_ic1, nodes, TARGET_RESOLUTION)
            commit_session_safe(target_db, "demand added")
            print("demand added")
            #remove_items(target_db)
            #target_db.commit_session("removal")
            remove_items(target_db)
            try:
                target_db.commit_session("removal")
            except Exception as e:
                # spinedb_api raises NothingToCommit when there are no changes pending
                if "NothingToCommit" in e.__class__.__name__:
                    print("Nothing to commit after removal (steam/heat not present). Continuing...")
                else:
                    raise
        
if __name__ == "__main__":
    main()