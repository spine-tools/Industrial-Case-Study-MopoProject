import spinedb_api as api
from spinedb_api import DatabaseMapping
from spinedb_api.dataframes import to_dataframe
from spinedb_api.parameter_value import convert_map_to_table, IndexedValue
from sqlalchemy.exc import DBAPIError
import datetime
import pandas as pd
import sys
import numpy as np
import json
import yaml 
import time as time_lib
import plotly.express as px
from plotly.subplots import make_subplots
import plotly.graph_objects as go
import plotly.colors as pc
import copy
import re 
from math import cos, sin, radians, sqrt, pi
import matplotlib.pyplot as plt
from matplotlib.patches import Wedge
import geopandas as gpd
import sys
from streamlit.web import cli as stcli
import dill
import time as time_lib

start_time = time_lib.time()
url_results = sys.argv[1]#r"sqlite:///C:\Users\papo002\Desktop\Pan-European_Framework\.spinetoolbox\items\investment_results\Investment_Results.sqlite" #sys.argv[1]
result_db = DatabaseMapping(url_results)
result_db.fetch_all()

if len(sys.argv) > 2:
    sopt_results = sys.argv[2]#r"sqlite:///C:\Users\papo002\Desktop\Pan-European_Framework\.spinetoolbox\items\final_spineopt_model\Final_SpineOpt_Model.sqlite" # sys.argv[2]
    sopt_db = DatabaseMapping(sopt_results)
    sopt_db.fetch_all()
else:
    print("There is no associated SpineOpt DB, you will get an error if you call it")

if len(sys.argv) > 3:
    with open(sys.argv[3], 'r') as file:
        scenario_config = yaml.safe_load(file)

with open("config/node_mapping.yml","r") as file:
    node_map = yaml.safe_load(file)
with open("config/node_mapping_sankey.yml","r") as file:
    node_map_sankey = yaml.safe_load(file)
with open("config/unit_mapping.yml","r") as file:
    unit_map = yaml.safe_load(file)
with open("config/scenario_mapping.yml","r") as file:
    scenario_map = yaml.safe_load(file)
with open("config/bidirectional_storage_node_map.yml","r") as file:
    storage_bi_node_map = yaml.safe_load(file)
with open("config/storage_node_mapping.yml","r") as file:
    storage_node_map = yaml.safe_load(file)
        

def extract_polygon(unit_name: str):
    if not isinstance(unit_name, str):
        return None
    part = unit_name.rsplit('_', 1)[-1][-2:]
    return (part if part!="on" else "Europe") or None

def apply_unit_name(unit_name: str):
    new_name = None
    if not isinstance(unit_name, str):
        return None
    for key_i in unit_map:
        if key_i in unit_name:
            new_name = unit_map[key_i]
    return new_name or unit_name.rsplit('_', 1)[0]

def nested_index_names(value, names = None, depth = 0):
    if names is None:
        names = []
    if depth == len(names):
        names.append(value.index_name)
    elif value.index_name != names[-1]:
        raise RuntimeError(f"Index names at depth {depth} do no match: {value.index_name} vs. {names[-1]}")
    for y in value.values:
        if isinstance(y, IndexedValue):
            nested_index_names(y, names, depth + 1)
    return names

