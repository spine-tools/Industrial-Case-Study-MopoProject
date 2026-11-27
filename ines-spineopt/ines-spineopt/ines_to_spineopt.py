import spinedb_api as api
from spinedb_api import DatabaseMapping, DateTime, Map, to_database
from spinedb_api.parameter_value import convert_map_to_table, IndexedValue
from sqlalchemy.exc import DBAPIError
import yaml
import sys
from ines_tools import ines_transform
import pandas as pd
import json
import numpy as np

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

operations = {
    "multiply": lambda x, y: x * y,
    "add": lambda x, y: x + y,
    "subtract": lambda x, y: x - y,
    "divide": lambda x, y: x / y,
    "constant": lambda x, y: y
}

if len(sys.argv) > 1:
    url_db_in = sys.argv[1]
else:
    exit("Please provide input database url and output database url as arguments. They should be of the form ""sqlite:///path/db_file.sqlite""")
if len(sys.argv) > 2:
    url_db_out = sys.argv[2]
else:
    exit("Please provide input database url and output database url as arguments. They should be of the form ""sqlite:///path/db_file.sqlite""")

with open('ines_to_spineopt_entities.yaml', 'r') as file:
    entities_to_copy = yaml.load(file, yaml.BaseLoader)
with open('ines_to_spineopt_parameters.yaml', 'r') as file:
    parameter_transforms = yaml.load(file, yaml.BaseLoader)
with open('ines_to_spineopt_methods.yaml', 'r') as file:
    parameter_methods = yaml.safe_load(file)
with open('ines_to_spineopt_entities_to_parameters.yaml', 'r') as file:
    entities_to_parameters = yaml.load(file, yaml.BaseLoader)
with open('settings.yaml', 'r') as file:
    settings = yaml.safe_load(file)

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

def add_alternative(db_map : DatabaseMapping,name_alternative : str) -> None:
    _, error = db_map.add_alternative_item(name=name_alternative)
    if error is not None:
        raise RuntimeError(error)
    
def add_scenario(db_map : DatabaseMapping,name_scenario : str) -> None:
    _, error = db_map.add_scenario_item(name=name_scenario)
    if error is not None:
        raise RuntimeError(error)

def add_scenario_alternative(db_map : DatabaseMapping,name_scenario : str, name_alternative : str, rank_int = None) -> None:
    _, error = db_map.add_scenario_alternative_item(scenario_name = name_scenario, alternative_name = name_alternative, rank = rank_int)
    if error is not None:
        raise RuntimeError(error)

def parameter_features(param_elements,source_db,source_entity_class,source_entity_names,source_alternative):

    if isinstance(param_elements,list):
        target_param = param_elements[0]
        multiplier = float(param_elements[1])
        target_order = param_elements[2]
    elif isinstance(param_elements,dict):
        target_param = param_elements["target"][0]
        conver_factor = float(param_elements["target"][1])
        target_order = param_elements["target"][2]
        op = operations[param_elements["operation"]]
        try:
            with_value = float(param_elements["with"])
        except:
            print("operating with ",param_elements["with"])
            value_ = source_db.get_parameter_value_item(entity_class_name = source_entity_class, parameter_definition_name = param_elements["with"], entity_byname = source_entity_names, alternative_name = source_alternative)
            if value_:
                with_value = value_["parsed_value"]
            else:
                raise ValueError(f"{param_elements['with']} does not exist for {source_entity_class} {source_entity_names}")
        multiplier = conver_factor*op(float(param_elements["target"][1]),with_value)

    return target_param, target_order, multiplier

def main():
    with DatabaseMapping(url_db_in) as source_db:
        with DatabaseMapping(url_db_out) as target_db:
            ## Empty the database
            target_db.purge_items('parameter_value')
            target_db.purge_items('entity')
            target_db.purge_items('alternative')
            target_db.purge_items('scenario')
            target_db.refresh_session()
            target_db.commit_session("Purged stuff")

            ## Copy alternatives
            for alternative in source_db.get_alternative_items():
                target_db.add_alternative_item(name=alternative["name"])
            for scenario in source_db.get_scenario_items():
                target_db.add_scenario_item(name=scenario["name"])
            for scenario_alternative in source_db.get_scenario_alternative_items():
                target_db.add_scenario_alternative_item(alternative_name=scenario_alternative["alternative_name"],
                                                        scenario_name=scenario_alternative["scenario_name"],
                                                        rank=scenario_alternative["rank"])
            
            
            ## Copy entites
            target_db = ines_transform.copy_entities(source_db, target_db, entities_to_copy)
            ## Copy numeric parameters(source_db, target_db, copy_entities)
            target_db = ines_transform.transform_parameters(source_db, target_db, parameter_transforms)
            ## Copy methods(source_db, target_db, copy_entities)
            target_db = ines_transform.process_methods(source_db, target_db, parameter_methods)
            ## Copy entities to parameters
            # target_db = ines_transform.copy_entities_to_parameters(source_db, target_db, entities_to_parameters)

            # Manual functions
            # timeline configuration for spineopt model
            timeline_setup(source_db,target_db)

            ## historical and future time series
            map_of_periods_or_historical_to_ts(source_db,target_db,settings["map_of_periods_or_historical_to_ts"])

            ## flow profiles addition
            flow_profile_method(source_db,target_db)

            ## investments not allowed
            limiting_investments_notallowed(source_db,target_db)

            # Process emisssions balance equations
            process_emissions(source_db,target_db,settings.get("process_emissions") or {})

            # Fix boundary condition for storages
            storage_state_fix_method(source_db,target_db)
            storage_state_binding_method(source_db,target_db)

            # Set to group constraints
            set_to_entities_and_parameters(source_db,target_db)

            # Default parameters
            default_parameters(target_db,settings["default_parameters"])

            # existing capacity 
            existing_capacity(source_db,target_db)

            # lifetime to duration
            lifetime_to_duration(source_db,target_db,settings["lifetime_to_duration"])

            # unit flow transformation
            unit_flow_variants(source_db,target_db,settings)

            # Link common parameter to all direction parameters
            link_parameters_to_directions(source_db,target_db,settings["link_parameters_to_directions"])
        

