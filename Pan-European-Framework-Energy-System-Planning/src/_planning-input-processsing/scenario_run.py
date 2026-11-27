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
import re
import yaml 
import time as time_lib


if len(sys.argv) > 1:
    url_spineopt = sys.argv[1]
else:
    exit("Please provide spineopt database url as argument. They should be of the form ""sqlite:///path/db_file.sqlite""")

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

def update_parameter_value(db_map : DatabaseMapping, id_int : int, class_name : str,parameter : str,alternative : str,elements : tuple,value : any) -> None:
    db_value, value_type = api.to_database(value)
    _, error = db_map.update_parameter_value_item(id=id_int, entity_class_name=class_name,entity_byname=elements,parameter_definition_name=parameter,alternative_name=alternative,value=db_value,type=value_type)
    if error:
        raise RuntimeError(error)

def add_or_update_parameter_value(db_map : DatabaseMapping, class_name : str,parameter : str,alternative : str,elements : tuple,value : any) -> None:
    db_value, value_type = api.to_database(value)
    db_map.add_or_update_parameter_value(entity_class_name=class_name,entity_byname=elements,parameter_definition_name=parameter,alternative_name=alternative,value=db_value,type=value_type)

def _scaled_value(target_parameter : dict, factor : float):
    """Multiply a stored parameter value by `factor`, preserving its Spine type.

    The stored JSON of a time_series holds only {"data": {...}} - the "type" lives
    in a separate database column. Round-tripping json.loads(value) straight back
    through api.to_database() therefore raises KeyError: 'type'. Re-attach the type
    so the value can be written back unchanged in form, only scaled in magnitude.

    Handles float and time_series; anything else is returned untouched rather than
    silently dropped, which is what the original if/elif did when it fell through
    (leaving parameter_value bound to the *previous* iteration's value).
    """
    ptype = target_parameter["type"]
    if ptype == "float":
        return target_parameter["parsed_value"] * factor
    if ptype == "time_series":
        raw = json.loads(target_parameter["value"])
        raw["data"] = {k: v * factor for k, v in raw["data"].items()}
        raw.setdefault("type", "time_series")
        return raw
    return target_parameter["parsed_value"]

def _rp_scaling(config) -> float:
    """Divisor for annual (cumulative) budgets that SpineOpt debits once per representative
    block while flows are weighted to a full year (docs/FINDING_co2_storage_cap_365x.md).
    1.0 (default) leaves values unchanged; 365 for daily representative periods."""
    return float(config.get("representative_period_scaling", 1.0))

def add_entity_group(db_map : DatabaseMapping, class_name : str, group : str, member : str) -> None:
    _, error = db_map.add_entity_group_item(group_name = group, member_name = member, entity_class_name=class_name)
    if error is not None:
        raise RuntimeError(error)

def add_entity(db_map : DatabaseMapping, class_name : str, name : tuple, ent_description = None) -> None:
    _, error = db_map.add_entity_item(entity_byname=name, entity_class_name=class_name, description = ent_description)
    if error is not None:
        raise RuntimeError(error)

def add_parameter_value(db_map : DatabaseMapping,class_name : str,parameter : str,alternative : str,elements : tuple,value : any) -> None:
    db_value, value_type = api.to_database(value)
    _, error = db_map.add_parameter_value_item(entity_class_name=class_name,entity_byname=elements,parameter_definition_name=parameter,alternative_name=alternative,value=db_value,type=value_type)
    if error:
        raise RuntimeError(error)

def add_scenario(db_map : DatabaseMapping,name_scenario : str) -> None:
    _, error = db_map.add_scenario_item(name=name_scenario)
    if error is not None:
        raise RuntimeError(error)

def add_alternative(db_map : DatabaseMapping,name_alternative : str) -> None:
    _, error = db_map.add_alternative_item(name=name_alternative)
    if error is not None:
        raise RuntimeError(error)
    
def add_scenario_alternative(db_map : DatabaseMapping,name_scenario : str, name_alternative : str, rank_int = None) -> None:
    _, error = db_map.add_scenario_alternative_item(scenario_name = name_scenario, alternative_name = name_alternative, rank = rank_int)
    if error is not None:
        raise RuntimeError(error)

def add_entity_alternative(db_map : DatabaseMapping,entity_class_name : str, entity_byname : tuple, alternative_name = str, active = bool) -> None:
    _, error = db_map.add_entity_alternative_item(entity_class_namee = entity_class_name, entity_byname = entity_byname, alternative_name = alternative_name, active = active)
    if error is not None:
        raise RuntimeError(error)
    
def scenario_development(config):

    with DatabaseMapping(url_spineopt) as sopt_db:

        scenarios_in_db = [scenario_i["name"] for scenario_i in sopt_db.get_scenario_items()]
        for scenario_name in config["scenarios"]:
            
            if scenario_name not in scenarios_in_db:
                add_scenario(sopt_db,scenario_name)
                alt_names = config["scenarios"][scenario_name]
                for alt_name in alt_names:
                    add_scenario_alternative(sopt_db,scenario_name,alt_name,alt_names.index(alt_name)+1)
        try:
            sopt_db.commit_session("Added scenario")
        except:
            print("###################################################################### commit error")  

