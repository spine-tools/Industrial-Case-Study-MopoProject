import spinedb_api as api
from spinedb_api import DatabaseMapping
from spinedb_api.exception import NothingToCommit
import argparse
import os
import pandas as pd
import sys
import numpy as np
import json 
import yaml

SOURCE_RESOLUTION_PRIORITY = ["nuts3", "nuts2", "nuts1", "nuts0"]
DEFAULT_TARGET_RESOLUTION = "ic1"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_IC1_REGION_MAP = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "region_transformation_IC1.xlsx"))

def add_entity(db_map : DatabaseMapping, class_name : str, name : str, ent_description = None) -> None:
    _, error = db_map.add_entity_item(name=name, entity_class_name=class_name,description=ent_description)
    if error is not None:
        raise RuntimeError(error)

def add_relationship(db_map : DatabaseMapping,class_name : str,element_names : str) -> None:
    _, error = db_map.add_entity_item(element_name_list=element_names, entity_class_name=class_name)
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

def add_scenario(db_map : DatabaseMapping,name_scenario : str) -> None:
    _, error = db_map.add_scenario_item(name=name_scenario)
    if error is not None:
        raise RuntimeError(error)

def warn(msg : str) -> None:
    print(f"WARNING: {msg}")

def commit_session_safe(db_map : DatabaseMapping, message : str) -> None:
    try:
        db_map.commit_session(message)
    except NothingToCommit:
        print(f"Nothing to commit for '{message}'. Continuing...")

def find_column_case_insensitive(df : pd.DataFrame, candidates : list) -> str | None:
    lookup = {str(col).lower(): col for col in df.columns}
    for candidate in candidates:
        hit = lookup.get(candidate.lower())
        if hit is not None:
            return hit
    return None

def get_region_column(df : pd.DataFrame, resolution : str) -> str | None:
    if resolution == "nuts0":
        return find_column_case_insensitive(df, ["nuts0", "country_code"])
    return find_column_case_insensitive(df, [resolution])

def detect_source_resolution(df : pd.DataFrame) -> str | None:
    for resolution in SOURCE_RESOLUTION_PRIORITY:
        if get_region_column(df, resolution) is not None:
            return resolution
    return None

def load_region_transformations(file_path : str, target_resolution : str) -> dict:
    if not file_path:
        return {}
    if not os.path.exists(file_path):
        warn(f"Region transformation file not found: {file_path}")
        return {}

    transformations = {}
    sheet_dict = pd.read_excel(file_path, sheet_name=None)
    lower_sheet_lookup = {name.lower(): name for name in sheet_dict.keys()}

    for source_resolution in SOURCE_RESOLUTION_PRIORITY:
        sheet_key = f"{source_resolution}_{target_resolution}".lower()
        source_sheet = lower_sheet_lookup.get(sheet_key)
        if source_sheet is None:
            continue

        map_df = sheet_dict[source_sheet].copy()
        source_col = find_column_case_insensitive(map_df, ["source"])
        target_col = find_column_case_insensitive(map_df, ["target"])
        if source_col is None or target_col is None:
            warn(f"Sheet '{source_sheet}' is missing source/target columns and will be ignored")
            continue

        map_df = map_df[[source_col, target_col]].rename(columns={source_col: "source", target_col: "target"})
        map_df["source"] = map_df["source"].astype(str).str.strip()
        map_df["target"] = map_df["target"].astype(str).str.strip()
        map_df = map_df[(map_df["source"] != "") & (map_df["target"] != "")].drop_duplicates()
        transformations[source_resolution] = map_df

    return transformations

def normalize_biomass_regions(
    df : pd.DataFrame,
    target_resolution : str,
    transformations : dict,
) -> pd.DataFrame:
    out_df = df.copy()
    target_col = get_region_column(out_df, target_resolution)

    if target_col is not None:
        out_df["target_region"] = out_df[target_col].astype(str).str.strip()
        return out_df

    source_resolution = detect_source_resolution(out_df)
    if source_resolution is None:
        raise RuntimeError(
            "No compatible region column found in biomass CSV. "
            f"Expected one of: {SOURCE_RESOLUTION_PRIORITY + [target_resolution]}"
        )

    source_col = get_region_column(out_df, source_resolution)
    out_df[source_col] = out_df[source_col].astype(str).str.strip()

    if source_resolution == target_resolution:
        out_df["target_region"] = out_df[source_col]
        return out_df

    mapping_df = transformations.get(source_resolution)
    if mapping_df is None:
        raise RuntimeError(
            f"Missing mapping table '{source_resolution}_{target_resolution}'. "
            "Provide --region-map with a workbook containing source/target sheets."
        )

    mapped = out_df.merge(mapping_df, how="left", left_on=source_col, right_on="source")
    missing_mask = mapped["target"].isna()
    if missing_mask.any():
        missing_values = sorted(mapped.loc[missing_mask, source_col].dropna().astype(str).unique().tolist())
        warn(
            f"{len(missing_values)} source regions have no mapping to {target_resolution} and will be dropped:\n"
            + "\n".join(missing_values)
        )
        mapped = mapped[~missing_mask].copy()

    split_count = mapping_df.groupby("source")["target"].nunique().to_dict()
    mapped["_split"] = mapped[source_col].map(split_count).fillna(1.0).astype(float)
    mapped["quantity"] = pd.to_numeric(mapped["quantity"], errors="coerce").fillna(0.0) / mapped["_split"]
    mapped["_weighted_roadside"] = (
        pd.to_numeric(mapped["quantity"], errors="coerce").fillna(0.0)
        * pd.to_numeric(mapped["roadsidecost"], errors="coerce").fillna(0.0)
    )
    mapped["target_region"] = mapped["target"].astype(str).str.strip()
    return mapped.drop(columns=["source", "target", "_split"], errors="ignore")