def process_emissions(source_db, target_db, emission_settings = None):
    emission_settings = emission_settings or {}

    # unit flow coming from fossil nodes
    co2_params = source_db.get_parameter_value_items(entity_class_name="node",parameter_definition_name="co2_content",alternative_name="Base")
    co2_value  = {co2_param["entity_name"]:co2_param["parsed_value"] for co2_param in co2_params if co2_param["entity_name"] != "CO2"}

    # Process-route emission factors, written upstream by
    # industry_DB.py::add_tech_parameters() from ind_process_routes_co2_emission
    # and carried to the unit level by sysconfig.yaml (technology -> unit).
    #
    # These are NET of capture and are expressed per unit of the technology's
    # OUTPUT commodity, unlike co2_content which is per unit of INPUT fuel.
    # Where a route factor exists it REPLACES the fuel-based value entirely;
    # applying both would charge the unit twice.
    #
    # The fuel-based path remains the fallback for units with no route data
    # (power plants, boilers, terminals, gas extraction).
    #
    # See docs/VERIFICATION_co2_pipeline.md and docs/WHY_NOT_atmosphere_commodity.md.
    route_params = source_db.get_parameter_value_items(entity_class_name="unit",parameter_definition_name="co2_emission",alternative_name="Base")
    route_value = {p["entity_name"]: p["parsed_value"] for p in route_params}

    # The output node carrying the product. A unit may also emit to CO2_<region>
    # (the capture flow); the emission factor is keyed on the product output,
    # so CO2 and atmosphere targets are excluded here.
    product_node = {}
    for u2n in target_db.get_entity_items(entity_class_name="unit__to_node"):
        unit_name, to_node = u2n["entity_byname"]
        if unit_name not in route_value:
            continue
        if to_node == "atmosphere" or to_node == "CO2" or to_node.startswith("CO2_"):
            continue
        product_node.setdefault(unit_name, to_node)

    route_applied = 0

    for unit_entity in target_db.get_entity_items(entity_class_name="unit"):
        unit__from_nodes = [from_node for from_node in co2_value if target_db.get_entity_item(entity_class_name = "node__to_unit",entity_byname = (from_node,unit_entity["name"]))]       
        unit_name = unit_entity["name"]

        # Route-based emissions take precedence over the fuel-based fallback.
        if unit_name in route_value and unit_name in product_node:
            out_node = product_node[unit_name]
            add_entity(target_db,"unit__to_node",(unit_name,"atmosphere"))
            add_entity(target_db,"unit_flow__unit_flow",(unit_name,"atmosphere",unit_name,out_node))
            add_parameter_value(target_db,"unit_flow__unit_flow","flow_ratio_equality_coefficient","Base",(unit_name,"atmosphere",unit_name,out_node),route_value[unit_name])
            route_applied += 1
            continue

        if len(unit__from_nodes) > 1:
            add_entity(target_db,"unit__to_node",(unit_name,"atmosphere"))
            add_entity(target_db,"user_constraint",(unit_name+"_emissions",))
            add_entity(target_db,"unit_flow__user_constraint",(unit_name,"atmosphere",unit_name+"_emissions"))
            add_parameter_value(target_db,"unit_flow__user_constraint","coefficient_for_unit_flow","Base",(unit_name,"atmosphere",unit_name+"_emissions"),-1.0)
            for from_node in unit__from_nodes:
                add_entity(target_db,"unit_flow__user_constraint",(from_node,unit_name,unit_name+"_emissions"))
                add_parameter_value(target_db,"unit_flow__user_constraint","coefficient_for_unit_flow","Base",(from_node,unit_name,unit_name+"_emissions"),co2_value[from_node])
        elif len(unit__from_nodes) == 1:
            add_entity(target_db,"unit__to_node",(unit_name,"atmosphere"))
            add_entity(target_db,"unit_flow__unit_flow",(unit_name,"atmosphere",unit__from_nodes[0],unit_name))
            add_parameter_value(target_db,"unit_flow__unit_flow","flow_ratio_equality_coefficient","Base",(unit_name,"atmosphere",unit__from_nodes[0],unit_name),co2_value[unit__from_nodes[0]])

    # Explicit bookings for carriers whose co2_content cannot reach the model: the commodity
    # projection only attaches co2_content to GLOBAL nodes, while CH4/HC exist only as
    # regional nodes (docs/FINDING_co2_gateway_accounting.md). Configured in settings.yaml.
    #
    # output_bookings: units whose name starts with <unit_prefix> book <value> t/MWh on their
    #   <node_prefix>_* OUTPUT, e.g. methanation: synthetic CH4 is later burned without any
    #   booking, so its carbon must be booked where it is made (closes the CCU leak).
    # input_fallbacks: units that consume <node_prefix>_* and still have NO atmosphere flow
    #   book <value> t/MWh on that INPUT, e.g. HC burned in power/heat units.
    #   Units with route-based or fuel-based bookings are skipped, so nothing is booked twice.
    has_atmosphere = {e["entity_byname"][0] for e in target_db.get_entity_items(entity_class_name="unit__to_node") if e["entity_byname"][1] == "atmosphere"}
    extra = 0
    for unit_prefix, booking in (emission_settings.get("output_bookings") or {}).items():
        for u2n in target_db.get_entity_items(entity_class_name="unit__to_node"):
            unit_name, to_node = u2n["entity_byname"]
            if not unit_name.startswith(unit_prefix + "_") or not to_node.startswith(booking["node_prefix"] + "_"):
                continue
            if unit_name in has_atmosphere:
                print(f"WARNING process_emissions: {unit_name} already books CO2; output booking skipped")
                continue
            add_entity(target_db,"unit__to_node",(unit_name,"atmosphere"))
            add_entity(target_db,"unit_flow__unit_flow",(unit_name,"atmosphere",unit_name,to_node))
            add_parameter_value(target_db,"unit_flow__unit_flow","flow_ratio_equality_coefficient","Base",(unit_name,"atmosphere",unit_name,to_node),float(booking["value"]))
            has_atmosphere.add(unit_name); extra += 1
    for node_prefix, value in (emission_settings.get("input_fallbacks") or {}).items():
        for n2u in target_db.get_entity_items(entity_class_name="node__to_unit"):
            from_node, unit_name = n2u["entity_byname"]
            if not from_node.startswith(node_prefix + "_") or unit_name in has_atmosphere:
                continue
            add_entity(target_db,"unit__to_node",(unit_name,"atmosphere"))
            add_entity(target_db,"unit_flow__unit_flow",(unit_name,"atmosphere",from_node,unit_name))
            add_parameter_value(target_db,"unit_flow__unit_flow","flow_ratio_equality_coefficient","Base",(unit_name,"atmosphere",from_node,unit_name),float(value))
            has_atmosphere.add(unit_name); extra += 1
    print(f"process_emissions: {extra} explicit output/input bookings from settings")
    print(f"process_emissions: {route_applied} unit(s) got route-based emission factors "
          f"({len(route_value)} technologies carried co2_emission); "
          f"remaining units used the fuel-content fallback")

    try:
        target_db.commit_session("Added process capacities")
    except:
        print("commit process capacities error")