def storage_setup(config):

    with DatabaseMapping(url_spineopt) as sopt_db:
        list_rep = [entity_i["name"] for entity_i in sopt_db.get_entity_items(entity_class_name = "temporal_block") if "representative_period" in entity_i["name"]]
        list_otb = [entity_i["name"] for entity_i in sopt_db.get_entity_items(entity_class_name = "temporal_block") if "operations" in entity_i["name"]]                    

        cyclic_conditions = sopt_db.get_parameter_value_items(entity_class_name = "node__temporal_block", alternative_name = "Base", parameter_definition_name = "cyclic_condition")
        for param_map in sopt_db.get_parameter_value_items(entity_class_name = "node", parameter_definition_name = "storage_active"):
            if bool(param_map["parsed_value"]):
                if all(sto+"_" not in param_map["entity_byname"][0] for sto in config["short-term-storage"]):
                    add_or_update_parameter_value(sopt_db,"node","storage_longterm_active","Base",(param_map["entity_byname"][0],),True)
                    cyclic_condition_status = [entity_i for entity_i in cyclic_conditions if param_map["entity_byname"][0] == entity_i["entity_byname"][0]]
                    if cyclic_condition_status and sopt_db.get_entity_item(entity_class_name = "temporal_block",name = "all_rps"):
                        try:
                            add_entity(sopt_db,"node__temporal_block",(param_map["entity_byname"][0],"all_rps"))
                        except:
                            print(f"Entity class node__temporal_block with all_rps already added")
                            pass
                    elif any(sto+"_" in param_map["entity_byname"][0] for sto in config["long-term-storage"]):
                        if list_rep:
                            add_entity(sopt_db,"node__temporal_block",(param_map["entity_byname"][0],"all_rps"))
                        for tb in list_otb:
                            add_entity(sopt_db,"node__temporal_block",(param_map["entity_byname"][0],tb))
                            add_or_update_parameter_value(sopt_db,"node__temporal_block","cyclic_condition","Base",(param_map["entity_byname"][0],tb),True)

                else:
                    if list_rep:
                        # identifying long-term cyclic condition
                        for node_map in sopt_db.get_entity_items(entity_class_name = "node__temporal_block"):
                            if node_map["entity_byname"][0] == param_map["entity_byname"][0]:
                                item_id = node_map["id"]
                                sopt_db.remove_item("entity",item_id)
                        for rep in list_rep:
                            try:
                                add_entity(sopt_db,"node__temporal_block",(param_map["entity_byname"][0],rep))
                            except:
                                print(f"Entity node__temporal_block with {rep}")
                                pass
                            add_or_update_parameter_value(sopt_db,"node__temporal_block","cyclic_condition","Base",(param_map["entity_byname"][0],rep),True)
                    else:
                        add_or_update_parameter_value(sopt_db,"node","storage_longterm_active","Base",(param_map["entity_byname"][0],),True)
                        for tb in list_otb:
                            try:
                                add_entity(sopt_db,"node__temporal_block",(param_map["entity_byname"][0],tb))
                            except:
                                print(f"Entity node__temporal_block with {tb}")
                                pass
                            add_or_update_parameter_value(sopt_db,"node__temporal_block","cyclic_condition","Base",(param_map["entity_byname"][0],tb),True)
        try:
            sopt_db.commit_session("Added storage_setup")
        except:
            print("###################################################################### commit error") 

def update_parameters(config):

    with DatabaseMapping(url_spineopt) as sopt_db:

        resolution_ = config["resolution"]
        parameter_value = {"type":"duration","data":resolution_}
        # operations_* blocks may get their own (coarse) resolution, see collapse_representative_maps
        ops_value = {"type":"duration","data":config["operations_resolution"]} if config.get("operations_resolution") else parameter_value
        for parameter_map in sopt_db.get_parameter_value_items(parameter_definition_name = "resolution"):
            if "planning" not in parameter_map["entity_byname"][0]:
                value_ = ops_value if parameter_map["entity_byname"][0].startswith("operations") else parameter_value
                add_or_update_parameter_value(sopt_db, parameter_map["entity_class_name"], "resolution", parameter_map["alternative_name"], parameter_map["entity_byname"], value_)
            # IC1 fix: the EU case has a single node named exactly "CO2-storage", but IC1
        # names sequestration sites per reservoir - "CO2-storage-NSNL012" and
        # "CO2-storage-NSNL031" (each with low_CO2/medium_CO2/high_CO2 series). An exact
        # entity_byname match therefore selected nothing and emission_factor was never
        # applied to the sequestration caps, while it WAS applied to the atmosphere
        # budget. That asymmetry would silently under-provision CCS whenever
        # emission_factor != 1.0. Match by prefix so every site is scaled.
        for co2_parameter in ["storage_investment_count_fix_cumulative"]:
            target_parameters = [
                p for p in sopt_db.get_parameter_value_items(
                    entity_class_name="node", parameter_definition_name=co2_parameter)
                if str(p["entity_byname"][0]).startswith("CO2-storage")
            ]
            for target_parameter in target_parameters:
                entity_byname = target_parameter["entity_byname"]
                parameter_value = _scaled_value(target_parameter, config["emission_factor"]/_rp_scaling(config))
                add_or_update_parameter_value(sopt_db, "node", co2_parameter, target_parameter["alternative_name"], entity_byname, parameter_value)

        # The atmosphere carbon budget enters SpineOpt as a *variable bound*:
        # variable_node_state.jl:169 sets
        #     node_state_ub = node_state_capacity * (existing + storage_investment_count_max_cumulative)
        # so with a 2050 cap of 0 the bound is a hard zero that balance_penalty cannot
        # relax (that only prices node_slack_pos/neg on the node balance).
        #
        # This is deliberate, not a bug: the EU reference case has the same trajectory
        # (2030=520, 2041=116, 2050=0, 2060=0) and solved with no balance_penalty at all.
        # Net zero is met through the CCS chain, so the cap is left untouched here.
        # Do not floor it to force feasibility - that would hide a broken CCS chain.
        for atm_parameter in ["storage_investment_count_initial_cumulative","storage_investment_count_max_cumulative"]:
            target_parameters = sopt_db.get_parameter_value_items(entity_class_name = "node", entity_byname = ("atmosphere", ), parameter_definition_name = atm_parameter)
            for target_parameter in target_parameters:
                parameter_value = _scaled_value(target_parameter, config["emission_factor"]/_rp_scaling(config))
                add_or_update_parameter_value(sopt_db, "node", atm_parameter, target_parameter["alternative_name"], ("atmosphere", ), parameter_value)

        # Secondary, cheaper relief: prices the node balance slack. Kept because it does
        # help where emissions violate the atmosphere *balance* rather than its bound,
        # but on its own it does NOT rescue a zero budget cap - see the note above.
        if config.get("co2_overshoot_penalty"):
            add_or_update_parameter_value(sopt_db, "node", "balance_penalty", "Base", ("atmosphere", ), float(config["co2_overshoot_penalty"]))

        try:
            sopt_db.commit_session("Update parameters")
        except:
            print("###################################################################### commit error")  

def fix_no_investable_by_2030(config):

    indexes_ = ["2030-01-01T00:00:00","2040-01-01T00:00:00","2050-01-01T00:00:00","2060-01-01T00:00:00"]
    values_ = [0.0,None,None,None]
    parameter_value = {"type":"time_series","data":dict(zip(indexes_,values_))}

    parameter_name_map = {"unit":"investment_count_fix_new","node":"storage_investment_count_fix_new","connection":"investment_count_fix_new"}

    with DatabaseMapping(url_spineopt) as sopt_db:
        fix_config = config["no_investable_2030"]
        parsed_entities = {class_i:[entity_map["name"] for entity_map in sopt_db.get_entity_items(entity_class_name=class_i) if entity_map["name"].split("_")[0] in fix_config[class_i]] for class_i in ["unit","node"]}

        parsed_entities["connection"] = []
        for entity_map in sopt_db.get_entity_items(entity_class_name="connection"):
            if entity_map["name"].split("_")[1] in fix_config["connection"]:
                parsed_entities["connection"].append(entity_map["name"])
                
        for entity_class in parsed_entities:
            for entity_name in parsed_entities[entity_class]:
                check_existing_param = sopt_db.get_parameter_value_items(entity_class_name = entity_class, parameter_definition_name = parameter_name_map[entity_class], entity_byname = (entity_name,))
                if not check_existing_param:
                    add_parameter_value(sopt_db,entity_class,parameter_name_map[entity_class],"Base",(entity_name,),parameter_value)

        try:
            sopt_db.commit_session("fix invested variables")
        except:
            print("###################################################################### fix invested variables commit error")  