def from_DB_to_df(map_years):

    alternatives = [i["name"] for i in result_db.get_alternative_items()]
    latest_alternatives = {}
    for alternative in alternatives:
        if "@" in alternative:
            name, timestamp = alternative.split('@')
            timestamp = pd.Timestamp(timestamp)
        
            if name not in latest_alternatives or timestamp > latest_alternatives[name]:
                latest_alternatives[name] = timestamp

    years = list(map_years.values())
    start_date = {2030:"2030-01-01 00:00:00",2041:"2040-12-31 23:00:00",2050:"2049-12-31 23:00:00"}
    years_index = [pd.Timestamp(i) for year in map_years for i in pd.date_range(start=start_date[year],end=str(year)+"-12-31 23:00:00",freq="1h")]

    rps = get_representative_periods()
    flex_res = check_flexible_resolution()

    analyzed_nodes = ["elec","HC","H2","CH4","heat","cool","MeOH","NH3"]#,"steel-primary","steel-secondary","MeOH","glass-float","glass-container","glass-fibre","fertiliser-ammonia-NH3","chemical-PE","chemical-PEA","chemical-olefins","cement"]
    unit_to_node_map = {}
    energy_map_list    = {name:[] for name in latest_alternatives}
    flows_map_list     = {name:[] for name in latest_alternatives}
    flows_sto_list     = {name:[] for name in latest_alternatives}
    emission_map_list  = {name:[] for name in latest_alternatives}
    unit_to_flows_list = {name:[] for name in latest_alternatives}
    connections_cap_list  = {name:[] for name in latest_alternatives}
    connections_inv_list  = {name:[] for name in latest_alternatives}
    connections_dec_list  = {name:[] for name in latest_alternatives}
    storages_cap_list  = {name:[] for name in latest_alternatives}
    storages_inv_list  = {name:[] for name in latest_alternatives}
    storages_dec_list  = {name:[] for name in latest_alternatives}
    storages_cost_list = {name:[] for name in latest_alternatives}
    units_cap_list     = {name:[] for name in latest_alternatives}
    units_inv_list     = {name:[] for name in latest_alternatives}
    units_dec_list     = {name:[] for name in latest_alternatives}
    units_inv_cost_list= {name:[] for name in latest_alternatives}
    node_state_parts   = {name:[] for name in latest_alternatives}

    for param_map in result_db.get_parameter_value_items(parameter_definition_name = "unit_flow"):        
        scenario_name, timestamp = param_map["alternative_name"].split("@")
        timestamp = pd.Timestamp(timestamp)
        if scenario_name in latest_alternatives:
            if timestamp == latest_alternatives[scenario_name]:
                alte_name = scenario_name
                if "to_node" in param_map["entity_byname"]:

                    unit_name = param_map["entity_byname"][1]
                    node_name = param_map["entity_byname"][2]

                    map_table = convert_map_to_table(param_map["parsed_value"])
                    index_names = nested_index_names(param_map["parsed_value"])
                    data = pd.DataFrame(map_table, columns=index_names + [unit_name]).set_index(index_names[0])[unit_name]
                    data.index = pd.to_datetime(data.index.astype("string"))

                    if rps:
                        rp_alternative = [i for i in scenario_config["scenarios"][scenario_name.split("__")[0]] if i in rps.keys()][0]
                        data = data.loc[rps[rp_alternative].index]*rps[rp_alternative].loc[:,"weight"]
                    elif flex_res:
                        for year_res in flex_res:
                            mask = data.index.year == (year_res if year_res != 2040 else 2041)
                            data.loc[mask] *= flex_res[year_res]

                    yearly_sums = data.groupby(data.index.year).sum()
                    unit_to_flows_list[alte_name].append([unit_name,node_name.split("_")[0]] + [yearly_sums.get(year_i, 0) for year_i in map_years])

                    if node_name != "atmosphere":
                        if not (any(i in unit_name for i in ["+CC","MEA","DEA","-CC","Oxy","CaL"]) and node_name.split("_")[0] == "CO2"):
                            if any(i in unit_name for i in storage_bi_node_map):
                                unit_to_node_map[unit_name] = [storage_bi_node_map[i] for i in storage_bi_node_map if i in unit_name][0]
                            else:
                                unit_to_node_map[unit_name] = node_name.split("_")[0] 
                        if "wind" in unit_name:
                            energy_map_list[alte_name].append(["wind",unit_name] + [yearly_sums.get(year_i, 0) for year_i in map_years])
                        elif "solar" in unit_name:
                            energy_map_list[alte_name].append(["solar",unit_name] + [yearly_sums.get(year_i, 0) for year_i in map_years])
                        elif "RoR" in unit_name:
                            energy_map_list[alte_name].append(["hydro",unit_name] + [yearly_sums.get(year_i, 0) for year_i in map_years])
                    else:
                        emission_map_list[alte_name].append([unit_name,"atmosphere"] + [yearly_sums.get(year_i, 0) for year_i in map_years])

                elif "from_node" in param_map["entity_byname"]:
                    unit_name = param_map["entity_byname"][1]
                    node_name = param_map["entity_byname"][2]

                    map_table = convert_map_to_table(param_map["parsed_value"])
                    index_names = nested_index_names(param_map["parsed_value"])
                    data = pd.DataFrame(map_table, columns=index_names + [unit_name]).set_index(index_names[0])[unit_name]
                    data.index = [pd.Timestamp(i) for i in data.index.astype("string")]
                    
                    if rps:
                        rp_alternative = [i for i in scenario_config["scenarios"][scenario_name.split("__")[0]] if i in rps.keys()][0]
                        data = data.loc[rps[rp_alternative].index]*rps[rp_alternative].loc[:,"weight"]
                    elif flex_res:
                        for year_res in flex_res:
                            mask = data.index.year == (year_res if year_res != 2040 else 2041)
                            data.loc[mask] *= flex_res[year_res]

                    yearly_sums = data.groupby(data.index.year).sum()
                    if node_name != "atmosphere":
                        energy_map_list[alte_name].append([node_name.split("_")[0],unit_name] + [yearly_sums.get(year_i, 0) for year_i in map_years])
                    else:
                        emission_map_list[alte_name].append(["atmosphere",unit_name]  + [yearly_sums.get(year_i, 0) for year_i in map_years])

    connection_flow_items = result_db.get_parameter_value_items(parameter_definition_name = "connection_flow")
    analyzed_vehs = ["car","van","bus","truck","aviation","maritime","rail"]
    for param_map in connection_flow_items:
        scenario_name, timestamp = param_map["alternative_name"].split("@")
        timestamp = pd.Timestamp(timestamp)
        if scenario_name in latest_alternatives:
            if timestamp == latest_alternatives[scenario_name]:
                alte_name = scenario_name
                if "from_node" in param_map["entity_byname"]:
                    link_name = param_map["entity_byname"][1]
                    node_name = param_map["entity_byname"][2]

                    if any(analyzed_node in node_name for analyzed_node in analyzed_nodes) and any(analyzed_veh in link_name for analyzed_veh in analyzed_vehs):
                        map_table = convert_map_to_table(param_map["parsed_value"])
                        index_names = nested_index_names(param_map["parsed_value"])
                        data = pd.DataFrame(map_table, columns=index_names + [link_name]).set_index(index_names[0])[link_name]
                        data.index = pd.to_datetime(data.index.astype("string"))
   
                        if rps:
                            rp_alternative = [i for i in scenario_config["scenarios"][scenario_name.split("__")[0]] if i in rps.keys()][0]
                            data = data.loc[rps[rp_alternative].index]*rps[rp_alternative].loc[:,"weight"]
                        elif flex_res:
                            for year_res in flex_res:
                                mask = data.index.year == (year_res if year_res != 2040 else 2041)
                                data.loc[mask] *= flex_res[year_res]

                        yearly_sums = data.groupby(data.index.year).sum()
                        unit_to_node_map[link_name] = link_name.split("__")[1].split("_")[0]
                        energy_map_list[alte_name].append([node_name.split("_")[0],link_name]  + [yearly_sums.get(year_i, 0) for year_i in map_years])

    for param_map in connection_flow_items:
        scenario_name, timestamp = param_map["alternative_name"].split("@")
        timestamp = pd.Timestamp(timestamp)
        if scenario_name in latest_alternatives:
            if timestamp == latest_alternatives[scenario_name]:
                alte_name = scenario_name
                if "from_node" in param_map["entity_byname"]:
                    link_name = param_map["entity_byname"][1]
                    node_name = param_map["entity_byname"][2]

                    if node_name.split("_")[0] == link_name.split("_")[1]:
                        if node_name.split("_")[1] == link_name.split("_")[0] or node_name.split("_")[1] == link_name.split("_")[2]:
                            map_table = convert_map_to_table(param_map["parsed_value"])
                            index_names = nested_index_names(param_map["parsed_value"])
                            data = pd.DataFrame(map_table, columns=index_names + [link_name]).set_index(index_names[0])[link_name]
                            data.index = pd.to_datetime(data.index.astype("string"))

                            if rps:
                                rp_alternative = [i for i in scenario_config["scenarios"][scenario_name.split("__")[0]] if i in rps.keys()][0]
                                data = data.loc[rps[rp_alternative].index]*rps[rp_alternative].loc[:,"weight"]
                            elif flex_res:
                                for year_res in flex_res:
                                    mask = data.index.year == (year_res if year_res != 2040 else 2041)
                                    data.loc[mask] *= flex_res[year_res]

                            yearly_sums = data.groupby(data.index.year).sum()
                            if len(node_name.split("_")) > 1:
                                #print(link_name)
                                p1 = node_name.split("_")[1]
                                p2 = [i for i in [link_name.split("_")[0],link_name.split("_")[2]] if i != p1][0]
                                commodity = link_name.split("_")[1]
                                #print(p1,p2,commodity)
                                flows_map_list[alte_name].append([p1,p2,commodity] + [yearly_sums.get(year_i, 0) for year_i in map_years])
                    
                    elif "CH4-geo-formation" in link_name or "salt-cavern" in link_name:
                        map_table = convert_map_to_table(param_map["parsed_value"])
                        index_names = nested_index_names(param_map["parsed_value"])
                        data = pd.DataFrame(map_table, columns=index_names + [link_name]).set_index(index_names[0])[link_name]
                        data.index = pd.to_datetime(data.index.astype("string"))
                        if rps:
                            rp_alternative = [i for i in scenario_config["scenarios"][scenario_name.split("__")[0]] if i in rps.keys()][0]
                            data = data.loc[rps[rp_alternative].index]*rps[rp_alternative].loc[:,"weight"]
                        elif flex_res:
                            for year_res in flex_res:
                                mask = data.index.year == (year_res if year_res != 2040 else 2041)
                                data.loc[mask] *= flex_res[year_res]
                        yearly_sums = data.groupby(data.index.year).sum()
                        flows_sto_list[alte_name].append([node_name,link_name]  + [yearly_sums.get(year_i, 0) for year_i in map_years])

    for param_map in result_db.get_parameter_value_items(parameter_definition_name = "demand"):
        scenario_name, timestamp = param_map["alternative_name"].split("@")
        timestamp = pd.Timestamp(timestamp)
        if scenario_name in latest_alternatives:
            if timestamp == latest_alternatives[scenario_name]:
                alte_name = scenario_name
                node_name = param_map["entity_byname"][1]
                if any(analyzed_node == node_name.split("_")[0] and len(node_name.split("_"))==2  for analyzed_node in analyzed_nodes):
                    map_table = convert_map_to_table(param_map["parsed_value"])
                    index_names = nested_index_names(param_map["parsed_value"])
                    data = pd.DataFrame(map_table, columns=index_names + [node_name]).set_index(index_names[0])[node_name]
                    data.index = pd.to_datetime(data.index.astype("string"))
                    if rps:
                        rp_alternative = [i for i in scenario_config["scenarios"][scenario_name.split("__")[0]] if i in rps.keys()][0]
                        data = data.loc[rps[rp_alternative].index]*rps[rp_alternative].loc[:,"weight"]
                    elif flex_res:
                        for year_res in flex_res:                           
                            mask = data.index.year == (year_res if year_res != 2040 else 2041)
                            data.loc[mask] *= flex_res[year_res]

                    yearly_sums = data.groupby(data.index.year).sum()
                    unit_to_node_map[node_name] = "residual-"+node_name.split("_")[0]
                    energy_map_list[alte_name].append([node_name.split("_")[0],node_name] + [yearly_sums.get(year_i, 0) for year_i in map_years])

    unit_capacity_map = {p["entity_byname"][1]: p["parsed_value"].values[0] for p in result_db.get_parameter_value_items(parameter_definition_name="capacity_per_unit")}
    for param_map in result_db.get_parameter_value_items(parameter_definition_name = "units_invested_available"):
        scenario_name, timestamp = param_map["alternative_name"].split("@")
        timestamp = pd.Timestamp(timestamp)
        if scenario_name in latest_alternatives:
            if timestamp == latest_alternatives[scenario_name]:
                alte_name = scenario_name
                unit_name = param_map["entity_byname"][1]

                map_table = convert_map_to_table(param_map["parsed_value"])
                index_names = nested_index_names(param_map["parsed_value"])
                data = pd.DataFrame(map_table, columns=index_names + [unit_name]).set_index(index_names[0])
                
                capacity_value = unit_capacity_map[unit_name]
                units_cap_list[alte_name].append([unit_name] + (capacity_value*data[unit_name]).to_list())
        
                invested = result_db.get_parameter_value_item(entity_class_name = param_map["entity_class_name"], alternative_name = param_map["alternative_name"],parameter_definition_name = "units_invested", entity_byname = param_map["entity_byname"])
                map_table = convert_map_to_table(invested["parsed_value"])
                index_names = nested_index_names(invested["parsed_value"])
                data = pd.DataFrame(map_table, columns=index_names + [unit_name]).set_index(index_names[0])
                
                units_inv_list[alte_name].append([unit_name] + (capacity_value*data[unit_name]).to_list())
                if data[unit_name].sum() > 0.001:
                    inv_cost = sopt_db.get_parameter_value_item(entity_class_name = "unit", alternative_name = "Base",parameter_definition_name = "unit_investment_cost", entity_byname = (unit_name,))
                    if inv_cost:
                        map_table = convert_map_to_table(inv_cost["parsed_value"])
                        index_names = nested_index_names(inv_cost["parsed_value"])
                        data_inv = pd.DataFrame(map_table, columns=index_names + [unit_name]).set_index(index_names[0])
                        units_inv_cost_list[alte_name].append([unit_name] + [capacity_value*data.at[i,unit_name]*data_inv.at[(i if i.year != 2040 else pd.Timestamp("2041-01-01")),unit_name] for i in data[unit_name].index])

                decommissioned = result_db.get_parameter_value_item(entity_class_name = param_map["entity_class_name"], alternative_name = param_map["alternative_name"],parameter_definition_name = "units_mothballed", entity_byname = param_map["entity_byname"])
                map_table = convert_map_to_table(decommissioned["parsed_value"])
                index_names = nested_index_names(decommissioned["parsed_value"])
                data = pd.DataFrame(map_table, columns=index_names + [unit_name]).set_index(index_names[0])
                
                units_dec_list[alte_name].append([unit_name] + (capacity_value*data[unit_name]).to_list())

    for param_map in result_db.get_parameter_value_items(parameter_definition_name = "connections_invested_available"):
        scenario_name, timestamp = param_map["alternative_name"].split("@")
        timestamp = pd.Timestamp(timestamp)
        if scenario_name in latest_alternatives:
            if timestamp == latest_alternatives[scenario_name]:
                alte_name = scenario_name
                link_name = param_map["entity_byname"][1]
                if len(link_name.split("_"))==3 and any(analyzed_node in link_name for analyzed_node in analyzed_nodes):
                    p1, commodity, p2 = link_name.split("_")
                    
                    map_table = convert_map_to_table(param_map["parsed_value"])
                    index_names = nested_index_names(param_map["parsed_value"])
                    data = pd.DataFrame(map_table, columns=index_names + [link_name]).set_index(index_names[0])
                    connections_cap_list[alte_name].append([p1, p2, commodity] + (data[link_name]).to_list())

                    invested = result_db.get_parameter_value_item(entity_class_name = param_map["entity_class_name"], alternative_name = param_map["alternative_name"],parameter_definition_name = "connections_invested", entity_byname = param_map["entity_byname"])
                    map_table = convert_map_to_table(invested["parsed_value"])
                    index_names = nested_index_names(invested["parsed_value"])
                    data = pd.DataFrame(map_table, columns=index_names + [link_name]).set_index(index_names[0])               
                    connections_inv_list[alte_name].append([p1, p2, commodity] + (data[link_name]).to_list())

                    decommissioned = result_db.get_parameter_value_item(entity_class_name = param_map["entity_class_name"], alternative_name = param_map["alternative_name"],parameter_definition_name = "connections_decommissioned", entity_byname = param_map["entity_byname"])
                    map_table = convert_map_to_table(decommissioned["parsed_value"])
                    index_names = nested_index_names(decommissioned["parsed_value"])
                    data = pd.DataFrame(map_table, columns=index_names + [link_name]).set_index(index_names[0])               
                    connections_dec_list[alte_name].append([p1, p2, commodity] + (data[link_name]).to_list())

    sto_capacity_map = {p["entity_byname"][1]: p["parsed_value"].values[0] for p in result_db.get_parameter_value_items(parameter_definition_name="storage_state_max")}
    for param_map in result_db.get_parameter_value_items(parameter_definition_name = "storages_invested_available"):
        scenario_name, timestamp = param_map["alternative_name"].split("@")
        timestamp = pd.Timestamp(timestamp)
        if scenario_name in latest_alternatives:
            if timestamp == latest_alternatives[scenario_name]:
                alte_name = scenario_name
                storage_name = param_map["entity_byname"][1]
                if storage_name != "CO2":

                    map_table = convert_map_to_table(param_map["parsed_value"])
                    index_names = nested_index_names(param_map["parsed_value"])
                    data = pd.DataFrame(map_table, columns=index_names + [storage_name]).set_index(index_names[0])
                    
                    capacity_value = sto_capacity_map[storage_name]
                    storages_cap_list[alte_name].append([storage_name] + (capacity_value*data[storage_name]).to_list())
            
                    invested = result_db.get_parameter_value_item(entity_class_name = param_map["entity_class_name"], alternative_name = param_map["alternative_name"],parameter_definition_name = "storages_invested", entity_byname = param_map["entity_byname"])
                    map_table = convert_map_to_table(invested["parsed_value"])
                    index_names = nested_index_names(invested["parsed_value"])
                    data = pd.DataFrame(map_table, columns=index_names + [storage_name]).set_index(index_names[0])
                    storages_inv_list[alte_name].append([storage_name] + (capacity_value*data[storage_name]).to_list())
                    
                    if data[storage_name].sum() > 0.001:
                        inv_cost = sopt_db.get_parameter_value_item(entity_class_name = "node", alternative_name = "Base",parameter_definition_name = "storage_investment_cost", entity_byname = (storage_name,))
                        if inv_cost:
                            map_table = convert_map_to_table(inv_cost["parsed_value"])
                            index_names = nested_index_names(inv_cost["parsed_value"])
                            data_inv = pd.DataFrame(map_table, columns=index_names + [storage_name]).set_index(index_names[0])
                            storages_cost_list[alte_name].append([storage_name] + [capacity_value*data.at[i,storage_name]*data_inv.at[(i if i.year != 2040 else pd.Timestamp("2041-01-01")),storage_name] for i in data[storage_name].index])

                    decommissioned = result_db.get_parameter_value_item(entity_class_name = param_map["entity_class_name"], alternative_name = param_map["alternative_name"],parameter_definition_name = "storages_decommissioned", entity_byname = param_map["entity_byname"])
                    map_table = convert_map_to_table(decommissioned["parsed_value"])
                    index_names = nested_index_names(decommissioned["parsed_value"])
                    data = pd.DataFrame(map_table, columns=index_names + [storage_name]).set_index(index_names[0])
                    storages_dec_list[alte_name].append([storage_name] + (capacity_value*data[storage_name]).to_list())

    
    node_state_param = "node_state_longterm" if rps else "node_state"
    for param_map in result_db.get_parameter_value_items(parameter_definition_name = node_state_param):
        scenario_name, timestamp = param_map["alternative_name"].split("@")
        timestamp = pd.Timestamp(timestamp)
        if scenario_name in latest_alternatives:
            if timestamp == latest_alternatives[scenario_name]:
                storage_name = param_map["entity_byname"][1]

                map_table = convert_map_to_table(param_map["parsed_value"])
                index_names = nested_index_names(param_map["parsed_value"])
                data = pd.DataFrame(map_table, columns=index_names + [storage_name]).set_index(index_names[0])
                data.index = [pd.Timestamp(i) for i in data.index.astype("string")]
                node_state_parts[scenario_name].append(data)

    node_state    = {name: pd.concat(parts,axis=1).sort_index() if parts else pd.DataFrame() for name, parts in node_state_parts.items()}
    energy_map    = {name:pd.DataFrame(energy_map_list[name],columns=["source","target"]+years) for name in latest_alternatives}
    flows_map     = {name:pd.DataFrame(flows_map_list[name],columns=["source","target","commodity"]+years) for name in latest_alternatives}
    flows_sto     = {name:pd.DataFrame(flows_sto_list[name],columns=["source","target"]+years) for name in latest_alternatives}
    emission_map  = {name:pd.DataFrame(emission_map_list[name],columns=["source","target"]+years) for name in latest_alternatives}
    unit_to_flows = {name:pd.DataFrame(unit_to_flows_list[name],columns=["unit_name","node"]+years) for name in latest_alternatives}
    connections_cap= {name:pd.DataFrame(connections_cap_list[name],columns=["source","target","commodity"]+years) for name in latest_alternatives}
    connections_inv= {name:pd.DataFrame(connections_dec_list[name],columns=["source","target","commodity"]+years) for name in latest_alternatives}
    connections_dec= {name:pd.DataFrame(flows_map_list[name],columns=["source","target","commodity"]+years) for name in latest_alternatives}
    storages_cap  = {name:pd.DataFrame(storages_cap_list[name],columns=["storage_name"]+years) for name in latest_alternatives}
    storages_inv  = {name:pd.DataFrame(storages_inv_list[name],columns=["storage_name"]+years) for name in latest_alternatives}
    storages_dec  = {name:pd.DataFrame(storages_dec_list[name],columns=["storage_name"]+years) for name in latest_alternatives}
    storages_cost = {name:pd.DataFrame(storages_cost_list[name],columns=["storage_name"]+years) for name in latest_alternatives}
    units_cap     = {name:pd.DataFrame(units_cap_list[name],columns=["unit_name"]+years) for name in latest_alternatives}
    units_inv     = {name:pd.DataFrame(units_inv_list[name],columns=["unit_name"]+years) for name in latest_alternatives}
    units_dec     = {name:pd.DataFrame(units_dec_list[name],columns=["unit_name"]+years) for name in latest_alternatives}
    units_inv_cost= {name:pd.DataFrame(units_inv_cost_list[name],columns=["unit_name"]+years) for name in latest_alternatives}
    
    return unit_to_flows, energy_map, unit_to_node_map, emission_map, units_cap, units_inv, units_inv_cost, units_dec, storages_cap, storages_inv, storages_cost, storages_dec, connections_cap, connections_inv, connections_dec, flows_map, flows_sto, node_state