def map_of_periods_or_historical_to_ts(source_db,target_db,settings):
    
    starttime = {} 
    year_repr = {} 
    for period in json.loads(source_db.get_parameter_value_items(entity_class_name = "solve_pattern", parameter_definition_name = "period")[0]["value"])["data"]:
        starttime[period] = json.loads(source_db.get_parameter_value_item(entity_class_name = "period", entity_byname = (period,), alternative_name = "Base", parameter_definition_name = "start_time")["value"])["data"]
        year_repr[period] = source_db.get_parameter_value_item(entity_class_name = "period", entity_byname = (period,), alternative_name = "Base", parameter_definition_name = "years_represented")["parsed_value"]

    duration      = json.loads(source_db.get_parameter_value_items(entity_class_name = "solve_pattern", parameter_definition_name = "duration")[0]["value"])["data"]
    starttime_sp  = json.loads(source_db.get_parameter_value_items(entity_class_name = "solve_pattern", parameter_definition_name = "start_time")[0]["value"])["data"]
    resolution    = json.loads(source_db.get_parameter_value_items(entity_class_name = "solve_pattern", parameter_definition_name = "time_resolution")[0]["value"])["data"]
                             
    for source_entity_class in settings:
        for target_entity_class in settings[source_entity_class]:
            for source_param in settings[source_entity_class][target_entity_class]:
                print(source_entity_class,target_entity_class,source_param)
                param_elements = settings[source_entity_class][target_entity_class][source_param]

                for param_map in source_db.get_parameter_value_items(entity_class_name = source_entity_class, parameter_definition_name = source_param):

                    target_param, target_order, multiplier = parameter_features(param_elements,source_db,source_entity_class,param_map["entity_byname"],param_map["alternative_name"])

                    if param_map["type"] == "map":

                        map_table = convert_map_to_table(param_map["parsed_value"])
                        index_names = nested_index_names(param_map["parsed_value"])
                        data = pd.DataFrame(map_table, columns=index_names + ["value"]).set_index(index_names[0])
                        data.index = data.index.astype("string")

                        if any(i in data.index for i in starttime):
                            indexes_ = []
                            values_ = []
                            for period_, ts_index_ in starttime.items():
                                values_.append(multiplier*(float(data.at[period_,"value"]) if period_ in data.index else 0.0))
                                
                                # this should be removed once the fixed resolution is repaired
                                indexes_.append(ts_index_)
                            values_.append(values_[-1]) 
                            indexes_.append((pd.Timestamp(ts_index_).replace(year=int(pd.Timestamp(ts_index_).year+year_repr[period_]))).isoformat())

                            ts_to_export = {"type": "time_series","data": dict(zip(indexes_,values_))}
                            target_names = tuple(["__".join([param_map["entity_byname"][int(i)-1] for i in k]) for k in target_order])
                            add_parameter_value(target_db,target_entity_class,target_param,param_map["alternative_name"],target_names,ts_to_export)
                    
                        if any(i in data.index for i in starttime_sp):
                            for index, element in enumerate(starttime_sp):
                                try:
                                    alternative_name = f"wy{str(pd.Timestamp(element).year)}"
                                    add_alternative(target_db,alternative_name)
                                except:
                                    pass
                                steps = pd.to_timedelta(duration) / pd.to_timedelta(resolution)
                                df_data = (multiplier*data.iloc[data.index.tolist().index(element):data.index.tolist().index(element)+int(steps),data.columns.tolist().index("value")]).tolist()
                                ts_export = {"type": "time_series","data": df_data,"index": {"start": f"2018{element[4:]}","resolution": resolution,"ignore_year": True}}
                                target_names = tuple(["__".join([param_map["entity_byname"][int(i)-1] for i in k]) for k in target_order])
                                add_parameter_value(target_db,target_entity_class,target_param,alternative_name,target_names,ts_export)
                    
                
                    elif param_map["type"] == "float":
                        target_names = tuple(["__".join([param_map["entity_byname"][int(i)-1] for i in k]) for k in target_order])
                        add_parameter_value(target_db,target_entity_class,target_param,param_map["alternative_name"],target_names,multiplier*param_map["parsed_value"])
          
    try:
        target_db.commit_session("Added map of periods, historical data to timeseries")
    except:
        print("commit map of periods, historical data to timeseries error")