def ramping_constraints(config):

    if config["include_ramping"]:
        print("Ramping constraints included")
        with DatabaseMapping(url_spineopt) as sopt_db:
            entities = [entity_i for entity_i in sopt_db.get_entity_items(entity_class_name = "unit__to_node") if any(tech in entity_i["entity_byname"][0] for tech in config["ramping"])]
            for entity in entities:
                for tech in config["ramping"]:
                    if tech in entity["entity_byname"][0] and config["ramping"][tech][0] in entity["entity_byname"][1]:
                        ramp_value = config["ramping"][tech][1]
                        add_or_update_parameter_value(sopt_db,"unit__to_node","ramp_up_limit","Base",entity["entity_byname"],ramp_value)
                        add_or_update_parameter_value(sopt_db,"unit__to_node","ramp_down_limit","Base",entity["entity_byname"],ramp_value)
                        add_or_update_parameter_value(sopt_db,"unit__to_node","start_up_limit","Base",entity["entity_byname"],ramp_value)
                        add_or_update_parameter_value(sopt_db,"unit__to_node","shut_down_limit","Base",entity["entity_byname"],ramp_value)
                        break

            try:
                sopt_db.commit_session("ramping constraints")
            except:
                print("###################################################################### ramping constraints commit error")  
        
def refinery_constraints(config):

    if config["include_refinery_trajectory"]:
        print("you are modeling imposed refinery trajectory")
        with DatabaseMapping(url_spineopt) as sopt_db:
            list_otb = [entity_i["name"] for entity_i in sopt_db.get_entity_items(entity_class_name = "temporal_block") if "operations" in entity_i["name"]]    
            entities = {type_:[entity_i["name"] for entity_i in sopt_db.get_entity_items(entity_class_name = "unit") if any(tech in entity_i["name"] for tech in config["refineries"][type_]["techs"])] for type_ in config["refineries"]}
            all_rps  = sopt_db.get_entity_item(entity_class_name = "temporal_block",name = "all_rps")
            for type_ in ["bio","syn"]:
                add_entity(sopt_db,"investment_group",(f"{type_}fuels",))
                
                coefficient_2030 = config["refineries"][type_]["share_2030"]
                coefficient_2040 = config["refineries"][type_]["share_2040"]
                coefficient_2050 = config["refineries"][type_]["share_2050"]
                refinery_cap = 0
                for tech in entities["fossil"]:
                    initial_cap = sopt_db.get_parameter_value_item(entity_class_name = "unit", alternative_name = "Base", parameter_definition_name = "investment_count_initial_cumulative", entity_byname = (tech,))
                    if initial_cap:
                        refinery_cap += initial_cap["parsed_value"]
                for tech in entities[type_]:
                    add_entity(sopt_db,"unit__investment_group",(tech,f"{type_}fuels"))

                index_ = ["2030-01-01T00:00:00","2040-01-01T00:00:00","2050-01-01T00:00:00","2060-01-01T00:00:00"]
                value_ = [coefficient_2030*refinery_cap,coefficient_2040*refinery_cap,coefficient_2050*refinery_cap,coefficient_2050*refinery_cap]
                parameter_value = {"type":"time_series","data":dict(zip(index_,value_))}
                add_parameter_value(sopt_db,"investment_group","investment_count_total_max_cumulative","Base",(f"{type_}fuels",),parameter_value)

            for entity_HC in [entity_i["name"] for entity_i in sopt_db.get_entity_items(entity_class_name="node") if "HC_" in entity_i["name"] and len(entity_i["name"])==5]:
                add_entity(sopt_db,"node",(f"bunker-{entity_HC}",))
                add_parameter_value(sopt_db,"node","storage_active","Base",(f"bunker-{entity_HC}",),True)
                add_parameter_value(sopt_db,"node","storage_longterm_active","Base",(f"bunker-{entity_HC}",),True)
                for tb in list_otb:
                    add_entity(sopt_db,"node__temporal_block",(f"bunker-{entity_HC}",tb))
                    add_parameter_value(sopt_db,"node__temporal_block","cyclic_condition","Base",(f"bunker-{entity_HC}",tb),True)
                if all_rps:
                    add_entity(sopt_db,"node__temporal_block",(f"bunker-{entity_HC}","all_rps"))
                add_entity(sopt_db,"connection",(f"bunker-connection-{entity_HC}",))
                add_parameter_value(sopt_db,"connection","connection_type","Base",(f"bunker-connection-{entity_HC}",),"connection_type_lossless_bidirectional")
                add_entity(sopt_db,"connection__from_node",(f"bunker-connection-{entity_HC}",entity_HC))
                add_entity(sopt_db,"connection__to_node",(f"bunker-connection-{entity_HC}",f"bunker-{entity_HC}"))
                add_entity(sopt_db,"connection__node__node",(f"bunker-connection-{entity_HC}",f"bunker-{entity_HC}",entity_HC))
                add_parameter_value(sopt_db,"connection__node__node","fix_ratio_out_in_connection_flow","Base",(f"bunker-connection-{entity_HC}",f"bunker-{entity_HC}",entity_HC),1.0)

            try:
                sopt_db.commit_session("refinery constraints")
            except:
                print("###################################################################### refinery constraints commit error")  

def onshore_potentials(config_renewable):

    config = config_renewable["renewable_potentials"]
    if config["include_onshore_potential_limitations"]:
        print("WARNING: If you haven't reset the model, you are reducing the VRE potentials once again.")
        with DatabaseMapping(url_spineopt) as sopt_db:
            maximum_entities = [parameter_map  for parameter_map in sopt_db.get_parameter_value_items(parameter_definition_name = "investment_count_total_max_cumulative") if "wind-on" in parameter_map["entity_byname"][0] or "solar-PV" in parameter_map["entity_byname"][0]]

            # max_capacity_history is per COUNTRY. When a country is split into several
            # polygons (IC1: BEC1..BEC8, NLC1..NLC9) the national history is distributed
            # pro rata to each polygon's share of the national potential, so the country
            # total lands on max(onshore_potentials * potential, history). For one polygon
            # per country (share 1) this is identical to the original rule.
            # cap_never_raised: a polygon's cap is never set above its original potential.
            maximum_entities = [m for m in maximum_entities if "MT" not in m["entity_byname"][0] and m["alternative_name"] == "Base"]
            def _split(name):
                tech_type = "wind-on" if "wind-on" in name else "solar-PV"
                polygon = name.split("_")[1]
                return tech_type, polygon, polygon[:2]
            national = {}
            for max_entity in maximum_entities:
                tech_type, polygon, country = _split(max_entity["entity_byname"][0])
                national[(tech_type, country)] = national.get((tech_type, country), 0.0) + max_entity["parsed_value"]
            for max_entity in maximum_entities:
                tech_type, polygon, country = _split(max_entity["entity_byname"][0])
                value = max_entity["parsed_value"]
                share = value/national[(tech_type, country)] if national[(tech_type, country)] else 0.0
                history = config["max_capacity_history"][tech_type].get(polygon, config["max_capacity_history"][tech_type].get(country, 0.0))
                floor = history if polygon in config["max_capacity_history"][tech_type] else history*share
                parameter_value = max(value*config["onshore_potentials"], floor)
                if config.get("cap_never_raised", False):
                    parameter_value = min(value, parameter_value)
                add_or_update_parameter_value(sopt_db,"investment_group","investment_count_total_max_cumulative","Base",max_entity["entity_byname"],parameter_value)

            try:
                sopt_db.commit_session("vre onshore potentials update")
            except:
                print("###################################################################### vre onshore potentials update commit error")  

