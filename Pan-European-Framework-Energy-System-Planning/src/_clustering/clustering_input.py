import spinedb_api as api
from spinedb_api import DatabaseMapping
import pandas as pd
import sys
import numpy as np
import os
from sklearn.preprocessing import MinMaxScaler
from sqlalchemy.exc import DBAPIError
import re

sopt_db =  DatabaseMapping(sys.argv[1])

def add_entity(db_map : DatabaseMapping, class_name : str, name : tuple, ent_description = None) -> None:
    _, error = db_map.add_entity_item(entity_byname=name, entity_class_name=class_name, description = ent_description)
    if error is not None:
        raise RuntimeError(error)

def add_entity_group(db_map : DatabaseMapping, class_name : str, group : str, member : str) -> None:
    _, error = db_map.add_entity_group_item(group_name = group, member_name = member, entity_class_name=class_name)
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

def input_data():

    patterns = {"wind": ["wind"],
            "solar": ["solar"],
            "RoR": ["ror"],  # 'RoR' en minúsculas porque hacemos case-insensitive
            "reservoir": ["reservoir"],
            "elec": ["elec"],
            "cool": ["cool"],
            "DHW_or_space": ["dhw", "space"],
            "transport_truck_bus_van_car_rail_aviation_maritime": [
                "truck", "bus", "van", "car", "rail", "aviation", "maritime"
            ],
        }

    dict_df = {}
    for alternative_name in ["wy2009"]:
        columns_names = []
        array_ts = np.array([])
        for name_parameter in ["availability_factor","demand"]:
            for param_map in sopt_db.get_parameter_value_items(parameter_definition_name = name_parameter,alternative_name = alternative_name):
                if param_map["type"] == "time_series":
                    columns_names.append(param_map["entity_name"])
                    array_ts = np.hstack((array_ts, param_map["parsed_value"].values.reshape(-1, 1))) if  array_ts.size != 0 else param_map["parsed_value"].values.reshape(-1, 1)
        # Initialize the scaler
        scaler = MinMaxScaler()
        df_ts = pd.DataFrame(scaler.fit_transform(array_ts),index = range(1,array_ts.shape[0]+1), columns = columns_names).rename_axis("timestep").reset_index()
        dict_df[alternative_name] = pd.melt(df_ts, id_vars=df_ts.columns.tolist()[:1], value_vars=df_ts.columns.tolist()[1:], var_name='profile_name', value_name='value')[["profile_name","timestep","value"]]
        profiles_df = pd.concat([dict_df[alternative_name]],ignore_index=True)
        print(profiles_df)
        per_cat = {}
        for cat, keys in patterns.items():
            pat = r"|".join(re.escape(k) for k in keys)
            mask = profiles_df["profile_name"].str.contains(pat, case=False, na=False)
            per_cat[cat] = profiles_df.loc[mask].groupby("timestep", dropna=True)["value"].mean()

        wide = pd.DataFrame(per_cat).sort_index() 
        wide = wide.dropna(axis=1, how="all")
        long = (wide.reset_index(names="timestep").melt(id_vars="timestep", var_name="profile_name", value_name="value").sort_values(["profile_name", "timestep"]).reset_index(drop=True))    

        long = long[["profile_name","timestep","value"]]
        os.makedirs("profiles", exist_ok=True)
        long.to_csv(f"profiles/profiles_{alternative_name}.csv",index=False)

if __name__ == "__main__":
    input_data()