def timeline_setup(source_db,target_db):

    # model_data
    model_name = source_db.get_entity_items(entity_class_name = "solve_pattern")[0]["name"]
    # Process scenario realizations
    sto_structure = "deterministic"
    sto_scenario  = "realization"
    add_entity(target_db,"stochastic_structure",(sto_structure,))
    add_entity(target_db,"model__default_stochastic_structure",(model_name,sto_structure))
    add_entity(target_db,"model__default_investment_stochastic_structure",(model_name,sto_structure))
    add_entity(target_db,"stochastic_scenario",(sto_scenario,))
    add_entity(target_db,"stochastic_structure__stochastic_scenario",(sto_structure,sto_scenario))
    
    periods = json.loads(source_db.get_parameter_value_items(entity_class_name = "solve_pattern", parameter_definition_name = "period")[0]["value"])["data"]
    resolution = json.loads(source_db.get_parameter_value_items(entity_class_name = "solve_pattern", parameter_definition_name = "time_resolution")[0]["value"])["data"]
    
    # historical data
    duration = json.loads(source_db.get_parameter_value_items(entity_class_name = "solve_pattern", parameter_definition_name = "duration")[0]["value"])["data"]
    py_yearrs = []
    # if not multiyear
    if len(periods) == 1:
        print("it is not a multiyear invesment problem")
        # model horizon
        for period in periods:
            py_start = json.loads(source_db.get_parameter_value_item(entity_class_name = "period", parameter_definition_name = "start_time", alternative_name = "Base", entity_byname = (period,))["value"])["data"]
            py_yearr = source_db.get_parameter_value_item(entity_class_name = "period", parameter_definition_name = "years_represented", alternative_name = "Base", entity_byname = (period,))["parsed_value"]
            py_yearrs.append(py_yearr)
            print("Leap Year: ", bool(pd.Timestamp(py_start).year % 4 == 0), period)
            extra_duration = pd.Timedelta("1D") if pd.Timestamp(py_start).year % 4 == 0 else pd.Timedelta("0h")
            py_end = (pd.Timestamp(py_start) + pd.Timedelta(duration) + extra_duration).isoformat()
            add_parameter_value(target_db,"model","model_start","Base",(model_name,),{"type":"date_time","data":py_start})
            add_parameter_value(target_db,"model","model_end","Base",(model_name,),{"type":"date_time","data":py_end})

            # operational_resolution
            temporal_block_name = "operations"
            add_entity(target_db,"temporal_block",(temporal_block_name,))
            add_entity(target_db,"model__default_temporal_block",(model_name,temporal_block_name))
            add_parameter_value(target_db,"temporal_block","resolution","Base",(temporal_block_name,),{"type":"duration","data":resolution})
            add_parameter_value(target_db,"temporal_block","weight","Base",(temporal_block_name,),py_yearr)
            add_parameter_value(target_db,"temporal_block","has_free_start","Base",(temporal_block_name,),True)

    else:
        print("Multiyear investment planning")
        py_starts = []
        py_ends = []
        py_yearrs = []
        # model horizon
        for period in periods:
            # add_alternative(target_db,period)
            py_start = json.loads(source_db.get_parameter_value_item(entity_class_name = "period", parameter_definition_name = "start_time", alternative_name = "Base", entity_byname = (period,))["value"])["data"]
            py_yearr = source_db.get_parameter_value_item(entity_class_name = "period", parameter_definition_name = "years_represented", alternative_name = "Base", entity_byname = (period,))["parsed_value"]
            py_yearrs.append(py_yearr)
            # operational_resolution
            temporal_block_name = f"operations_{period}"
            add_entity(target_db,"temporal_block",(temporal_block_name,))
            add_entity(target_db,"model__default_temporal_block",(model_name,temporal_block_name))
            add_parameter_value(target_db,"temporal_block","resolution","Base",(temporal_block_name,),{"type":"duration","data":resolution})
            if bool(pd.Timestamp(py_start).year % 4 == 0):
                print("Leap Year: ", bool(pd.Timestamp(py_start).year % 4 == 0), period)
                block_start = (pd.Timestamp(py_start) + pd.Timedelta(days=366) - (pd.Timedelta(resolution) if periods.index(period)>0 else pd.Timedelta("0h"))).isoformat()
                block_end = (pd.Timestamp(py_start) + pd.Timedelta(days=366) + pd.Timedelta(duration)).isoformat()
            else:
                block_start = (pd.Timestamp(py_start)).isoformat()
                block_end = (pd.Timestamp(py_start) + pd.Timedelta(duration)).isoformat()

            add_parameter_value(target_db,"temporal_block","block_start","Base",(temporal_block_name,),{"type":"date_time","data":block_start})
            add_parameter_value(target_db,"temporal_block","block_end","Base",(temporal_block_name,),{"type":"date_time","data":block_end})
            add_parameter_value(target_db,"temporal_block","weight","Base",(temporal_block_name,),py_yearr)
            add_parameter_value(target_db,"temporal_block","has_free_start","Base",(temporal_block_name,),True)
            
            py_starts.append(pd.Timestamp(py_start))
            py_ends.append(pd.Timestamp(str(int(py_start[:4]) + int(py_yearr))+"-01-01T00:00:00"))
        
        add_parameter_value(target_db,"model","model_start","Base",(model_name,),{"type":"date_time","data":min(py_starts).isoformat()})
        add_parameter_value(target_db,"model","model_end","Base",(model_name,),{"type":"date_time","data":max(py_ends).isoformat()})
        # add_parameter_value(target_db,"model","discount_year",period,(model_name,),{"type":"date_time","data":py_start})

    # investment_resolution
    temporal_block_name = "planning"
    add_entity(target_db,"temporal_block",(temporal_block_name,))
    add_entity(target_db,"model__default_investment_temporal_block",(model_name,temporal_block_name))
    add_parameter_value(target_db,"temporal_block","resolution","Base",(temporal_block_name,),{"type":"array","value_type":"duration","data":[f"{str(int(yearr))}Y" for yearr in py_yearrs]})

    try:
        target_db.commit_session("Added timeline")
    except:
        print("commit timeline error")

