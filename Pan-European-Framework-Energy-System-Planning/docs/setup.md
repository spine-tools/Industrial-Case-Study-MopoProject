---
title: Set Up Your Framework
nav_order: 3
---

# Key Details

* Sectoral spatial resolution
* Possibility to run your model for 5 weather years: 1995, 2008, 2009, 2012, and 2015. More than 40 years of climate data for residual electricity demand, VRE, and hydro.
* 2025 as baseline
* 3 planning years available: 2030, 2040 and 2050
* Bronwfield scenario

# Model Configuration Guide

This guide explains how to configure your energy system model using the `userconfig.yaml` file. This configuration file allows you to customize model behavior, select technologies, define constraints, and specify which sectors to include in your analysis.

## Overview

The `userconfig.yaml` file is structured into several main sections that control different aspects of the model:

- **Pipelines**: Enable/disable major model components and their corresponding resolution
- **Countries**: Specify geographical scope
- **Model Settings**: Define model type, temporal resolution, and planning years
- **Timeline**: Set historical periods
- **Global Constraints**: Configure CO₂ budgets
- **Commodities**: Define energy carriers and their properties
- **Network**: Configure transmission networks
- **Storage**: Select storage technologies and investment options
- **Technologies**: Configure power generation, conversion, and end-use technologies
- **End-use**: Define heating and cooling demand sectors
- **Vehicles**: Select transport vehicle types

---

## 1. Pipelines

Control which major sectors and systems are included in the model.

```yaml
pipelines:
  power_sector: 
    status: True             # include pipeline or not
    source_resolution: NUTS3 # Do not touch unless you rerun the corresponding pipeline producing data in that resolution
    target_resolution: PECD1 # Using the weighting factors from the documentation (configurable in sysconfig.yaml file)
  vre:
    status: True
    source_resolution:
      "on": PECD2 
      "off": OFF3
    target_resolution:
      "on": PECD1
      "off": OFF2
  hydro_systems:
    status: True
    source_resolution: PECD1
    target_resolution: PECD1
  biomass_production:
    status: True
    source_resolution: PECD1
    target_resolution: PECD1
  power_transmission:
    status: True
    source_resolution: PECD1
    target_resolution: PECD1
  residual_demand:
    status: True
    source_resolution: PECD1
    target_resolution: PECD1
  gas_sector:
    status: True
    source_resolution: PECD1
    target_resolution: PECD1
  gas_pipelines: 
    status: True
    source_resolution: PECD1
    target_resolution: PECD1
  industrial_sector:
    status: True
    source_resolution: NUTS3
    target_resolution: PECD1
  other_industrial_sector:
    status: True
    source_resolution: PECD1
    target_resolution: PECD1
  heat_sector:
    status: True
    source_resolution: PECD1
    target_resolution: PECD1
  transport_sector:
    status: True
    source_resolution: PECD1
    target_resolution: PECD1
  cargo_transport:
    status: True
    source_resolution: PECD1
    target_resolution: PECD1
```

**Usage**: Set to `True` to include the pipeline in your model, or `False` to exclude it. In this format, the user can choose the target resolution for each sector and the source resolution, in case they manipulate the corresponding pipeline. The data [section](data.md) provides more detail about each sector and its differences.

Some sector like power and industry could be imported at different resolutions. Network resolution are fixed and the user must run the corresponding data pipeline with the desirable resolution (currently cross-border), that is, source resolution is always equal to target resolution.


## 2. Countries

Define geographical scope and onshore/offshore wind characteristics.

```yaml
countries:
  - Europe
  - ES
```

**Usage**:
- Use `Europe` as a country code to model all of Europe with default settings
- Add specific country codes (e.g., `ES` for Spain, `DE` for Germany) to customize individual countries


**Available Country Codes**:

```
  countries = [
        "AT",  # Austria
        "BE",  # Belgium
        "BG",  # Bulgaria
        "HR",  # Croatia
        "CY",  # Cyprus
        "CZ",  # Czech Republic
        "DK",  # Denmark
        "EE",  # Estonia
        "FI",  # Finland
        "FR",  # France
        "DE",  # Germany
        "GR",  # Greece
        "HU",  # Hungary
        "IE",  # Ireland
        "IT",  # Italy
        "LV",  # Latvia
        "LT",  # Lithuania
        "LU",  # Luxembourg
        "MT",  # Malta
        "NL",  # Netherlands
        "PL",  # Poland
        "PT",  # Portugal
        "RO",  # Romania
        "SK",  # Slovakia
        "SI",  # Slovenia
        "ES",  # Spain
        "SE",  # Sweden
        "CH",  # Switzerland
        "UK",  # United Kingdom
        "NO"   # Norway
    ]
```

---

## 3. Model Settings

Define the fundamental model characteristics and planning horizons.

```yaml
model:
    type: brownfield  # greenfied not included yet
    operations_resolution: "1h"
    planning_resolution: "365D"
    planning_years:
      "2030": ["2030-01-01T00:00:00", 10.0]
      "2040": ["2041-01-01T00:00:00", 10.0]
      "2050": ["2050-01-01T00:00:00", 10.0]
    units: # options: GW and Meuro, or MW and euro
      energy: "GW" # GW or MW
      cost: "Meuro" # Million euro or euro
```

**Parameters**:
- `type`: Model approach
  - `brownfield`: Includes existing infrastructure (recommended)
  - `greenfield`: Build from scratch (not yet implemented)
- `operations_resolution`: Time step for operational decisions (e.g., "1h", "3h")
- `planning_resolution`: Planning period length (e.g., "365D" for annual)
- `planning_years`: Dictionary of target years with:
  - Start date in ISO format
  - Investment period weight (typically 10.0)
- `units`: which units we use for the parameters to correctly scale the optimization model:
  - energy units, you can select GW or MW (GWh or MWh)
  - cost units, you can select Meuro (million euros) or euros.
  - There are two options available, GW and Meuro or MW and euro.

**Available Planning Years**: 2030, 2040, 2050

---

## 4. Timeline Configuration

Set historical reference years and temporal clustering options.

```yaml
timeline:
  historical_alt:
    CY_1995:
      start: "1995-01-01T00:00:00"
    CY_2008:
      start: "2008-01-01T00:00:00"
    CY_2009:
      start: "2009-01-01T00:00:00"
```

**Historical Periods**: Define reference years for weather and demand patterns

---

## 5. Global Constraints

Set system-wide CO₂ limits and renewable energy targets.

```yaml
global_constraints:
  co2_annual_budget:
    "2030": 2200000000  # European level (tonnes CO₂)
    "2040": 550000000   # European level
    "2050": 0.0         # Net-zero target
  co2_annual_sequestration: 200000000  # European level (tonnes CO₂)
```

**Parameters**:
- `co2_annual_budget`: Maximum annual CO₂ emissions (tonnes) for each planning year
- `co2_annual_sequestration`: Maximum annual CO₂ that can be sequestered (tonnes)

---

## 6. Commodities (Energy Carriers)

Define which energy carriers are modeled and their properties.

```yaml
commodity:
  elec:
    status: True           # Model this commodity
    node_type: balance     # Requires supply-demand balance
  CH4:
    status: True
    node_type: balance
  H2:
    status: True
    node_type: balance
  CO2:
    status: False
    node_type: storage     # Storage node, defined per country
  fossil-CH4:
    status: False
    node_type: commodity   # No balance equation required
```

**Node Types**:
- `balance`: Supply must equal demand at each node (per country)
- `storage`: Commodity can be stored
- `commodity`: Simple commodity node without balance constraint

**Common Commodities**:
- `elec`: Electricity
- `CH4`: Methane/natural gas
- `H2`: Hydrogen
- `CO2`: Carbon dioxide
- `bio`: Biomass
- `HC`: Hydrocarbons
- `MeOH`: Methanol
- `fossil-CH4`, `fossil-HC`: Fossil fuel sources
- `crude`, `coal`, `U-92`: Primary energy sources
- `waste`: Waste materials

**Set `status: True`** to include the commodity in your model.

Note that industrial commodities are not included here as they are always considered to be modeled, per country and as balanced node.

---

## 7. Transmission Networks