def get_representative_periods():

    rps={}
    for entity_tb in sopt_db.get_parameter_value_items(parameter_definition_name = "block_start"):

        if "representative_period" in entity_tb["entity_byname"][0]:
            if entity_tb["entity_byname"][0] not in rps:
                rps[entity_tb["entity_byname"][0]] = {}

            if entity_tb["alternative_name"] not in rps[entity_tb["entity_byname"][0]]:
                rps[entity_tb["entity_byname"][0]][entity_tb["alternative_name"]] = {}
                 
            rps[entity_tb["entity_byname"][0]][entity_tb["alternative_name"]]["start"] = json.loads(entity_tb["value"])["data"]
            block_end = sopt_db.get_parameter_value_item(entity_class_name = "temporal_block", alternative_name = entity_tb["alternative_name"], entity_byname = entity_tb["entity_byname"], parameter_definition_name = "block_end")
            rps[entity_tb["entity_byname"][0]][entity_tb["alternative_name"]]["end"] = (pd.Timestamp(json.loads(block_end["value"])["data"])-pd.Timedelta("1h")).isoformat()
            weight = sopt_db.get_parameter_value_item(entity_class_name = "temporal_block", alternative_name = entity_tb["alternative_name"], entity_byname = entity_tb["entity_byname"], parameter_definition_name = "weight")
            rps[entity_tb["entity_byname"][0]][entity_tb["alternative_name"]]["weight"] = weight["parsed_value"]
            rps[entity_tb["entity_byname"][0]][entity_tb["alternative_name"]]["dates"] = pd.date_range(start=rps[entity_tb["entity_byname"][0]][entity_tb["alternative_name"]]["start"],end=rps[entity_tb["entity_byname"][0]][entity_tb["alternative_name"]]["end"],freq="1h").tolist()

    if rps:
        indexes = {}
        weights = {}
        for rp in rps:
            for alternative in rps[rp]:
                if alternative not in indexes:
                    indexes[alternative] = []
                indexes[alternative] += rps[rp][alternative]["dates"]
                if alternative not in weights:
                    weights[alternative] = []
                weights[alternative] += [rps[rp][alternative]["weight"]]*len(rps[rp][alternative]["dates"])

        all_rps_years = {alternative:pd.DataFrame(weights[alternative],index=indexes[alternative],columns=["weight"]).sort_index() for alternative in indexes}
        concat_alter = {}
        for alternative in all_rps_years:
            if alternative not in concat_alter:
                concat_alter[alternative] = []
            concat_alter[alternative].append(alternative)
        
        all_rps={alternative:pd.concat([all_rps_years[alt_i] for alt_i in concat_alter[alternative]],ignore_index=False) for alternative in concat_alter}
    else:
        all_rps = {}
    return all_rps