def biomass_limitations(config):
    # Biomass-stock caps are annual volumes debited from a long-term storage once per
    # representative block, so they are divided by representative_period_scaling as well
    # (docs/FINDING_biomass_cap.md). The two factors are applied together, once.
    factor = (config["biomass_potential_realistic"] if config["include_biomass_potential_limitations"] else 1.0)/_rp_scaling(config)
    if factor != 1.0:
        print("WARNING: If you haven't reset the model, you are reducing the biomass potentials once again.")
        with DatabaseMapping(url_spineopt) as sopt_db:
            for parameter_name in ["storage_investment_count_max_cumulative","storage_state_fix","storage_investment_count_fix_cumulative","storage_investment_count_initial_cumulative"]:
                for parameter_map in sopt_db.get_parameter_value_items(parameter_definition_name = parameter_name):
                    if "biomass-stock" in parameter_map["entity_byname"][0]:
                        if parameter_map["type"] == "float":
                            parameter_value = factor*parameter_map["parsed_value"]
                        elif parameter_map["type"] == "time_series":
                            values_ = factor*parameter_map["parsed_value"].values
                            indexes_ = [pd.Timestamp(i).isoformat() for i in parameter_map["parsed_value"].indexes]
                            parameter_value = {"type":"time_series","data":dict(zip(indexes_,values_))}
                        add_or_update_parameter_value(sopt_db,parameter_map["entity_class_name"],parameter_name,parameter_map["alternative_name"],parameter_map["entity_byname"],parameter_value)
            try:
                sopt_db.commit_session("vre biomass potentials update")
            except:
                print("###################################################################### vre biomass potentials update commit error")  

def investment_cost_update(config):
    
    default_technology_discount_rate = config["default_technology_discount_rate"]
    future_inflation = config["future_inflation"]
    reference_year = int(config["economic_reference_year"])
    with DatabaseMapping(url_spineopt) as sopt_db:

        dates = []
        for date_dict in sopt_db.get_parameter_value_items(parameter_definition_name = "block_start"):
            if "operations" in date_dict["entity_byname"][0]:
                dates.append(pd.Timestamp(date_dict["parsed_value"].value).isoformat())
        final_date = [pd.Timestamp(i["parsed_value"].value) for i in sopt_db.get_parameter_value_items(parameter_definition_name = "model_end", alternative_name = "Base")][0]
        dates.append(final_date.isoformat())
        final_year = final_date.year

        entities = ["unit","connection","node"]
        icost    = ["unit_investment_cost","connection_investment_cost","storage_investment_cost"]
        fcost    = ["fom_cost","fixed_annual_cost","storage_fixed_annual_cost"]
        ilife    = ["lifetime_economic","lifetime_economic","storage_lifetime_economic"]
        tlife    = ["lifetime_technical","lifetime_technical","storage_lifetime_technical"]
        isense   = ["lifetime_constraint_sense","lifetime_constraint_sense","storage_lifetime_constraint_sense"]
        irate    = ["discount_rate_technology_specific","discount_rate_technology_specific","storage_discount_rate_technology_specific"]
        
        for index, entity_class_name in enumerate(entities): 

            for parameter_map in sopt_db.get_parameter_value_items(entity_class_name = entities[index], parameter_definition_name = icost[index]):
                
                lifetime_dict = sopt_db.get_parameter_value_item(entity_class_name = entities[index], parameter_definition_name = ilife[index], alternative_name = parameter_map["alternative_name"], entity_byname = parameter_map["entity_byname"])
                if not lifetime_dict:
                    print("Annuities are implemented using economic lifetime. Economic lifetime not found.")
                    continue
                else:
                    lifetime = int(json.loads(lifetime_dict["value"])["data"][:-1])
                    techlife_dict = sopt_db.get_parameter_value_item(entity_class_name = entities[index], parameter_definition_name = tlife[index], alternative_name = parameter_map["alternative_name"], entity_byname = parameter_map["entity_byname"])
                    add_or_update_parameter_value(sopt_db,entity_class_name,isense[index],"Base",techlife_dict["entity_byname"],"<=")
                
                rate_dict = sopt_db.get_parameter_value_item(entity_class_name = entities[index], parameter_definition_name = irate[index], alternative_name = parameter_map["alternative_name"], entity_byname = parameter_map["entity_byname"])
                if not rate_dict:
                    rate_list = sopt_db.get_parameter_value_items(parameter_definition_name = "discount_rate")
                    if not rate_list:
                        print("Model discount rate not found. Using 0.05 as default")
                        rate = default_technology_discount_rate
                    else:
                        rate = rate_list[0]["parsed_value"]
                else:
                    rate = rate_dict["parsed_value"]

                # fom cost
                fom_dict = sopt_db.get_parameter_value_item(entity_class_name = entities[index], parameter_definition_name = fcost[index], alternative_name = parameter_map["alternative_name"], entity_byname = parameter_map["entity_byname"])
                fom_cost_condition = False if not fom_dict else True
                value_dict = {}
                crf = rate * (1 + rate)**lifetime / ((1 + rate)**lifetime - 1)

                if parameter_map["type"] == "time_series": 
                    df = pd.DataFrame(parameter_map["parsed_value"].values,index=parameter_map["parsed_value"].indexes,columns=["value"])
                    data = df.copy()["value"]
                    data.index = [pd.Timestamp(i).isoformat() for i in data.index]

                if fom_cost_condition:
                    if fom_dict["type"] == "time_series":
                        df = pd.DataFrame(fom_dict["parsed_value"].values,index=fom_dict["parsed_value"].indexes,columns=["value"])
                        data_fom = df.copy()["value"]
                        data_fom.index = [pd.Timestamp(i).isoformat() for i in data.index]

                for date in dates:
                    if date != dates[-1]:
                        year = pd.Timestamp(date).year
                        n_years = min(lifetime, final_year - year)
                        annual_cost_nominal = (parameter_map["parsed_value"] if parameter_map["type"] == "float" else (data[date if date in data.index else dates[dates.index(date)-1]])) * (1 + future_inflation)**(year - reference_year) * crf 
                        fom_cost_term = (0 if not fom_cost_condition else (fom_dict["parsed_value"] if fom_dict["type"] == "float" else (data_fom[date if date in data_fom.index else dates[dates.index(date)-1]])))*(8760.0 if entities[index] == "unit" else 1.0)*n_years
                        value_dict[date] = sum(annual_cost_nominal * (1 + future_inflation)**(reference_year - i) for i in range(year, year + n_years)) + fom_cost_term
                    else:
                        value_dict[dates[-1]] = value_dict[dates[-2]]
                
                new_value   = {"type":"time_series","data":value_dict}
                add_or_update_parameter_value(sopt_db, parameter_map["entity_class_name"], parameter_map["parameter_definition_name"], parameter_map["alternative_name"], parameter_map["entity_byname"], new_value)
                if not fom_cost_condition:
                    print("FOM cost not found for ", parameter_map["entity_name"])
                else:
                    add_or_update_parameter_value(sopt_db, parameter_map["entity_class_name"], fcost[index], fom_dict["alternative_name"], fom_dict["entity_byname"], (fom_dict["parsed_value"].values[-1] if fom_dict["type"]=="time_series" else fom_dict["parsed_value"]))

        try:
            sopt_db.commit_session("Update Investment Costs")
        except:
            print("###################################################################### commit error investment costs")  