Enable transmission networks between regions for different commodities.

```yaml
network:
  elec:
    status: True  # Model electricity transmission
  CH4:
    status: True
  H2:
    status: True
  bio:
    status: True
  HC:
    status: True
  MeOH:
    status: True
```

**Usage**: Set `status: True` to allow transmission of that commodity.

**NOTE**. When modeling only one country, the interconnections with others are considered with fixed exogenous price for the commodity exported or imported from the neighboring region.

---


## 9. Storage Technologies

Configure available storage technologies and their investment constraints.

```yaml
storage:
  battery-storage:
    status: True                    # True = it is included in the model
    investment_method : "no_limits" # not_allowed, no_limits or cumulative_limits
  battery-storage-iron-air:
    status: True 
    investment_method : "no_limits"
  CH4-geo-formation : 
    status: True 
    investment_method : "not_allowed"
  salt-cavern :
    status: True 
    investment_method : "cumulative_limits"
```

**Investment Methods**:
- `not_allowed`: Only existing capacity can be used (no new investments)
- `no_limits`: Unlimited investment allowed
- `cumulative_limits`: Total investment is constrained by resource availability

**Available Storage Types**:
- `baterry-storage`: Large-scale short-term battery storage
- `baterry-storage-iron-air`: Large-scale short-term battery storage
- `CH4-geo-formation`: Underground methane storage
- `salt-cavern`: Salt cavern storage (typically for hydrogen)

---

## 10. Technologies

Configure individual technologies with detailed settings. Technologies are organized by sector.

### Technology Configuration Structure

Each technology has four main properties:

```yaml
technology:
  CCGT:
    status: True                      # Include in model
    investment_method: "no_limits"    # Investment constraint
```

### Investment Methods

- `not_allowed`: Existing units only (typically used with `-existing` suffix)
- `no_limits`: Unrestricted new investments
- `cumulative_limits`: Limited by resource constraints

### Power Generation Technologies

**Fossil Fuel Plants**:

```yaml
  CCGT:
    status: False
    investment_method: "no_limits"
  CCGT-existing:
    status: True
    investment_method: "not_allowed"
  CCGT+CC:
    status: True
    investment_method: "no_limits"
```

- `SCPC`: Supercritical Pulverized Coal
- `OCGT`: Open Cycle Gas Turbine
- `CCGT`: Combined Cycle Gas Turbine
- `+CC` suffix: Includes carbon capture

**Nuclear**:

```yaml
  nuclear-3:
    status: True
    investment_method: "no_limits"
```

**Biomass & Waste**:

```yaml
  bioST:
    status: True
    investment_method: "no_limits"
  wasteST-existing:
    status: True
    investment_method: "not_allowed"
```

### Renewable Energy Technologies

**Wind Power**:

```yaml
  wind-on-SP199-HH100:
    status: True
    investment_method: "no_limits"
  wind-off-FB-SP370-HH155:
    status: True
    investment_method: "no_limits"
```

Wind technology naming convention: `wind-[on/off]-[type]-SP[rotor]-HH[height]`
- `on`: Onshore, `off`: Offshore
- `FB`: Fixed-bottom, `FO`: Floating offshore
- `SP###`: Specific power (W/m²)
- `HH###`: Hub height (m)

**Solar Power**:

```yaml
  solar-PV-no-tracking:
    status: True
    investment_method: "no_limits"
  solar-PV-rooftop:
    status: False
    investment_method: "no_limits"
  solar-CSP:
    status: False
    investment_method: "no_limits"
```

**Hydropower**:

```yaml
  hydro-turbine:
    status: True
    investment_method: "not_allowed"
```

### Hydrogen Production

```yaml
  SMR:
    status: True
    investment_method: "no_limits"
  SMR+CC:
    status: True
    investment_method: "no_limits"
  PEM:
    status: True
    investment_method: "no_limits"
  AEC:
    status: False
    investment_method: "no_limits"
```

- `SMR`: Steam Methane Reforming
- `SMR+CC`: SMR with carbon capture
- `PEM`: Proton Exchange Membrane electrolyzer
- `AEC`: Alkaline Electrolyzer

### Heat Technologies