def run_streamlit_app(app_path: str):
    original_argv = sys.argv.copy()
    try:
        sys.argv = ["streamlit", "run", app_path]
        stcli.main()
    finally:
        sys.argv = original_argv

def clean_storage_flows(energy_map,unit_to_node_map,map_years):

    for storage in storage_bi_node_map:
        sto_indexes = energy_map[energy_map["source"] == storage].index
        for sto_i in sto_indexes:
            unit_name_dir1 = energy_map.at[sto_i,"target"]
            unit_name_dir2 = "__".join([unit_name_dir1.split("__")[1],unit_name_dir1.split("__")[0]])
            unit_to_node_map[unit_name_dir2] = storage
            com_i  = energy_map[(energy_map["source"] == storage_bi_node_map[storage])&(energy_map["target"] == unit_name_dir1)].index[0]
            energy_map.loc[com_i,"target"] = unit_name_dir2

    return energy_map, unit_to_node_map

def check_flexible_resolution():
    resolutions = {}

    for otb in sopt_db.get_parameter_value_items(parameter_definition_name = "resolution"):
        if "operations" in otb["entity_byname"][0] and otb["alternative_name"]!="Base":
            if otb["type"] == "array":
                list_values = json.loads(otb["value"])["data"]
                weights = [pd.Timedelta(i).total_seconds()/3600 for i in list_values]
                resolutions[int(otb["entity_byname"][0].split("_")[1][1:])] = np.array(weights)

    return resolutions