def storage_state_fix_method(source_db,target_db):
    
    periods = json.loads(source_db.get_parameter_value_items(entity_class_name = "solve_pattern", parameter_definition_name = "period")[0]["value"])["data"]
    resolution = json.loads(source_db.get_parameter_value_items(entity_class_name = "solve_pattern", parameter_definition_name = "time_resolution")[0]["value"])["data"]
    block_starts = {}
    for period in periods:
        py_start = json.loads(source_db.get_parameter_value_item(entity_class_name = "period", parameter_definition_name = "start_time", alternative_name = "Base", entity_byname = (period,))["value"])["data"]
        block_starts[period] = (pd.Timestamp(py_start) + pd.Timedelta(days=366)).isoformat() if bool(pd.Timestamp(py_start).year % 4 == 0) else py_start
    for storage_method in source_db.get_parameter_value_items(parameter_definition_name = "storage_state_fix_method"):
        
        if storage_method["parsed_value"] == "fix_start":
            values_ = source_db.get_parameter_value_items(entity_class_name = storage_method["entity_class_name"], entity_byname= storage_method["entity_byname"], parameter_definition_name = "storage_state_fix")
            if values_:
                capacities_ = source_db.get_parameter_value_items(entity_class_name = storage_method["entity_class_name"], entity_byname= storage_method["entity_byname"], parameter_definition_name = "storage_capacity")
                if capacities_:
                    existings_ = source_db.get_parameter_value_items(entity_class_name = storage_method["entity_class_name"], entity_byname= storage_method["entity_byname"], parameter_definition_name = "storages_existing")
                    for existing_ in existings_:
                        if not existing_:
                            multiplier = 1.0
                        else:
                            if existing_["type"] == "float":
                                multiplier = existing_["parsed_value"]
                            elif existing_["type"] == "map":
                                if len(existing_["parsed_value"].values) == 1:
                                    multiplier = existing_["parsed_value"].values[0]
                                else:
                                    multiplier = dict(zip(existing_["parsed_value"].indexes,existing_["parsed_value"].values))

                        for capacity_ in capacities_:
                            for value_ in values_:
                                if value_["type"] == "float":
                                    if capacity_["type"] == "float":
                                        target_value_ = value_["parsed_value"]*capacity_["parsed_value"]


                                        alternatives = [i for i in [value_["alternative_name"],capacity_["alternative_name"],existing_["alternative_name"]] if i != "Base"]
                                        if len(alternatives) == 0:
                                            alternative_name = "Base"
                                        elif len(alternatives) == 1:
                                            alternative_name = alternatives[0]
                                        else:
                                            alternative_name = "_".join(alternatives)
                                            try:
                                                add_alternative(target_db,alternative_name)
                                            except:
                                                print(f"{alternative_name} alternative already added")

                                    indexes_ = []
                                    vals_ = []
                                    for period, block_start in block_starts.items():
                                        indexes_.append((pd.Timestamp(block_start) - pd.Timedelta(resolution)).isoformat())
                                        indexes_.append(block_start)
                                        vals_.append((multiplier if isinstance(multiplier,float) else multiplier[period])*target_value_)
                                        vals_.append(None)
                                    target_ts_ = {"type":"time_series","data":dict(zip(indexes_,vals_))}
                                    add_parameter_value(target_db,"node","storage_state_fix",alternative_name,value_["entity_byname"],target_ts_)
                else:
                    print("WARNING: FIXED STATE DOES NOT EXIST ", storage_method["entity_byname"])
        
        elif storage_method["parsed_value"] == "fix_start_and_horizon_end":
            values_ = source_db.get_parameter_value_items(entity_class_name = storage_method["entity_class_name"], entity_byname= storage_method["entity_byname"], parameter_definition_name = "storage_state_fix")
            if not values_:
                for entity_map in target_db.get_entity_items(entity_class_name = "model__default_temporal_block"):
                    add_entity(target_db,"node__temporal_block",(storage_method["entity_name"],entity_map["entity_byname"][1]))
                    add_parameter_value(target_db,"node__temporal_block","cyclic_condition","Base",(storage_method["entity_name"],entity_map["entity_byname"][1]),True)
                    add_parameter_value(target_db,"node__temporal_block","cyclic_condition_sense","Base",(storage_method["entity_name"],entity_map["entity_byname"][1]),"==")

        else:
            print("WARNING: CAPACITY NOT DEFINED, THEN FIX STATE NOT ADDED", storage_method["entity_byname"])
    try:
        target_db.commit_session("Added fixed storage state method")
    except:
        print("commit fixed storage state error")

def storage_state_binding_method(source_db,target_db):

    for storage_method in source_db.get_parameter_value_items(parameter_definition_name = "storage_state_binding_method"):
        if storage_method["parsed_value"] == "leap_over_within_period":
            for entity_map in target_db.get_entity_items(entity_class_name = "model__default_temporal_block"):
                add_entity(target_db,"node__temporal_block",(storage_method["entity_name"],entity_map["entity_byname"][1]))
                add_parameter_value(target_db,"node__temporal_block","cyclic_condition","Base",(storage_method["entity_name"],entity_map["entity_byname"][1]),True)
    try:
        target_db.commit_session("Added storage state binding method")
    except:
        print("commit storage state binding method error")