**Residential & Commercial Heating**:

```yaml
  air-heatpump:
    status: True
    investment_method: "no_limits"
  ground-heatpump:
    status: True
    investment_method: "no_limits"
  gas-boiler:
    status: True
    investment_method: "no_limits"
  oil-boiler:
    status: True
    investment_method: "no_limits"
  bio-boiler:
    status: True
    investment_method: "no_limits"
  electric-heating:
    status: True
    investment_method: "no_limits"
```

### Industrial Technologies

Industrial routes use a special naming convention:

```yaml
  (H2)DRI-EAF:
    status: true
  (NG)DRI-EAF:
    status: true
  (NG)DRI-EAF-MEA:
    status: true
  BF-BOF:
    status: true
  BF-BOF-MEA:
    status: true
```

**Naming Convention**: `(Input)Process-Technology` or `(Input)Process-Technology-CarbonCapture`

**Common Prefixes**:
- `(H2)`: Hydrogen-based
- `(NG)`: Natural gas-based
- `(EL)`: Electricity-based
- `(BM)`: Biomass-based
- `(COEL)`: CO₂ + electricity-based

**Common Suffixes**:
- `-MEA`: With MEA carbon capture
- `-CC`: With carbon capture
- `-DC`: Direct conversion

**Examples**:
- `(H2)DRI-EAF`: Hydrogen-based Direct Reduced Iron - Electric Arc Furnace (steel)
- `(NG)NH3`: Natural gas-based ammonia production
- `(H2)FT-DC`: Hydrogen-based Fischer-Tropsch synthesis
- `CEM2-(Coal)`: Coal-based cement production (Type II)

---

## 11. End-Use Demand

Configure which heat and cooling demands are modeled.

```yaml
end-use:
  nonres-cool:
    status: True
  res-cool:
    status: True
  nonres-space:
    status: True
  res-space:
    status: True
  nonres-DHW:
    status: True
  res-DHW:
    status: True
  DH-space:
    status: False
  DH-DHW:
    status: False
```

**Demand Categories**:
- `res-`: Residential sector
- `nonres-`: Non-residential (commercial, services)
- `DH-`: District heating
- `-space`: Space heating
- `-cool`: Cooling
- `-DHW`: Domestic hot water

---

## 12. Vehicle Technologies

Select which vehicle types and fuel technologies to include in the transport sector.

```yaml
vehicle:
  car:
    status: True
  car-diesel:
    status: True
  car-gasoline:
    status: True
  car-DR:
    status: True  # Direct electric
  car-H2:
    status: True
  car-CNG:
    status: True
  van:
    status: True
  van-diesel:
    status: True
  truck:
    status: True
  bus:
    status: True
  aviation:
    status: True
  int-aviation:
    status: True  # International aviation
  maritime:
    status: True
  int-maritime:
    status: True  # International maritime
  rail:
    status: True
  thermal-rail:
    status: True
```

**Vehicle Categories**:
- `car`, `van`, `truck`, `bus`: Road transport
- `aviation`, `int-aviation`: Air transport (domestic and international)
- `maritime`, `int-maritime`: Sea transport (domestic and international)
- `rail`, `thermal-rail`: Rail transport

**Fuel Types** (suffixes for road vehicles):
- `-diesel`: Diesel fuel
- `-gasoline`: Gasoline/petrol
- `-DR`: Direct electric (battery electric)
- `-H2`: Hydrogen fuel cell
- `-CNG`: Compressed natural gas
- `-LNG`: Liquefied natural gas
- `-LPG`: Liquefied petroleum gas

---

## Validation Checklist

Before running your model, verify:

- [ ] At least one pipeline is enabled
- [ ] Required commodities for enabled pipelines have `status: True`
- [ ] At least one technology is enabled in each active sector
- [ ] CO₂ budgets are realistic for your scenario
- [ ] Planning years are properly configured
- [ ] Country codes are valid
- [ ] Investment methods align with your scenario goals

# WARNINGS
1. No all the technologies and options are introduced here, explore the file to check the whole catalogue.
2. The configuration files allows to model countries but all the considered countries follow the same sectoral spatial resolution.