def main():

    resolution = 1
    map_years = {2030:"y2030",2041:"y2040",2050:"y2050"}
    unit_to_flows, energy_map, unit_to_node_map, emission_map, units_cap, units_inv, units_inv_cost, units_dec, storages_cap, storages_inv, storages_cost, storages_dec, connections_cap, connections_inv, connections_dec, flows_map, flows_sto, node_state = copy.deepcopy(from_DB_to_df(map_years))

    node_state = {scenario_map.get(k, k): v for k, v in node_state.items()}
    with open('files_out/node_state.dill', 'wb') as file:
        dill.dump(node_state,file)

    energy_list   = []
    emission_list = []

    for alternative_name in energy_map:
        energy_map[alternative_name]["polygon"] = energy_map[alternative_name]["target"].map(extract_polygon)
        energy_map[alternative_name], unit_to_node_map = clean_storage_flows(energy_map[alternative_name],unit_to_node_map, map_years)
        energy_map[alternative_name]["technology"] = energy_map[alternative_name]["target"].values
        energy_map[alternative_name]["target"] = energy_map[alternative_name]["target"].map(unit_to_node_map)
        energy_map[alternative_name]["target"] = energy_map[alternative_name]["target"].map(node_map_sankey)
        energy_map[alternative_name]["source"] = energy_map[alternative_name]["source"].map(node_map_sankey)
        energy_map[alternative_name][list(map_years.values())] /= 1e3
        energy_map[alternative_name] = energy_map[alternative_name][energy_map[alternative_name]["source"] != energy_map[alternative_name]["target"]]
        energy_map[alternative_name] = energy_map[alternative_name][energy_map[alternative_name][list(map_years.values())].sum(axis=1) > 0.001]
        energy_map[alternative_name]["scenario"] = alternative_name
        energy_list.append(energy_map[alternative_name])

        emission_map[alternative_name]["polygon"] = emission_map[alternative_name]["target"].map(extract_polygon)
        emission_map[alternative_name].loc[emission_map[alternative_name]["polygon"]=="re","polygon"] = emission_map[alternative_name]["source"].map(extract_polygon).loc[emission_map[alternative_name]["polygon"]=="re"].values
        emission_map[alternative_name]["technology"] = emission_map[alternative_name]["target"].values
        emission_map[alternative_name]["target"] = emission_map[alternative_name]["target"].map(unit_to_node_map|{"atmosphere":"atmosphere"})
        emission_map[alternative_name]["source"] = emission_map[alternative_name]["source"].map(unit_to_node_map|{"atmosphere":"atmosphere"})
        emission_map[alternative_name]["target"] = emission_map[alternative_name]["target"].map(node_map)
        emission_map[alternative_name]["source"] = emission_map[alternative_name]["source"].map(node_map)
        # [alternative_name] = emission_map[alternative_name].groupby(["source","target"]).sum().reset_index()
        emission_map[alternative_name] = emission_map[alternative_name][emission_map[alternative_name][list(map_years.values())].sum(axis=1) > 0.001]
        emission_map[alternative_name]["scenario"] = alternative_name
        emission_list.append(emission_map[alternative_name])

    energy_df = pd.concat(energy_list,axis=0,ignore_index=True)
    emission_df = pd.concat(emission_list,axis=0,ignore_index=True)
    energy_df["scenario"] = energy_df["scenario"].map(scenario_map)
    emission_df["scenario"] = emission_df["scenario"].map(scenario_map)
    energy_df.to_csv(f"files_out/energy_flows.csv")
    emission_df.to_csv(f"files_out/emissions_flows.csv")

    installed_cap = []
    for alte_name in units_cap:
        units_cap[alte_name]["node"] = units_cap[alte_name]["unit_name"].values
        units_cap[alte_name]["node"] = units_cap[alte_name]["node"].map(unit_to_node_map)
        units_cap[alte_name]["node"] = units_cap[alte_name]["node"].map(node_map)
        units_cap[alte_name] = units_cap[alte_name][units_cap[alte_name][list(map_years.values())].sum(axis=1) > 0.001]
        units_cap[alte_name]["scenario"] = alte_name
        installed_cap.append(units_cap[alte_name])
    installed_cap_df = pd.concat(installed_cap,axis=0,ignore_index=True)
    installed_cap_df['polygon'] = installed_cap_df["unit_name"].map(extract_polygon)
    installed_cap_df['technology'] = installed_cap_df["unit_name"].map(apply_unit_name)
    installed_cap_df["scenario"] = installed_cap_df["scenario"].map(scenario_map)
    installed_cap_df_total = (installed_cap_df.groupby(["node","technology","scenario"], dropna=False)[["y2030","y2040","y2050"]].sum().reset_index()).assign(polygon="Europe", unit_name="EU_total")
    installed_cap_df = pd.concat([installed_cap_df,installed_cap_df_total],ignore_index=True)
    installed_cap_df.round(2).to_csv("files_out/installed_capacity.csv")

    invested_cap = []
    for alte_name in units_inv:
        units_inv[alte_name]["node"] = units_inv[alte_name]["unit_name"].values
        units_inv[alte_name]["node"] = units_inv[alte_name]["node"].map(unit_to_node_map)
        units_inv[alte_name]["node"] = units_inv[alte_name]["node"].map(node_map)
        units_inv[alte_name] = units_inv[alte_name][units_inv[alte_name][list(map_years.values())].sum(axis=1) > 0.001]
        units_inv[alte_name]["scenario"] = alte_name
        invested_cap.append(units_inv[alte_name])
    invested_cap_df = pd.concat(invested_cap,axis=0,ignore_index=True)
    invested_cap_df['polygon'] = invested_cap_df["unit_name"].map(extract_polygon)
    invested_cap_df['technology'] = invested_cap_df["unit_name"].map(apply_unit_name)
    invested_cap_df["scenario"] = invested_cap_df["scenario"].map(scenario_map)
    invested_cap_df_total = (invested_cap_df.groupby(["node","technology","scenario"], dropna=False)[["y2030","y2040","y2050"]].sum().reset_index()).assign(polygon="Europe", unit_name="EU_total")
    invested_cap_df = pd.concat([invested_cap_df,invested_cap_df_total],ignore_index=True)
    invested_cap_df.round(2).to_csv("files_out/invested_capacity.csv")

    invested_cost = []
    for alte_name in units_inv_cost:
        units_inv_cost[alte_name]["node"] = units_inv_cost[alte_name]["unit_name"].values
        units_inv_cost[alte_name]["node"] = units_inv_cost[alte_name]["node"].map(unit_to_node_map)
        units_inv_cost[alte_name]["node"] = units_inv_cost[alte_name]["node"].map(node_map)
        units_inv_cost[alte_name] = units_inv_cost[alte_name][units_inv_cost[alte_name][list(map_years.values())].sum(axis=1) > 0.001]
        units_inv_cost[alte_name]["scenario"] = alte_name
        invested_cost.append(units_inv_cost[alte_name])
    invested_cost_df = pd.concat(invested_cost,axis=0,ignore_index=True)
    invested_cost_df['polygon'] = invested_cost_df["unit_name"].map(extract_polygon)
    invested_cost_df['technology'] = invested_cost_df["unit_name"].map(apply_unit_name)
    invested_cost_df["scenario"] = invested_cost_df["scenario"].map(scenario_map)
    invested_cost_df_total = (invested_cost_df.groupby(["node","technology","scenario"], dropna=False)[["y2030","y2040","y2050"]].sum().reset_index()).assign(polygon="Europe", unit_name="EU_total")
    invested_cost_df = pd.concat([invested_cost_df,invested_cost_df_total],ignore_index=True)
    invested_cost_df.round(2).to_csv("files_out/invested_cost.csv")

    decommissioned = []
    for alte_name in units_dec:
        units_dec[alte_name]["node"] = units_dec[alte_name]["unit_name"].values
        units_dec[alte_name]["node"] = units_dec[alte_name]["node"].map(unit_to_node_map)
        units_dec[alte_name]["node"] = units_dec[alte_name]["node"].map(node_map)
        units_dec[alte_name] = units_dec[alte_name][units_dec[alte_name][list(map_years.values())].sum(axis=1) > 0.001]
        units_dec[alte_name]["scenario"] = alte_name
        decommissioned.append(units_dec[alte_name])
    decommissioned_df = pd.concat(decommissioned,axis=0,ignore_index=True)
    decommissioned_df['polygon'] = decommissioned_df["unit_name"].map(extract_polygon)
    decommissioned_df['technology'] = decommissioned_df["unit_name"].map(apply_unit_name)
    decommissioned_df["scenario"] = decommissioned_df["scenario"].map(scenario_map)
    decommissioned_df_total = (decommissioned_df.groupby(["node","technology","scenario"], dropna=False)[["y2030","y2040","y2050"]].sum().reset_index()).assign(polygon="Europe", unit_name="EU_total")
    decommissioned_df = pd.concat([decommissioned_df,decommissioned_df_total],ignore_index=True)
    decommissioned_df.round(2).to_csv("files_out/decommissioned_capacity.csv")

    unit2node_flow = []
    for alte_name in unit_to_flows:
        unit_to_flows[alte_name]["node"] = unit_to_flows[alte_name]["node"].map(node_map)
        unit_to_flows[alte_name] = unit_to_flows[alte_name][unit_to_flows[alte_name][list(map_years.values())].sum(axis=1) > 0.001]
        unit_to_flows[alte_name]["scenario"] = alte_name
        unit2node_flow.append(unit_to_flows[alte_name])
    unit2node_flow_df = pd.concat(unit2node_flow,axis=0,ignore_index=True)
    unit2node_flow_df['polygon'] = unit2node_flow_df["unit_name"].map(extract_polygon)
    unit2node_flow_df['technology'] = unit2node_flow_df["unit_name"].map(apply_unit_name)
    unit2node_flow_df["scenario"] = unit2node_flow_df["scenario"].map(scenario_map)
    unit2node_flow_df_total = (unit2node_flow_df.groupby(["node","technology","scenario"], dropna=False)[["y2030","y2040","y2050"]].sum().reset_index()).assign(polygon="Europe", unit_name="EU_total")
    unit2node_flow_df = pd.concat([unit2node_flow_df,unit2node_flow_df_total],ignore_index=True)
    unit2node_flow_df.round(2).to_csv("files_out/unit_to_flows.csv")

    installed_sto_cap = []
    for alte_name in storages_cap:
        storages_cap[alte_name]["technology"] = storages_cap[alte_name]["storage_name"].str.split('_', n=1).str[0]
        storages_cap[alte_name]["node"] = storages_cap[alte_name]["technology"].map(storage_node_map)
        storages_cap[alte_name] = storages_cap[alte_name][storages_cap[alte_name][list(map_years.values())].sum(axis=1) > 0.001]
        storages_cap[alte_name]["scenario"] = alte_name
        installed_sto_cap.append(storages_cap[alte_name])
    installed_sto_cap_df = pd.concat(installed_sto_cap,axis=0,ignore_index=True)
    installed_sto_cap_df['polygon'] = installed_sto_cap_df["storage_name"].map(extract_polygon)
    installed_sto_cap_df["scenario"] = installed_sto_cap_df["scenario"].map(scenario_map)
    installed_sto_cap_df_total = (installed_sto_cap_df.groupby(["node","technology","scenario"], dropna=False)[["y2030","y2040","y2050"]].sum().reset_index()).assign(polygon="Europe", storage_name="EU_total")
    installed_sto_cap_df = pd.concat([installed_sto_cap_df,installed_sto_cap_df_total],ignore_index=True)
    installed_sto_cap_df.round(2).to_csv("files_out/storage_installed_capacity.csv")

    installed_sto_cost = []
    for alte_name in storages_cost:
        storages_cost[alte_name]["technology"] = storages_cost[alte_name]["storage_name"].str.split('_', n=1).str[0]
        storages_cost[alte_name]["node"] = storages_cost[alte_name]["technology"].map(storage_node_map)
        storages_cost[alte_name] = storages_cost[alte_name][storages_cost[alte_name][list(map_years.values())].sum(axis=1) > 0.001]
        storages_cost[alte_name]["scenario"] = alte_name
        installed_sto_cost.append(storages_cost[alte_name])
    installed_sto_cost_df = pd.concat(installed_sto_cost,axis=0,ignore_index=True)
    installed_sto_cost_df['polygon'] = installed_sto_cost_df["storage_name"].map(extract_polygon)
    installed_sto_cost_df["scenario"] = installed_sto_cost_df["scenario"].map(scenario_map)
    installed_sto_cost_df_total = (installed_sto_cost_df.groupby(["node","technology","scenario"], dropna=False)[["y2030","y2040","y2050"]].sum().reset_index()).assign(polygon="Europe", storage_name="EU_total")
    installed_sto_cost_df = pd.concat([installed_sto_cost_df,installed_sto_cost_df_total],ignore_index=True)
    installed_sto_cost_df.round(2).to_csv("files_out/storage_cost_capacity.csv")

    installed_sto_inv = []
    for alte_name in storages_inv:
        storages_inv[alte_name]["technology"] = storages_inv[alte_name]["storage_name"].str.split('_', n=1).str[0]
        storages_inv[alte_name]["node"] = storages_inv[alte_name]["technology"].map(storage_node_map)
        storages_inv[alte_name] = storages_inv[alte_name][storages_inv[alte_name][list(map_years.values())].sum(axis=1) > 0.001]
        storages_inv[alte_name]["scenario"] = alte_name
        installed_sto_inv.append(storages_inv[alte_name])
    installed_sto_inv_df = pd.concat(installed_sto_inv,axis=0,ignore_index=True)
    installed_sto_inv_df['polygon'] = installed_sto_inv_df["storage_name"].map(extract_polygon)
    installed_sto_inv_df["scenario"] = installed_sto_inv_df["scenario"].map(scenario_map)
    installed_sto_inv_df_total = (installed_sto_inv_df.groupby(["node","technology","scenario"], dropna=False)[["y2030","y2040","y2050"]].sum().reset_index()).assign(polygon="Europe", storage_name="EU_total")
    installed_sto_inv_df = pd.concat([installed_sto_inv_df,installed_sto_inv_df_total],ignore_index=True)
    installed_sto_inv_df.round(2).to_csv("files_out/storage_invested_capacity.csv")

    installed_sto_dec = []
    for alte_name in storages_dec:
        storages_dec[alte_name]["technology"] = storages_dec[alte_name]["storage_name"].str.split('_', n=1).str[0]
        storages_dec[alte_name]["node"] = storages_dec[alte_name]["technology"].map(storage_node_map)
        storages_dec[alte_name] = storages_dec[alte_name][storages_dec[alte_name][list(map_years.values())].sum(axis=1) > 0.001]
        storages_dec[alte_name]["scenario"] = alte_name
        installed_sto_dec.append(storages_dec[alte_name])
    installed_sto_dec_df = pd.concat(installed_sto_dec,axis=0,ignore_index=True)
    installed_sto_dec_df['polygon'] = installed_sto_dec_df["storage_name"].map(extract_polygon)
    installed_sto_dec_df["scenario"] = installed_sto_dec_df["scenario"].map(scenario_map)
    installed_sto_dec_df_total = (installed_sto_dec_df.groupby(["node","technology","scenario"], dropna=False)[["y2030","y2040","y2050"]].sum().reset_index()).assign(polygon="Europe", storage_name="EU_total")
    installed_sto_dec_df = pd.concat([installed_sto_dec_df,installed_sto_dec_df_total],ignore_index=True)
    installed_sto_dec_df.round(2).to_csv("files_out/storage_decommissioned_capacity.csv")

    flows = []
    for alternative_name in flows_map:
        flows_map[alternative_name]["commodity"] = flows_map[alternative_name]["commodity"].map(node_map)
        flows_map[alternative_name][list(map_years.values())] *= resolution/1e3
        flows_map[alternative_name] = flows_map[alternative_name][flows_map[alternative_name]["source"] != flows_map[alternative_name]["target"]]
        flows_map[alternative_name] = flows_map[alternative_name][flows_map[alternative_name][list(map_years.values())].sum(axis=1) > 0.001]
        # Merging both directions of the flow
        '''flows_map[alternative_name]['pair'] = flows_map[alternative_name].apply(lambda x: '-'.join(sorted([x['source'], x['target']])), axis=1)
        flows_map[alternative_name] = flows_map[alternative_name].groupby(['pair', 'commodity'], as_index=False)[['y2030','y2040','y2050']].sum()
        flows_map[alternative_name][['source','target']] = flows_map[alternative_name]['pair'].str.split('-', expand=True)
        flows_map[alternative_name] = flows_map[alternative_name].drop(columns=['pair'])'''
        flows_map[alternative_name]["scenario"] = alternative_name
        flows_map[alternative_name] = flows_map[alternative_name][["source","target","commodity","y2030","y2040","y2050","scenario"]]
        flows.append(flows_map[alternative_name])
    flows_df = pd.concat(flows,axis=0,ignore_index=True)
    flows_df["scenario"] = flows_df["scenario"].map(scenario_map)
    flows_df.to_csv("files_out/crossborder_flows.csv")

    flow_av = []
    for alternative_name in connections_cap:
        connections_cap[alternative_name]["commodity"] = connections_cap[alternative_name]["commodity"].map(node_map)
        connections_cap[alternative_name] = connections_cap[alternative_name][connections_cap[alternative_name]["source"] != connections_cap[alternative_name]["target"]]
        connections_cap[alternative_name] = connections_cap[alternative_name][connections_cap[alternative_name][list(map_years.values())].sum(axis=1) > 0.001]
        connections_cap[alternative_name]["scenario"] = alternative_name
        connections_cap[alternative_name] = connections_cap[alternative_name][["source","target","commodity","y2030","y2040","y2050","scenario"]]
        flow_av.append(connections_cap[alternative_name])
    flow_av_df = pd.concat(flow_av,axis=0,ignore_index=True)
    flow_av_df["scenario"] = flow_av_df["scenario"].map(scenario_map)
    flow_av_df.to_csv("files_out/crossborder_capacity.csv")

    flow_in = []
    for alternative_name in connections_inv:
        connections_inv[alternative_name]["commodity"] = connections_inv[alternative_name]["commodity"].map(node_map)
        connections_inv[alternative_name] = connections_inv[alternative_name][connections_inv[alternative_name]["source"] != connections_inv[alternative_name]["target"]]
        connections_inv[alternative_name] = connections_inv[alternative_name][connections_inv[alternative_name][list(map_years.values())].sum(axis=1) > 0.001]
        connections_inv[alternative_name]["scenario"] = alternative_name
        connections_inv[alternative_name] = connections_inv[alternative_name][["source","target","commodity","y2030","y2040","y2050","scenario"]]
        flow_in.append(connections_inv[alternative_name])
    flow_in_df = pd.concat(flow_in,axis=0,ignore_index=True)
    flow_in_df["scenario"] = flow_in_df["scenario"].map(scenario_map)
    flow_in_df.to_csv("files_out/crossborder_invested.csv")

    flow_de = []
    for alternative_name in connections_dec:
        connections_dec[alternative_name]["commodity"] = connections_dec[alternative_name]["commodity"].map(node_map)
        connections_dec[alternative_name] = connections_dec[alternative_name][connections_dec[alternative_name]["source"] != connections_dec[alternative_name]["target"]]
        connections_dec[alternative_name] = connections_dec[alternative_name][connections_dec[alternative_name][list(map_years.values())].sum(axis=1) > 0.001]
        connections_dec[alternative_name]["scenario"] = alternative_name
        connections_dec[alternative_name] = connections_dec[alternative_name][["source","target","commodity","y2030","y2040","y2050","scenario"]]
        flow_de.append(connections_dec[alternative_name])
    flow_de_df = pd.concat(flow_de,axis=0,ignore_index=True)
    flow_de_df["scenario"] = flow_de_df["scenario"].map(scenario_map)
    flow_de_df.to_csv("files_out/crossborder_decommissioned.csv")
    
if __name__ == "__main__":
    main()
    print("Time spent organizing the results ",time_lib.time() - start_time)
    # run_streamlit_app("app.py")