def air_ground_heatpump(config):

    with DatabaseMapping(url_spineopt) as sopt_db:
        
        for entity_name in [element["name"] for element in sopt_db.get_entity_items(entity_class_name = "unit") if "ground-heatpump_" in element["name"]]:
            polygon_name = entity_name.split("_")[1]
            add_entity(sopt_db,"user_constraint",("heatpump-ratio"+"_"+polygon_name,))
            add_entity(sopt_db,"unit__user_constraint",(entity_name,"heatpump-ratio"+"_"+polygon_name))
            add_parameter_value(sopt_db,"unit__user_constraint","coefficient_for_units_invested","Base",(entity_name,"heatpump-ratio"+"_"+polygon_name),1.0)
            add_parameter_value(sopt_db,"unit__user_constraint","coefficient_for_units_invested_available","Base",(entity_name,"heatpump-ratio"+"_"+polygon_name),0.0)
            add_entity(sopt_db,"unit__user_constraint",("air-heatpump"+"_"+polygon_name,"heatpump-ratio"+"_"+polygon_name))
            add_parameter_value(sopt_db,"unit__user_constraint","coefficient_for_units_invested","Base",("air-heatpump"+"_"+polygon_name,"heatpump-ratio"+"_"+polygon_name),-config["ratio_ground_air_HP"])
            add_parameter_value(sopt_db,"unit__user_constraint","coefficient_for_units_invested_available","Base",("air-heatpump"+"_"+polygon_name,"heatpump-ratio"+"_"+polygon_name),0.0)
        try:
            sopt_db.commit_session("Add User Constraint Heat Pumps")
        except:
            print("######################## commit error heat pump ratio")  

def manage_output():
    with DatabaseMapping(url_spineopt) as sopt_db:

        report_name = "default_report"
        add_entity(sopt_db,"report",(report_name,))
        add_entity(sopt_db,"model__report",("capacity_planning",report_name))
        outputs = ["capacity_per_unit","capacity_per_connection","storage_state_max","demand",
                   "connections_invested","connections_invested_available","connections_decommissioned","units_invested","units_invested_available","units_mothballed",
                   "storages_invested","storages_invested_available","storages_decommissioned","unit_flow","connection_flow","node_state","node_state_longterm","node_injection",
                   #"unit_investment_cost","connection_investment_cost","storage_investment_cost",
                   "unit_investment_costs","connection_investment_costs","storage_investment_costs","fixed_om_costs","variable_om_costs","fuel_costs","connection_flow_costs","taxes","objective_penalties",
                   "total_costs"]
                   #"node_slack_neg","node_slack_pos",
                   #"constraint_nodal_balance","constraint_units_available",
                   #"bound_units_on"]
        
        for output in outputs:
            add_entity(sopt_db,"output",(output,))
            add_entity(sopt_db,"report__output",(report_name,output))
        try:
            sopt_db.commit_session("Added outputs")
        except:
            print("############################## error commit adding output")

def solver_options(config):

    # NOTE: these options are only applied when SpineOpt builds the solver itself,
    # i.e. when `run_spineopt` is called WITHOUT mip_solver/lp_solver. Our plugin
    # wrapper (tools/spineopt-plugin/run_spineopt.jl) does pass a solver, and
    # SpineOpt then returns it untouched:
    #     _solver(f::Function, given_solver) = given_solver
    #     "If given solver is not `nothing`, just return it."
    # so everything below is INERT for IC1 runs made through that wrapper.
    # Keep the two in sync anyway: if the wrapper is ever reverted to the stock
    # plugin file, these values take over silently.
    #
    # time_limit: kept equal to SOLVER_TIME_LIMIT in the wrapper (4 h). The EU
    # baseline of 3600.01 s was not enough for IC1 to converge.
    # The HiGHS numerical options mirror the wrapper and stand in for Gurobi's
    # NumericFocus=2, which has no HiGHS equivalent.
    with DatabaseMapping(url_spineopt) as sopt_db:
        map_options = {"type":"map","index_type":"str","index_name":"x","data":
                       {"HiGHS.jl" :{"type":"map","index_type":"str","index_name":"x","data":{
                            "presolve":"on",
                            "time_limit":14400.0,                            "simplex_scale_strategy":4.0,
                            "primal_feasibility_tolerance":1e-9,
                            "dual_feasibility_tolerance":1e-9,
                            "ipm_optimality_tolerance":1e-9,
                            "mip_feasibility_tolerance":1e-7,
                            "mip_rel_gap":1e-3}},
                        "Gurobi.jl":{"type":"map","index_type":"str","index_name":"x","data":{"Method":2.0,"NumericFocus":2.0,"Crossover":0.0}}}}
        
        add_parameter_value(sopt_db,"model","solver_mip_options","Base",("capacity_planning",),map_options)
        add_parameter_value(sopt_db,"model","solver_mip","Base",("capacity_planning",),config["solver"])
        try:
            sopt_db.commit_session("Added solver_options")
        except:
            print("############################## error committing solver options")