def limiting_investments_notallowed(source_db,target_db):

    retirement_method = {"unit":"retirement_method","link":"retirement_method","node":"storage_retirement_method"}
    target_candi = {"unit":"units_existing","link":"links_existing","node":"storages_existing"}
    target_class = {"unit":"unit","link":"connection","node":"node"}
    target_param = {"unit":"investment_count_max_cumulative","link":"investment_count_max_cumulative","node":"storage_investment_count_max_cumulative"}
    fix_param = {"unit":"investment_count_fix_new","link":"investment_count_fix_new","node":"storage_investment_count_fix_new"}
    fix_av_param = {"unit":"investment_count_fix_cumulative","link":"investment_count_fix_cumulative","node":"storage_investment_count_fix_cumulative"}
    starttime = {} 
    year_repr = {} 

    for period in json.loads(source_db.get_parameter_value_items(entity_class_name = "solve_pattern", parameter_definition_name = "period")[0]["value"])["data"]:
        starttime[period] = json.loads(source_db.get_parameter_value_item(entity_class_name = "period", entity_byname = (period,), alternative_name = "Base", parameter_definition_name = "start_time")["value"])["data"]
        year_repr[period] = source_db.get_parameter_value_item(entity_class_name = "period", entity_byname = (period,), alternative_name = "Base", parameter_definition_name = "years_represented")["parsed_value"]

    for source_param in ["investment_method","storage_investment_method"]:
        for param_map in [i for i in source_db.get_parameter_value_items(parameter_definition_name = source_param) if i["parsed_value"]=="not_allowed"]:
            add_parameter_value(target_db,target_class[param_map["entity_class_name"]],fix_param[param_map["entity_class_name"]],param_map["alternative_name"],param_map["entity_byname"],0.0)
            existings_ = source_db.get_parameter_value_items(entity_class_name = param_map["entity_class_name"], parameter_definition_name = target_candi[param_map["entity_class_name"]], entity_byname = param_map["entity_byname"])
            if existings_:
                for existing_ in existings_:
                    if existing_["type"] == "map":
                        
                        map_table = convert_map_to_table(existing_["parsed_value"])
                        index_names = nested_index_names(existing_["parsed_value"])
                        data = pd.DataFrame(map_table, columns=index_names + ["value"]).set_index(index_names[0])
                        data.index = data.index.astype("string")

                        if any(i in data.index for i in starttime):
                            indexes_ = []
                            values_ = []
                            for period_, ts_index_ in starttime.items():
                                if period_ in data.index:
                                    values_.append(float(data.at[period_,"value"]))
                                    # this should be removed once the fixed resolution is repaired
                                    indexes_.append(ts_index_)

                            values_.append(values_[-1]) 
                            indexes_.append((pd.Timestamp(ts_index_).replace(year=int(pd.Timestamp(ts_index_).year+year_repr[period_]))).isoformat())

                            if len(data) > 1:
                                value_ = {"type": "time_series","data": dict(zip(indexes_,values_))}
                            else:
                                value_ = values_[0]

                            add_parameter_value(target_db,target_class[param_map["entity_class_name"]],target_param[param_map["entity_class_name"]],existing_["alternative_name"],existing_["entity_byname"],value_)
                    
                            retirement_method_value = source_db.get_parameter_value_item(entity_class_name=param_map["entity_class_name"],parameter_definition_name=retirement_method[param_map["entity_class_name"]],entity_byname=param_map["entity_byname"],alternative_name="Base")
                            if retirement_method_value:
                                if retirement_method_value["parsed_value"] =="not_retired":
                                    add_parameter_value(target_db,target_class[param_map["entity_class_name"]],fix_av_param[param_map["entity_class_name"]],existing_["alternative_name"],existing_["entity_byname"],value_)

                    elif existing_["type"] == "float":
                        value_ = existing_["parsed_value"]
                        add_parameter_value(target_db,target_class[param_map["entity_class_name"]],target_param[param_map["entity_class_name"]],existing_["alternative_name"],existing_["entity_byname"],value_)
                        retirement_method_value = source_db.get_parameter_value_item(entity_class_name=param_map["entity_class_name"],parameter_definition_name=retirement_method[param_map["entity_class_name"]],entity_byname=param_map["entity_byname"],alternative_name="Base")
                        if retirement_method_value:
                            if retirement_method_value["parsed_value"] =="not_retired":
                                add_parameter_value(target_db,target_class[param_map["entity_class_name"]],fix_av_param[param_map["entity_class_name"]],existing_["alternative_name"],existing_["entity_byname"],value_)

            else: 
                print(f"There is no existing capacity in {param_map['entity_class_name']} {param_map['entity_byname']}")

    try:
        target_db.commit_session("Added candadite assets")
    except:
        print("commit candadite assets error")    

def set_to_entities_and_parameters(source_db,target_db):

    model_duration = json.loads(source_db.get_parameter_value_items(entity_class_name = "solve_pattern", parameter_definition_name = "duration")[0]["value"])["data"]
    resolution = json.loads(source_db.get_parameter_value_items(entity_class_name = "solve_pattern", parameter_definition_name = "time_resolution")[0]["value"])["data"]
    
    for source_parameter in ["max_cumulative","flow_max_cumulative"]:
        for source_dict_parameter in source_db.get_parameter_value_items(entity_class_name = "set", parameter_definition_name = source_parameter):
            source_relationships = {relation: [] for relation in ["set__unit_flow","set__node","set__unit","set__link"]}
            for relation in source_relationships:  
                for element in source_db.get_entity_items(entity_class_name = relation):
                    if element["entity_byname"][0] == source_dict_parameter["entity_byname"][0]:
                        source_relationships[relation].append(element["entity_byname"])
            if source_parameter == "max_cumulative":
                try:
                    add_entity(target_db,"investment_group",source_dict_parameter["entity_byname"])
                    print("Entity already created","investment_group",source_dict_parameter["entity_byname"])
                except:
                    pass
                add_parameter_value(target_db,"investment_group","investment_count_total_max_cumulative",source_dict_parameter["alternative_name"],source_dict_parameter["entity_byname"],source_dict_parameter["parsed_value"])
                for entity_relation, list_relation in source_relationships.items():
                    if entity_relation == "set__unit":
                        for names_relation in list_relation:
                            entity_byname = (names_relation[1],names_relation[0])
                            add_entity(target_db,"unit__investment_group",entity_byname)
                    if entity_relation == "set__node":
                        for names_relation in list_relation:
                            entity_byname = (names_relation[1],names_relation[0])
                            add_entity(target_db,"node__investment_group",entity_byname)
                    if entity_relation == "set__link":
                        for names_relation in list_relation:
                            entity_byname = (names_relation[1],names_relation[0])
                            add_entity(target_db,"connection__investment_group",entity_byname)

            elif source_parameter == "flow_max_cumulative":
                if len(source_relationships) == 1:
                    for entity_relation, names_relation in source_relationships.items():
                        if entity_relation == "set__unit_flow":
                            source_flow = source_db.get_entity_items(entity_byname = names_relation[1:])[0]["entity_class_name"]
                            target_entity_class = "node__to_unit" if source_flow == "node__to_unit" else "unit__to_node"
                            target_entity_names = (names_relation[1],names_relation[2])
                            try:
                                add_entity(target_db,target_entity_class,target_entity_names)
                            except:
                                pass
                            model_duration_hours = pd.Timedelta(model_duration) / pd.Timedelta(resolution)
                            param_value = model_duration_hours * source_dict_parameter["parsed_value"]
                            add_parameter_value(target_db,target_entity_class,"flow_limits_max_cumulative",source_dict_parameter["alternative_name"],target_entity_names,param_value)
                else:
                    pass
    try:
        target_db.commit_session("Added set constraints")
    except:
        print("commit set constraints error")  