def build_aggregated_biomass(df : pd.DataFrame, target_resolution : str) -> pd.DataFrame:
    norm_df = df.copy()
    norm_df["scenario"] = norm_df["scenario"].astype(str).str.strip()
    norm_df["target_region"] = norm_df["target_region"].astype(str).str.strip()
    if target_resolution == "nuts0":
        norm_df["target_region"] = norm_df["target_region"].replace({"EL": "GR"})

    norm_df["quantity"] = pd.to_numeric(norm_df["quantity"], errors="coerce").fillna(0.0)
    norm_df["roadsidecost"] = pd.to_numeric(norm_df["roadsidecost"], errors="coerce").fillna(0.0)

    if "_weighted_roadside" not in norm_df.columns:
        norm_df["_weighted_roadside"] = norm_df["quantity"] * norm_df["roadsidecost"]

    grouped = (
        norm_df
        .groupby(["scenario", "target_region"], as_index=False)
        .agg(
            quantity_sum=("quantity", "sum"),
            roadside_weighted_sum=("_weighted_roadside", "sum"),
        )
    )
    return grouped

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Spine biomass DB with configurable output resolution")
    parser.add_argument("output_db_url", help="Output Spine database URL/path")
    parser.add_argument("biomass_csv", help="Input biomass CSV")
    parser.add_argument("version_config", help="Version tracking YAML file")
    parser.add_argument(
        "--target-resolution",
        default=DEFAULT_TARGET_RESOLUTION,
        help="Output region resolution column name (default: ic1)",
    )
    parser.add_argument(
        "--region-map",
        default="",
        help="Optional Excel workbook with mapping sheets like nuts0_ic1 containing source/target columns",
    )
    return parser.parse_args()
       
def main():
    args = parse_args()

    url_db_out = args.output_db_url
    target_resolution = str(args.target_resolution).strip().lower()
    region_map_path = args.region_map
    if not region_map_path and target_resolution == "ic1":
        region_map_path = DEFAULT_IC1_REGION_MAP
    bio_db = pd.read_csv(args.biomass_csv).fillna(0.0)
    source_resolution = detect_source_resolution(bio_db)
    required_columns = {"scenario", "quantity", "roadsidecost"}
    if not required_columns.issubset(set(bio_db.columns)):
        raise RuntimeError(f"Input CSV must include columns: {sorted(required_columns)}")

    transformations = load_region_transformations(region_map_path, target_resolution)
    print(f"Biomass target resolution: {target_resolution}")
    print(f"Biomass detected source resolution: {source_resolution}")
    if region_map_path:
        print(f"Biomass region map file: {region_map_path}")
        print(f"Biomass loaded mapping sheets: {sorted(transformations.keys())}")
    else:
        print("Biomass region map file: none")
    bio_db_norm = normalize_biomass_regions(bio_db, target_resolution, transformations)
    bio_db_grouped = build_aggregated_biomass(bio_db_norm, target_resolution)

    bio_costs = {}
    with DatabaseMapping(url_db_out) as db_map:
        
        ## Empty the database
        db_map.purge_items('entity')
        db_map.purge_items('parameter_value')
        db_map.purge_items('alternative')
        db_map.purge_items('scenario')
        db_map.refresh_session()

        versionconfig = yaml.safe_load(open(args.version_config, "rb"))
        add_scenario(db_map, f"v_{versionconfig['biomass']['version']}")

        with open("biomass_template_DB.json", 'r') as f:
            db_template = json.load(f)
        # Importing Map
        api.import_data(db_map,
                    entity_classes=db_template["entity_classes"],
                    parameter_definitions=db_template["parameter_definitions"],
                    )
        
        add_alternative(db_map,"Base")
        add_entity(db_map,"commodity","bio")
        add_entity(db_map,"stock","biomass-stock")
        add_relationship(db_map,"stock__to_commodity",("biomass-stock","bio"))
        for scenario in bio_db_grouped["scenario"].unique():
            add_alternative(db_map,scenario+"_bio")

            scenario_df = bio_db_grouped[bio_db_grouped["scenario"] == scenario]
            for _, row in scenario_df.iterrows():
                region = row["target_region"]

                try:
                    add_entity(db_map,"region",region)
                except RuntimeError:
                    pass

                try:
                    add_relationship(db_map,"stock__to_commodity__region",("biomass-stock","bio",region))
                except RuntimeError:
                    pass

                value_converted = float(row["quantity_sum"])*277777.77
                add_parameter_value(db_map,"stock__to_commodity__region","annual_production",scenario+"_bio",("biomass-stock","bio",region),round(value_converted,1))
                transport_cost = 7.0 # moving biomass to final destination, average value
                value_converted = (
                    1.32*float(row["roadside_weighted_sum"])/float(row["quantity_sum"])/0.277778 + transport_cost
                    if float(row["quantity_sum"]) > 0
                    else transport_cost
                )
                add_parameter_value(db_map,"stock__to_commodity__region","operational_cost",scenario+"_bio",("biomass-stock","bio",region),round(value_converted,1))
                bio_costs[region]=value_converted
        print("Biomass Data Added")

        commit_session_safe(db_map, "entities added")
    if bio_costs:
        print(f"Average cost of biomass {np.mean(list(bio_costs.values()))}")
    else:
        print("No biomass costs were written")
if __name__ == "__main__":
    main()