def update_economic_parameters(config):

    with DatabaseMapping(url_spineopt) as sopt_db:

        economic_lifetime = {"unit":"lifetime_economic","connection":"lifetime_economic","node":"storage_lifetime_economic"}
        discount_rate = {"unit":"discount_rate_technology_specific","connection":"discount_rate_technology_specific","node":"storage_discount_rate_technology_specific"}
        
        for entity_class in config["economic_parameters"]:
            for entity_item in sopt_db.get_entity_items(entity_class_name = entity_class):
                if entity_item["name"].split("_")[0] in config["economic_parameters"][entity_class]:
                    if "WACC" in config["economic_parameters"][entity_class][entity_item["name"].split("_")[0]]:
                        add_or_update_parameter_value(sopt_db,entity_class,discount_rate[entity_class],"Base",entity_item["entity_byname"],config["economic_parameters"][entity_class][entity_item["name"].split("_")[0]]["WACC"])
                    if "economic_lifetime" in config["economic_parameters"][entity_class][entity_item["name"].split("_")[0]]:
                        add_or_update_parameter_value(sopt_db,entity_class,economic_lifetime[entity_class],"Base",entity_item["entity_byname"],{"type":"duration","data":config["economic_parameters"][entity_class][entity_item["name"].split("_")[0]]["economic_lifetime"]})
                    
        try:
            sopt_db.commit_session("Added economic parameters")
        except:
            print("############################## error committing economic parameters")

def limit_buildout(config):

    if config["set_technology_buildout"]:
        with DatabaseMapping(url_spineopt) as sopt_db:
            entities = {tech:[entity_i["name"] for entity_i in sopt_db.get_entity_items(entity_class_name = "unit") if tech in entity_i["name"]] for tech in config["technology_buildout"]}
            for entity in entities:
                add_entity(sopt_db,"investment_group",(entity,))
                try:
                    add_alternative(sopt_db,"limited_"+entity)
                except:
                    pass
                indexes = [str(i)+"-01-01T00:00:00" for i in list(config["technology_buildout"][entity].keys())]
                values = list(config["technology_buildout"][entity].values())
                indexes.append("2060-01-01T00:00:00")
                values.append(values[-1])
                parameter_value = {"type":"time_series","data":dict(zip(indexes,values))}
                add_parameter_value(sopt_db,"investment_group","investment_count_total_max_cumulative","limited_"+entity,(entity,),parameter_value)
                for tech in entities[entity]:
                    add_entity(sopt_db,"unit__investment_group",(tech,entity))
            # Per-country NEW-BUILD caps, alternative Base. Units <tech>_<CC> or <tech>_<CC>C<n>
            # are grouped in investment_group <tech>_<CC>; existing units (<tech>-existing_*) are excluded.
            for tech, countries in (config.get("technology_buildout_by_country") or {}).items():
                for country, caps in countries.items():
                    country = "NO" if country is False else str(country)  # YAML 1.1 reads NO as false
                    units = [e["name"] for e in sopt_db.get_entity_items(entity_class_name = "unit")
                             if re.match(r"^" + re.escape(tech) + "_" + country + r"(C\d+)?$", e["name"])]
                    if not units:
                        print(f"technology_buildout_by_country: no {tech} units in {country}, skipped")
                        continue
                    group = f"{tech}_{country}"
                    add_entity(sopt_db,"investment_group",(group,))
                    for unit in units:
                        add_entity(sopt_db,"unit__investment_group",(unit,group))
                    indexes = [str(i)+"-01-01T00:00:00" for i in caps] + ["2060-01-01T00:00:00"]
                    values = [float(v) for v in caps.values()] + [float(list(caps.values())[-1])]
                    add_parameter_value(sopt_db,"investment_group","investment_count_total_max_cumulative","Base",(group,),{"type":"time_series","data":dict(zip(indexes,values))})
            try:
                sopt_db.commit_session("Added technology buildout")
            except:
                print("############################## error technology buildout parameters")

def demand_flex(config):

    if config["set_industry_buildings_flex"]:
        industry = ["cement","chemical-chlorine","chemical-olefins","chemical-PE","chemical-PEA","fertiliser-ammonia-NH3","glass-container","glass-fibre","glass-float","steel-primary","steel-seconday","alumina","aluminium-primary","aluminium-secondary","electric-arc-steel","food-beverages-tobacco","leather-and-textile","machinery-equipment","other-non-ferrous-metals","paper","pharmaceuticals","printing-and-media","pulp","pulp","transport-equipment","wood-and-wood-products"]
        heat = ["nonres-cool","nonres-DHW","nonres-space","res-cool","res-DHW","res-space"]
        comfort_buildings = config["industry_buildings_flex"]["comfort_buildings"]
        comfort_industry = config["industry_buildings_flex"]["comfort_industry"]
        flex_buildings = config["industry_buildings_flex"]["flex_buildings"]
        flex_industry = config["industry_buildings_flex"]["flex_industry"]

        with DatabaseMapping(url_spineopt) as sopt_db:
            list_rep = [entity_i["name"] for entity_i in sopt_db.get_entity_items(entity_class_name = "temporal_block") if "representative_period" in entity_i["name"]]
            list_otb = [entity_i["name"] for entity_i in sopt_db.get_entity_items(entity_class_name = "temporal_block") if "operations" in entity_i["name"]]                    
            demands = sopt_db.get_parameter_value_items(entity_class_name = "node", parameter_definition_name = "demand")
            for demand in demands:
                node = demand["entity_name"]
                if any(i in node for i in heat):
                    peak_demand = demand["parsed_value"].values.max()
                    target_node = [j for j in heat if j in node][0]+"_"+node.split("_")[1].split("-")[0]
                    try:
                        add_alternative(sopt_db,"flex_buildings")
                    except:
                        pass
                    try:
                        add_parameter_value(sopt_db,"node","storage_active","flex_buildings",(target_node,),True)
                    except:
                        pass
                    if list_rep:
                        for rep in list_rep:
                            try:
                                add_entity(sopt_db,"node__temporal_block",(target_node,rep))
                                add_entity_alternative(sopt_db,"node__temporal_block",(target_node,rep),"flex_buildings")
                                add_entity_alternative(sopt_db,"node__temporal_block", (target_node,rep), "flex_buildings", True)
                                add_entity_alternative(sopt_db,"node__temporal_block", (target_node,rep), "Base", False)
                            except:
                                pass
                            add_or_update_parameter_value(sopt_db,"node__temporal_block","cyclic_condition","flex_buildings",(target_node,rep),True)
                    else:
                        add_or_update_parameter_value(sopt_db,"node","storage_longterm_active","flex_buildings",(target_node,),True)
                        for tb in list_otb:
                            try:
                                add_entity(sopt_db,"node__temporal_block",(target_node,tb))
                                add_entity_alternative(sopt_db,"node__temporal_block", (target_node,tb), "flex_buildings", True)
                                add_entity_alternative(sopt_db,"node__temporal_block", (target_node,tb), "Base", False)
                            except:
                                pass
                            add_or_update_parameter_value(sopt_db,"node__temporal_block","cyclic_condition","flex_buildings",(target_node,tb),True)
                    for frac_demand in sopt_db.get_parameter_value_items(entity_class_name = "node", parameter_definition_name = "demand_fraction", entity_byname = (target_node,)):
                        values = [i*peak_demand*flex_buildings*comfort_buildings  for i in frac_demand["parsed_value"].values]
                        indexes = [pd.Timestamp(i).isoformat() for i in frac_demand["parsed_value"].indexes]
                        parameter_value = {"type":"time_series","data":dict(zip(indexes,values))}
                        try:
                            add_alternative(sopt_db,"flex_buildings_"+demand["alternative_name"]+"_"+frac_demand["alternative_name"])
                        except:
                            pass
                        add_parameter_value(sopt_db,"node","storage_state_max","flex_buildings_"+demand["alternative_name"]+"_"+frac_demand["alternative_name"],(target_node,),parameter_value)

                if any(i in node for i in industry):
                    peak_demand = demand["parsed_value"]
                    target_node = [j for j in industry if j+"_" in node][0]+"_"+node.split("_")[1]
                    try:
                        add_alternative(sopt_db,"flex_industry")
                    except:
                        pass
                    try:
                        add_parameter_value(sopt_db,"node","storage_active","flex_industry",(target_node,),True)
                    except:
                        pass
                    if list_rep:
                        for rep in list_rep:
                            try:
                                add_entity(sopt_db,"node__temporal_block",(target_node,rep))
                                add_entity_alternative(sopt_db,"node__temporal_block",(target_node,rep),"flex_industry")
                                add_entity_alternative(sopt_db,"node__temporal_block", (target_node,rep), "flex_industry", True)
                                add_entity_alternative(sopt_db,"node__temporal_block", (target_node,rep), "Base", False)
                            except:
                                pass
                            add_or_update_parameter_value(sopt_db,"node__temporal_block","cyclic_condition","flex_industry",(target_node,rep),True)
                    else:
                        add_or_update_parameter_value(sopt_db,"node","storage_longterm_active","flex_industry",(target_node,),True)
                        for tb in list_otb:
                            try:
                                add_entity(sopt_db,"node__temporal_block",(target_node,tb))
                                add_entity_alternative(sopt_db,"node__temporal_block", (target_node,tb), "flex_industry", True)
                                add_entity_alternative(sopt_db,"node__temporal_block", (target_node,tb), "Base", False)
                            except:
                                pass
                            add_or_update_parameter_value(sopt_db,"node__temporal_block","cyclic_condition","flex_industry",(target_node,tb),True)
                    parameter_value = peak_demand*flex_industry*comfort_industry
                    add_parameter_value(sopt_db,"node","storage_state_max","flex_industry",(target_node,),parameter_value)
            try:
                sopt_db.commit_session("Added demand_flexibility")
            except:
                print("############################## error demand_flexibility parameters")