def default_parameters(target_db,settings):
    for target_entity_class in settings:
        for entity_item in target_db.get_entity_items(entity_class_name = target_entity_class):
            for target_parameter in settings[target_entity_class]:
                print(f"Adding {target_parameter} {entity_item["entity_byname"]}")
                try:
                    add_parameter_value(target_db,target_entity_class,target_parameter,"Base",entity_item["entity_byname"],settings[target_entity_class][target_parameter])
                except:
                    print(f"It seems to be previously added {target_parameter} {entity_item["entity_byname"]}")

    try:
        target_db.commit_session("Added default_parameters")
    except:
        print("commit default_parameters error")  

def existing_capacity(source_db,target_db):

    entity_map = {"unit":"unit","node":"node","link":"connection"}
    parameter_conversion = {"units_existing":"investment_count_initial_cumulative","links_existing":"investment_count_initial_cumulative","storages_existing":"storage_investment_count_initial_cumulative"}
    for source_parameter in parameter_conversion:
        target_parameter = parameter_conversion[source_parameter]
        for param_map in source_db.get_parameter_value_items(parameter_definition_name = source_parameter):
            if param_map["type"] == "map":
                param_dict = json.loads(param_map["value"].decode("utf-8"))
                param_value = param_dict["data"]
                target_entity = entity_map[param_map["entity_class_name"]]
                vals = np.fromiter(param_value.values(), dtype=float)
                add_parameter_value(target_db,target_entity,target_parameter,param_map["alternative_name"],param_map["entity_byname"],vals[0])
            elif param_map["type"] == "float":
                target_entity = entity_map[param_map["entity_class_name"]]
                add_parameter_value(target_db,target_entity,target_parameter,param_map["alternative_name"],param_map["entity_byname"],param_map["parsed_value"])
    try:
        target_db.commit_session("Added existing capacity")
    except:
        print("commit existing capacity error")

def lifetime_to_duration(source_db,target_db,settings):

    for source_class in settings:
        for target_class in settings[source_class]:
            for source_param in settings[source_class][target_class]:
                for param_map in source_db.get_parameter_value_items(entity_class_name = source_class, parameter_definition_name = source_param):
                    if param_map["type"] == "float":
                        param_value = {"type":"duration","data":str(int(param_map["parsed_value"]))+"Y"}
                    elif param_map["type"] == "map":
                        param_value = {"type":"duration","data":str(int(param_map["parsed_value"].values[0]))+"Y"}
                    
                    for target_param in settings[source_class][target_class][source_param]:
                        print(target_param, param_map["entity_byname"])
                        add_parameter_value(target_db,target_class,target_param,param_map["alternative_name"],param_map["entity_byname"],param_value)
                
    try:
        target_db.commit_session("Added lifetime conversion")
    except:
        print("commit lifetime conversion error")

def unit_flow_variants(source_db,target_db,settings):

    parameters_mapping = {"equality_ratio":"flow_ratio_equality_coefficient","less_than_ratio":"flow_ratio_less_than_coefficient","greater_than_ratio":"flow_ratio_greater_than_coefficient"}
    for param_map in source_db.get_parameter_value_items(entity_class_name = "unit_flow__unit_flow"):

        target_parameter = parameters_mapping[param_map["parameter_definition_name"]]

        try:
            add_entity(target_db,"unit_flow__unit_flow",param_map["entity_byname"])
        except:
            pass
        
        if param_map["type"] == "float":
            add_parameter_value(target_db,"unit_flow__unit_flow",target_parameter,param_map["alternative_name"],param_map["entity_byname"],param_map["parsed_value"])
        
        elif param_map["type"] == "map":
            
            starttime = {} 
            year_repr = {} 
            for period in json.loads(source_db.get_parameter_value_items(entity_class_name = "solve_pattern", parameter_definition_name = "period")[0]["value"])["data"]:
                starttime[period] = json.loads(source_db.get_parameter_value_item(entity_class_name = "period", entity_byname = (period,), alternative_name = "Base", parameter_definition_name = "start_time")["value"])["data"]
                year_repr[period] = source_db.get_parameter_value_item(entity_class_name = "period", entity_byname = (period,), alternative_name = "Base", parameter_definition_name = "years_represented")["parsed_value"]

            duration      = json.loads(source_db.get_parameter_value_items(entity_class_name = "solve_pattern", parameter_definition_name = "duration")[0]["value"])["data"]
            starttime_sp  = json.loads(source_db.get_parameter_value_items(entity_class_name = "solve_pattern", parameter_definition_name = "start_time")[0]["value"])["data"]
            resolution    = json.loads(source_db.get_parameter_value_items(entity_class_name = "solve_pattern", parameter_definition_name = "time_resolution")[0]["value"])["data"]
    
            index_names = nested_index_names(param_map["parsed_value"])
            map_table = convert_map_to_table(param_map["parsed_value"])
            index_names = nested_index_names(param_map["parsed_value"])
            data = pd.DataFrame(map_table, columns=index_names + ["value"]).set_index(index_names[0])
            data.index = data.index.astype("string")

            if any(i in data.index for i in starttime):
                indexes_ = []
                values_ = []
                for period_, ts_index_ in starttime.items():
                    values_.append((float(data.at[period_,"value"]) if period_ in data.index else 0.0))
                    
                    # this should be removed once the fixed resolution is repaired
                    indexes_.append(ts_index_)
                values_.append(values_[-1]) 
                indexes_.append((pd.Timestamp(ts_index_).replace(year=int(pd.Timestamp(ts_index_).year+year_repr[period_]))).isoformat())
                ts_export = {"type": "time_series","data": dict(zip(indexes_,values_))}
                add_parameter_value(target_db,"unit_flow__unit_flow",target_parameter,param_map["alternative_name"],param_map["entity_byname"],ts_export)

            if any(i in data.index for i in starttime_sp):
                for index, element in enumerate(starttime_sp):
                    try:
                        alternative_name = f"wy{str(pd.Timestamp(element).year)}"
                        add_alternative(target_db,alternative_name)
                    except:
                        pass
                    steps = pd.to_timedelta(duration) / pd.to_timedelta(resolution)
                    df_data = (data.iloc[data.index.tolist().index(element):data.index.tolist().index(element)+int(steps),data.columns.tolist().index("value")]).tolist()
                    ts_export = {"type": "time_series","data": df_data,"index": {"start": f"2018{element[4:]}","resolution": resolution,"ignore_year": True}}
                    add_parameter_value(target_db,"unit_flow__unit_flow",target_parameter,alternative_name,param_map["entity_byname"],ts_export)
                   

    try:
        target_db.commit_session("Added unit flows")
    except:
        print("commit unit flows error")

def flow_profile_method(source_db,target_db):

    duration   = json.loads(source_db.get_parameter_value_items(entity_class_name = "solve_pattern", parameter_definition_name = "duration")[0]["value"])["data"]
    starttime  = json.loads(source_db.get_parameter_value_items(entity_class_name = "solve_pattern", parameter_definition_name = "start_time")[0]["value"])["data"]
    resolution = json.loads(source_db.get_parameter_value_items(entity_class_name = "solve_pattern", parameter_definition_name = "time_resolution")[0]["value"])["data"]
                

    for param_map in source_db.get_parameter_value_items(entity_class_name = "node", alternative_name = "Base", parameter_definition_name = "flow_profile"):

        flow_method = source_db.get_parameter_value_item(entity_class_name = "node", alternative_name = "Base", entity_byname = param_map["entity_byname"], parameter_definition_name = "flow_scaling_method")
        
        if flow_method["parsed_value"] == "scale_to_annual":
            target_name = param_map["entity_name"]+"-group"
            add_entity(target_db,"node",(target_name,))
            add_parameter_value(target_db,"node","balance_type","Base",(target_name,),"none")
            add_entity_group(target_db,"node",target_name,param_map["entity_name"])
            definition_condition = True
        elif flow_method["parsed_value"] == "use_profile_directly":
            target_name = param_map["entity_name"]
            definition_condition = True
        else:
            print("flow profile wont be defined")
            definition_condition = False
        
        if definition_condition:
            if param_map["type"] == "map":
                index_names = nested_index_names(param_map["parsed_value"])
                map_table = convert_map_to_table(param_map["parsed_value"])
                index_names = nested_index_names(param_map["parsed_value"])
                data = pd.DataFrame(map_table, columns=index_names + ["value"]).set_index(index_names[0])
                data.index = data.index.astype("string")

                if any(i in data.index for i in starttime):
                    for index, element in enumerate(starttime):
                        try:
                            alternative_name = f"wy{str(pd.Timestamp(element).year)}"
                            add_alternative(target_db,alternative_name)
                        except:
                            pass
                        steps = pd.to_timedelta(duration) / pd.to_timedelta(resolution)
                        df_data = (-1.0*data.iloc[data.index.tolist().index(element):data.index.tolist().index(element)+int(steps),data.columns.tolist().index("value")]).tolist()
                        ts_export = {"type": "time_series","data": df_data,"index": {"start": f"2018{element[4:]}","resolution": resolution,"ignore_year": True}}
                        add_parameter_value(target_db,"node","demand",alternative_name,(target_name,),ts_export)
            
            elif param_map["type"] == "float":
                add_parameter_value(target_db,"node","demand",param_map["alternative_name"],(target_name,),-1.0*param_map["parsed_value"])
          
    try:
        target_db.commit_session("Added flow profile")
    except:
        print("commit flow profile error")

def link_parameters_to_directions(source_db,target_db,settings):

    for source_parameter in settings:
        for parameter_map in source_db.get_parameter_value_items(entity_class_name = "link", parameter_definition_name = source_parameter):
            for entity_direction in [entity_i for entity_i in source_db.get_entity_items(entity_class_name = "node__link__node") if entity_i["entity_byname"][1] == parameter_map["entity_byname"][0]]:
                if parameter_map["type"] == "float":
                    target_class = settings[source_parameter][0]
                    target_entity = tuple(["__".join([entity_direction["entity_byname"][int(i)-1] for i in k]) for k in settings[source_parameter][3]])
                    target_parameter = settings[source_parameter][1]
                    target_value = settings[source_parameter][2] * parameter_map["parsed_value"]
                    target_alternative = parameter_map["alternative_name"]

                    print(target_class,target_parameter,target_entity)
                    add_parameter_value(target_db,target_class,target_parameter,target_alternative,target_entity,target_value)
    try:
        target_db.commit_session("Added link parameters")
    except:
        print("commit link parameters error")

if __name__ == "__main__":
    main()