def limit_commodity(config):

    if config["set_limited_commodity"]:
        with DatabaseMapping(url_spineopt) as sopt_db:
            for commodity in config["limited_commodity"]:
                indexes = [str(i)+"-01-01T00:00:00" for i in list(config["limited_commodity"][commodity].keys())]
                values = list(config["limited_commodity"][commodity].values())
                indexes.append("2060-01-01T00:00:00")
                values.append(values[-1])
                parameter_value = {"type":"time_series","data":dict(zip(indexes,values))}
                try:
                    add_alternative(sopt_db,"limited_"+commodity)
                except:
                    pass
                add_parameter_value(sopt_db,"node","storage_state_max","limited_"+commodity,(commodity,),parameter_value)
                add_parameter_value(sopt_db,"node","balance_type","limited_"+commodity,(commodity,),"node_balance")
                add_parameter_value(sopt_db,"node","storage_active","limited_"+commodity,(commodity,),True)
                add_parameter_value(sopt_db,"node","storage_longterm_active","limited_"+commodity,(commodity,),True)
            try:
                sopt_db.commit_session("Added limited commodity")
            except:
                print("############################## error limited commodity parameters")

def set_parameters(config):
    """Explicit parameter overrides from scenario_config.yml (`set_parameters`). Each entry:
    {class, entity (regex on the entity name), parameter, value, alternative (default Base)}.
    Used for case decisions that are not data, e.g. closed gas fields or excluded DAC."""
    entries = config.get("set_parameters") or []
    if not entries:
        return
    with DatabaseMapping(url_spineopt) as sopt_db:
        for entry in entries:
            names = [e["name"] for e in sopt_db.get_entity_items(entity_class_name = entry["class"]) if re.match(entry["entity"], e["name"])]
            print(f"  set {entry['parameter']} = {entry['value']} on {len(names)} {entry['class']} ({entry['entity']})")
            for name in names:
                add_or_update_parameter_value(sopt_db, entry["class"], entry["parameter"], entry.get("alternative","Base"), (name,), entry["value"])
        try:
            sopt_db.commit_session("set_parameters overrides")
        except:
            print("###################################################################### set_parameters commit error")

def _values(item):
    if item is None:
        return []
    if item["type"] == "float":
        return [float(item["parsed_value"])]
    if item["type"] == "time_series":
        return [float(v) for v in item["parsed_value"].values]
    return []

def retire_industry(config):
    """Force retirement of endowed industrial incumbents where this is feasible
    (docs/STANDARD_model_patches.md #4). A unit with existing capacity X feeding a
    sector node gets investment_count_max_cumulative = {2030: X, 2041: X/2, 2050: 0, 2060: 0}
    only if, in its own region, at least one other unit feeds the same node and the others'
    final capacity covers the node demand (the screen that excludes e.g. Scraps_EAF_BEC3/5).
    Carrier nodes and units whose max is not a scalar are left alone."""
    settings = config.get("retire_industry") or {}
    if not settings.get("active", False):
        return
    carrier = re.compile(settings["carrier_regex"])
    region = re.compile(settings["region_regex"])
    with DatabaseMapping(url_spineopt) as sopt_db:
        def by_name(param, cls):
            return {p["entity_byname"]: p for p in sopt_db.get_parameter_value_items(entity_class_name = cls, parameter_definition_name = param)}
        init = by_name("investment_count_initial_cumulative", "unit")
        mx = by_name("investment_count_max_cumulative", "unit")
        dem = by_name("demand", "node")
        capu = {k: (_values(v) or [1.0])[0] for k, v in by_name("capacity_per_unit", "unit__to_node").items()}
        feeders = {}
        for e in sopt_db.get_entity_items(entity_class_name = "unit__to_node"):
            unit, node = e["element_name_list"]
            feeders.setdefault(node, []).append(unit)
        targets = []
        for node in sorted(feeders):
            if carrier.match(region.sub("", node)) or node.endswith("-group"):
                continue
            units = feeders[node]
            demand = (_values(dem.get((node,))) or [0.0])[0]
            for unit in units:
                endowment = (_values(init.get((unit,))) or [0.0])[0]
                if endowment <= 1e-9:
                    continue
                others = [u for u in units if u != unit]
                alt_capacity = sum(((_values(mx.get((u,))) or [0.0])[-1])*capu.get((u, node), 1.0) for u in others)
                already = ((_values(mx.get((unit,))) or [0.0])[-1]) <= 1e-12
                if others and alt_capacity >= demand - 1e-12 and not already:
                    targets.append((unit, endowment))
        changed = 0
        for unit, endowment in targets:
            item = mx.get((unit,))
            if item is None:
                raise RuntimeError(f"retire_industry: no investment_count_max_cumulative for {unit}")
            if item["type"] != "float":
                continue
            value = {"type":"time_series","data":{"2030-01-01T00:00:00": endowment, "2041-01-01T00:00:00": endowment/2.0,
                                                  "2050-01-01T00:00:00": 0.0, "2060-01-01T00:00:00": 0.0}}
            add_or_update_parameter_value(sopt_db, "unit", "investment_count_max_cumulative", item["alternative_name"], (unit,), value)
            changed += 1
        print(f"  retire_industry: {len(targets)} retire-safe incumbents, {changed} patched")
        try:
            sopt_db.commit_session("retire industrial incumbents")
        except:
            print("###################################################################### retire industry commit error")

def collapse_representative_maps(config):
    """Companion of operations_resolution (one operational timestep per year).
    With 1h operations blocks, node_state_longterm applies its per-period delta ~8760 times
    per milestone, shrinking every *_cumulative budget by that factor. With one timestep per
    year, representative_blocks_by_period must have ONE entry per block: the per-period rows
    (each summing to 1) are averaged over the year and renormalised to sum exactly 1
    (SpineOpt rejects any other sum). Replaces the former tools/make_tiny_model.py."""
    if not config.get("operations_resolution"):
        return
    n = 0
    with DatabaseMapping(url_spineopt) as sopt_db:
        for pv in list(sopt_db.get_parameter_value_items(entity_class_name="temporal_block", parameter_definition_name="representative_blocks_by_period")):
            m = api.from_database(pv["value"], pv["type"])
            idx = list(m.indexes)
            if len(idx) <= 1:
                continue
            rows = [list(r.values) for r in m.values]
            for r in rows:
                if abs(sum(r) - 1.0) > 1e-9:
                    raise ValueError(f"{pv['entity_byname'][0]}: a row sums to {sum(r)!r}, expected 1.0")
            shares = [sum(r[i] for r in rows) / len(rows) for i in range(len(rows[0]))]
            s = sum(shares)
            shares = [x / s for x in shares]
            new_map = {"type": "map", "index_type": "date_time", "index_name": "t",
                       "data": [(str(idx[0]), {"type": "array", "value_type": "float", "data": shares})]}
            val, typ = api.to_database(new_map)
            sopt_db.update_item("parameter_value", id=pv["id"], value=val, type=typ)
            n += 1
        print(f"  collapse_representative_maps: {n} maps collapsed to one entry")
        try:
            sopt_db.commit_session("collapse representative_blocks_by_period for coarse operations")
        except:
            print("###################################################################### collapse maps commit error")

def align_milestones_to_periods(config):
    """Source data stamp the middle milestone 2041 while the investment period starts
    2040-01-01, so SpineOpt reads the 2030/2041 average for 2040 investments
    (docs/FINDING_2040_midpoint_and_no_scenario_filter.md). Insert a 2040-01-01 point equal to
    the 2041 value in every yearly milestone series (2030, 2041, 2050[, 2060]).
    Operational 2040 blocks (calendar 2041) are unaffected; temporal_block maps are skipped."""
    if not config.get("align_milestones_to_periods", False):
        return
    patterns = {("2030-01-01","2041-01-01","2050-01-01","2060-01-01"), ("2030-01-01","2041-01-01","2050-01-01")}
    n = 0
    with DatabaseMapping(url_spineopt) as sopt_db:
        for v in sopt_db.get_parameter_value_items():
            if v["type"] not in ("time_series", "map") or v["entity_class_name"] == "temporal_block":
                continue
            x = api.from_database(v["value"], v["type"])
            idx = [str(i)[:10] for i in x.indexes]
            if "2040-01-01" in idx or tuple(idx) not in patterns:
                continue
            k = idx.index("2041-01-01"); vals = list(x.values)
            if not all(isinstance(y, (int, float, np.floating)) for y in vals):
                continue
            if isinstance(x, api.TimeSeriesVariableResolution):
                ni = list(x.indexes); ni.insert(k, np.datetime64("2040-01-01T00:00:00")); vals.insert(k, vals[k])
                nx = api.TimeSeriesVariableResolution(np.array(ni, dtype="datetime64[s]"), np.array(vals, dtype=float), x.ignore_year, x.repeat, index_name=x.index_name)
            else:
                ni = list(x.indexes); ni.insert(k, type(ni[k])("2040-01-01T00:00:00")); vals.insert(k, vals[k])
                nx = api.Map(ni, vals, index_name=x.index_name)
            val, typ = api.to_database(nx)
            sopt_db.update_item("parameter_value", id=v["id"], value=val, type=typ)
            n += 1
        print(f"  align_milestones_to_periods: {n} series given a 2040-01-01 point")
        try:
            sopt_db.commit_session("align 2041 milestones to the 2040 period")
        except:
            print("###################################################################### align milestones commit error")

def main():

    with open(sys.argv[2], 'r') as file:
        config = yaml.safe_load(file)

    print("Updating economic parameters, econ lifetime and discount rate")
    update_economic_parameters(config)
    
    print("Updating invesment costs and FOM costs")
    investment_cost_update(config)

    print("Heat pump constraints")
    air_ground_heatpump(config)

    print("Limitations on technology buildout")
    limit_buildout(config)

    print("storage_setup")
    storage_setup(config)
    
    print("Limitations on commodity usage")
    limit_commodity(config)

    print("Demand flexibility")
    demand_flex(config)

    print("managing outputs")
    manage_output()

    print("adding solver options")
    solver_options(config)

    print("adding scenarios to be analyzed")
    scenario_development(config)

    print("updating_parameters")
    update_parameters(config)

    print("fixing invested variables")
    fix_no_investable_by_2030(config)

    print("ramping constraints")
    ramping_constraints(config)

    print("refinery constraints")
    refinery_constraints(config)

    print("vre onshore potentials updates")
    onshore_potentials(config)

    print("biomass potentials updates")
    biomass_limitations(config)
    print("industry retirement")
    retire_industry(config)
    print("parameter overrides")
    set_parameters(config)
    print("representative maps for coarse operations")
    collapse_representative_maps(config)
    print("milestone alignment (must run last)")
    align_milestones_to_periods(config)

if __name__ == "__main__":
    main()