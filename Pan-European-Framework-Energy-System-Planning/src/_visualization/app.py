import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import math
from plotly.colors import sample_colorscale
from plotly.subplots import make_subplots
import json
import geopandas as gpd
import dill
import numpy as np

# ----------------------
# Color palette
# ----------------------
def assign_color_by_technology(tech_name):
    """Asigna colores basados en el tipo de tecnología"""
    tech_lower = tech_name.lower()
    
    if 'solar' in tech_lower or 'pv' in tech_lower or 'photovoltaic' in tech_lower:
        return '#FFD700'
    elif 'wind' in tech_lower or 'eolica' in tech_lower or 'eólica' in tech_lower:
        return '#87CEEB'
    elif 'hydro' in tech_lower or 'hydra' in tech_lower or 'water' in tech_lower or 'dam' in tech_lower:
        return '#1E90FF'
    elif 'nuclear' in tech_lower or 'uranium' in tech_lower:
        return '#9370DB'
    elif 'gas' in tech_lower and 'biogas' not in tech_lower:
        return '#A9A9A9'
    elif 'coal' in tech_lower or 'carbon' in tech_lower or 'carbón' in tech_lower:
        return '#2F4F4F'
    elif 'oil' in tech_lower or 'diesel' in tech_lower or 'fuel' in tech_lower:
        return '#8B4513'
    elif 'biomass' in tech_lower or 'bio' in tech_lower or 'waste' in tech_lower:
        return '#6B8E23'
    elif 'geothermal' in tech_lower or 'geo' in tech_lower:
        return '#FF6347'
    elif 'battery' in tech_lower or 'storage' in tech_lower or 'bess' in tech_lower:
        return '#32CD32'
    elif 'renewable' in tech_lower or 'green' in tech_lower or 'clean' in tech_lower:
        return '#00FA9A'
    elif 'turbine' in tech_lower:
        return '#B0C4DE'
    elif 'ccgt' in tech_lower or 'combined cycle' in tech_lower:
        return '#C0C0C0'
    elif 'chp' in tech_lower or 'cogeneration' in tech_lower or 'cogen' in tech_lower:
        return '#DAA520'
    else:
        import hashlib
        hash_val = int(hashlib.md5(tech_name.encode()).hexdigest(), 16)
        r = (hash_val % 155) + 100
        g = ((hash_val >> 8) % 155) + 100
        b = ((hash_val >> 16) % 155) + 100
        return f'#{r:02x}{g:02x}{b:02x}'

# ----------------------
# CACHED: Load CSV files
# ----------------------
@st.cache_data
def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, index_col=0)
    df = df.loc[:, ~df.columns.str.contains(r"^Unnamed")]
    return df

# ----------------------
# CACHED: Load storage dict
# ----------------------
@st.cache_data
def load_storage_dict(path: str):
    with open(path, "rb") as f:
        return dill.load(f)

# ----------------------
# CACHED: Load all data files
# ----------------------
@st.cache_data
def load_all_data():
    installed = load_csv("files_out/installed_capacity.csv")
    invested = load_csv("files_out/invested_capacity.csv")
    invested_cost = load_csv("files_out/invested_cost.csv")
    decommissioned = load_csv("files_out/decommissioned_capacity.csv")
    unit_to_flows = load_csv("files_out/unit_to_flows.csv")
    energy_flows = load_csv("files_out/energy_flows.csv")
    crossborder_flows = load_csv("files_out/crossborder_flows.csv")
    emissions_flows = load_csv("files_out/emissions_flows.csv")
    storage_dict = load_storage_dict("files_out/node_state.dill")
    storage_installed = load_csv("files_out/storage_installed_capacity.csv")
    storage_invested = load_csv("files_out/storage_invested_capacity.csv")
    storage_cost = load_csv("files_out/storage_cost_capacity.csv")
    storage_decommissioned = load_csv("files_out/storage_decommissioned_capacity.csv")
    
    return (installed, invested, invested_cost, decommissioned, unit_to_flows, 
            energy_flows, crossborder_flows, emissions_flows, storage_dict,
            storage_installed, storage_invested, storage_cost, storage_decommissioned)

# ----------------------
# Helper: Melt wide to long
# ----------------------
def melt_df(df: pd.DataFrame, value_name: str, id_vars) -> pd.DataFrame:
    year_cols = [c for c in df.columns if c.startswith("y") and c[1:].isdigit()]
    return df.melt(id_vars=id_vars, value_vars=year_cols, var_name="year", value_name=value_name)

# ----------------------
# CACHED: Preprocess data
# ----------------------
@st.cache_data
def preprocess_data(installed, invested, invested_cost, decommissioned, unit_to_flows, id_vars):
    installed_m = melt_df(installed, "Installed", id_vars)
    invested_m = melt_df(invested, "Invested", id_vars)
    invested_cost_m = melt_df(invested_cost, "Invested_Cost", id_vars)
    decom_m = melt_df(decommissioned, "Decommissioned", id_vars)
    unit_flows_m = melt_df(unit_to_flows, "UnitFlows", id_vars)

    # Merge all
    merged = installed_m.merge(invested_m, on=id_vars + ["year"], how="outer").merge(
        decom_m, on=id_vars + ["year"], how="outer"
    ).merge(invested_cost_m, on=id_vars + ["year"], how="outer").merge(unit_flows_m, on=id_vars + ["year"], how="outer")

    # Extract numeric year and clean
    merged["year"] = merged["year"].str.extract(r"(\d+)")
    merged = merged.dropna(subset=["year"]).copy()
    merged["year"] = merged["year"].astype(int)

    # Clean categories
    for col in ["technology", "polygon", "node", "scenario"]:
        merged[col] = merged[col].astype(str).str.strip()
    merged["technology"] = merged["technology"].replace({"nan": "Unknown"})

    # Convertir de MW a GW
    merged["Installed"] = merged["Installed"] / 1
    merged["Invested"] = merged["Invested"] / 1
    merged["Invested_Cost"] = merged["Invested_Cost"] / 1e3
    merged["Decommissioned"] = merged["Decommissioned"] / 1
    merged["UnitFlows"] = merged["UnitFlows"] / 1e3

    return merged

# ----------------------
# CACHED: Preprocess storage data
# ----------------------
@st.cache_data
def preprocess_storage_data(storage_installed, storage_invested, storage_cost, storage_decommissioned, id_vars):
    installed_m = melt_df(storage_installed, "Installed", id_vars)
    invested_m = melt_df(storage_invested, "Invested", id_vars)
    cost_m = melt_df(storage_cost, "Invested_Cost", id_vars)
    decom_m = melt_df(storage_decommissioned, "Decommissioned", id_vars)

    merged = installed_m.merge(invested_m, on=id_vars + ["year"], how="outer").merge(
        decom_m, on=id_vars + ["year"], how="outer"
    ).merge(cost_m, on=id_vars + ["year"], how="outer")

    merged["year"] = merged["year"].str.extract(r"(\d+)")
    merged = merged.dropna(subset=["year"]).copy()
    merged["year"] = merged["year"].astype(int)

    for col in ["technology", "polygon", "node", "scenario"]:
        if col in merged.columns:
            merged[col] = merged[col].astype(str).str.strip()
    if "technology" in merged.columns:
        merged["technology"] = merged["technology"].replace({"nan": "Unknown"})

    merged["Installed"] = merged["Installed"] / 1
    merged["Invested"] = merged["Invested"] / 1
    merged["Invested_Cost"] = merged["Invested_Cost"] / 1e3
    merged["Decommissioned"] = merged["Decommissioned"] / 1

    return merged


@st.cache_data
def create_color_map(technologies):
    return {tech: assign_color_by_technology(tech) for tech in technologies}

# ----------------------
# CACHED: Load geodata
# ----------------------
@st.cache_data
def load_geodata(path, poly_col):
    gdf = gpd.read_file(path).to_crs(epsg=4326)
    gdf['geometry'] = gdf['geometry'].simplify(tolerance=0.01)
    return json.loads(gdf.to_json()), gdf

# ----------------------
# Build sankey
# ----------------------
def build_sankey(region, scenario_selected, flow_data, cb_data, title_prefix, animate=True):
    """Build Sankey diagram. If animate=True, creates year animation; else shows single year (2030)."""
    import hashlib
    
    years = [2030, 2040, 2050]
    
    # Collect all nodes if animating, otherwise build on-the-fly
    if animate:
        all_nodes = set()
        for year in years:
            year_col = f"y{year}"
            df = flow_data[flow_data["scenario"] == scenario_selected].copy()
            if region != "Europe":
                df = df[df["polygon"] == region]
            df = df.groupby(["source","target"])[year_col].sum().reset_index()
            for _, row in df.iterrows():
                if row[year_col] > 0.001:
                    all_nodes.update([row["source"], row["target"]])
            
            if region != "Europe" and cb_data is not None:
                cb_df = cb_data[(cb_data["source"] == region) | (cb_data["target"] == region)]
                for _, row in cb_df.iterrows():
                    if row[year_col] > 0.001:
                        if row["target"] == region:
                            all_nodes.update([f"Import-{row['source']}", row["commodity"]])
                        else:
                            all_nodes.update([row["commodity"], f"Export-{row['target']}"])
        
        nodes = sorted(list(all_nodes))
        node_index = {name: idx for idx, name in enumerate(nodes)}
        node_colors = []
        for name in nodes:
            hash_val = int(hashlib.md5(name.encode()).hexdigest(), 16)
            node_colors.append(f'rgb({(hash_val % 180) + 75},{((hash_val >> 8) % 180) + 75},{((hash_val >> 16) % 180) + 75})')
    else:
        nodes = []
        node_index = {}
        node_colors = []
    
    def add_node(name):
        if name not in node_index:
            node_index[name] = len(nodes)
            nodes.append(name)
            hash_val = int(hashlib.md5(name.encode()).hexdigest(), 16)
            node_colors.append(f'rgb({(hash_val % 180) + 75},{((hash_val >> 8) % 180) + 75},{((hash_val >> 16) % 180) + 75})')
        return node_index[name]
    
    def build_links(year):
        year_col = f"y{year}"
        links = []
        df = flow_data[flow_data["scenario"] == scenario_selected].copy()
        if region != "Europe":
            df = df[df["polygon"] == region]
        df = df.groupby(["source","target"])[year_col].sum().reset_index()
        
        for _, row in df.iterrows():
            if row[year_col] > (0.001 if "Emission" not in title_prefix else 1000):
                s_idx = add_node(row["source"]) if not animate else node_index[row["source"]]
                t_idx = add_node(row["target"]) if not animate else node_index[row["target"]]
                links.append({"source": s_idx, "target": t_idx, "value": row[year_col]})
        
        if region != "Europe" and cb_data is not None:
            cb_df = cb_data[(cb_data["source"] == region) | (cb_data["target"] == region)]
            for _, row in cb_df.iterrows():
                if row[year_col] > 0.001:
                    if row["target"] == region:
                        s_idx = add_node(f"Import-{row['source']}") if not animate else node_index[f"Import-{row['source']}"]
                        t_idx = add_node(row["commodity"]) if not animate else node_index[row["commodity"]]
                        links.append({"source": s_idx, "target": t_idx, "value": row[year_col]})
                    else:
                        s_idx = add_node(row["commodity"]) if not animate else node_index[row["commodity"]]
                        t_idx = add_node(f"Export-{row['target']}") if not animate else node_index[f"Export-{row['target']}"]
                        links.append({"source": s_idx, "target": t_idx, "value": row[year_col]})
        return links
    
    # Build figure
    first_year = years[0]
    first_links = build_links(first_year)
    # Generate link colors AFTER nodes are added
    link_colors = [node_colors[l["source"]].replace('rgb', 'rgba').replace(')', ',0.4)') for l in first_links]
    
    fig = go.Figure(go.Sankey(
        node=dict(pad=15, thickness=20, line=dict(color="black", width=0.5), label=nodes, color=node_colors),
        link=dict(source=[l["source"] for l in first_links], target=[l["target"] for l in first_links],
                 value=[l["value"] for l in first_links], color=link_colors)
    ))
    
    if animate:
        frames = []
        for year in years:
            links = build_links(year)
            lcolors = [node_colors[l["source"]].replace('rgb', 'rgba').replace(')', ',0.4)') for l in links]
            frames.append(go.Frame(
                data=[go.Sankey(node=dict(pad=15, thickness=20, line=dict(color="black", width=0.5), label=nodes, color=node_colors),
                               link=dict(source=[l["source"] for l in links], target=[l["target"] for l in links],
                                       value=[l["value"] for l in links], color=lcolors))],
                name=str(year),
                layout=go.Layout(title_text=f"{title_prefix} - {region} - {year} - {scenario_selected}")
            ))
        
        fig.frames = frames
        fig.update_layout(
            updatemenus=[{"buttons": [
                {"args": [None, {"frame": {"duration": 1000, "redraw": True}, "fromcurrent": True, "transition": {"duration": 500}}],
                 "label": "Play", "method": "animate"},
                {"args": [[None], {"frame": {"duration": 0, "redraw": True}, "mode": "immediate", "transition": {"duration": 0}}],
                 "label": "Pause", "method": "animate"}
            ], "direction": "left", "pad": {"r": 10, "t": 87}, "type": "buttons", "x": 0.1, "y": 0}],
            sliders=[{"active": 0, "y": 0, "x": 0.1, "currentvalue": {"prefix": "Year: ", "visible": True},
                     "transition": {"duration": 500}, "pad": {"b": 10, "t": 50}, "len": 0.9,
                     "steps": [{"args": [[str(y)], {"frame": {"duration": 500, "redraw": True}, "mode": "immediate"}],
                               "label": str(y), "method": "animate"} for y in years]}]
        )
    
    fig.update_layout(title_text=f"{title_prefix} - {region} - {scenario_selected}", 
                     font_size=12, height=1200)
    return fig

# ----------------------
# Helper: download data
# ----------------------
def download_plot(fig, name):
    html_bytes = fig.to_html().encode()
    try:
        png_bytes = fig.to_image(format="png")
        st.download_button(label=f"Download {name} (PNG)", data=png_bytes,
                        file_name=f"{name}.png", mime="image/png")
    except Exception:
        st.caption("PNG export requires `kaleido`. Install it via `pip install kaleido`.")
    st.download_button(label=f"Download {name} (HTML)", data=html_bytes,
                    file_name=f"{name}.html", mime="text/html")

def main():
    st.set_page_config(page_title="Capacity Dashboard", layout="wide")

    # Define ID_VARS here so it can be passed to functions
    ID_VARS = ["unit_name", "node", "scenario", "polygon", "technology"]

    # CACHED: Load all data once
    (installed, invested, invested_cost, decommissioned, unit_to_flows, 
     energy_flows, crossborder_flows, emissions_flows, storage_dict,
     storage_installed, storage_invested, storage_cost, storage_decommissioned) = load_all_data()

    # CACHED: Preprocess data once
    merged = preprocess_data(installed, invested, invested_cost, decommissioned, unit_to_flows, ID_VARS)

    # CACHED: Preprocess storage capacity data
    storage_id_vars = [c for c in ID_VARS if c in storage_installed.columns]
    merged_storage = preprocess_storage_data(storage_installed, storage_invested, storage_cost, storage_decommissioned, storage_id_vars)

    # breakpoint()
    # Extract metadata
    scenarios = sorted(merged["scenario"].dropna().unique())
    countries = sorted(merged["polygon"].dropna().unique())
    nodes = sorted(merged["node"].dropna().unique())
    years = sorted(merged["year"].dropna().unique())

    TECH_ORDER = sorted(merged["technology"].dropna().unique())
    YEAR_ORDER = sorted(merged["year"].dropna().astype(int).unique())

    # CACHED: Create color map once
    color_map = create_color_map(TECH_ORDER)

    # Storage metadata
    s_scenarios = sorted(merged_storage["scenario"].dropna().unique()) if "scenario" in merged_storage.columns else scenarios
    s_countries = sorted(merged_storage["polygon"].dropna().unique()) if "polygon" in merged_storage.columns else countries
    s_nodes = sorted(merged_storage["node"].dropna().unique()) if "node" in merged_storage.columns else nodes
    S_TECH_ORDER = sorted(merged_storage["technology"].dropna().unique()) if "technology" in merged_storage.columns else TECH_ORDER
    s_color_map = create_color_map(S_TECH_ORDER)
    
    height_value = 700

    st.header("European Model Statistics")
    scenario = st.selectbox("Scenario", scenarios)

    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10, tab11 = st.tabs([
        # Units
        "📊 Installed Capacity",
        "🔄 Energy Production",
        "📈 Invested vs Decommissioned",
        "💰 CAPEX",
        "🗺️ Capacity Map",
        # Storage
        "🔋 Storage Analysis",
        "📊 Storage Installed Capacity",
        "📈 Storage Invested vs Decommissioned",
        "💰 Storage Investment Cost",
        # Flows
        "🌊 Sankey Diagrams",
        "🗺️ Flow Map",
    ])

    # ----------------------
    # Plot 1: Installed Capacity
    # ----------------------
    with tab1:
        st.header("Installed Capacity")
        col1, col2 = st.columns(2)
        with col1:
            selected_countries = st.multiselect("Countries", countries, default=countries, key="installed_countries")
        with col2:
            selected_node = st.selectbox("Node", nodes, key="installed_nodes")
        filtered = merged[(merged["scenario"] == scenario) & (merged["node"] == selected_node) & (merged["polygon"].isin(selected_countries))].copy()
        if filtered.empty:
            st.info("No data for the selected filters.")
        else:
            df = filtered.rename(columns={"Installed": "Capacity (GW)"}).copy()
            df["year"] = df["year"].astype(int)
            present_tech = (df.loc[df["Capacity (GW)"] > 0.001, "technology"].dropna().unique().tolist())
            if not present_tech:
                st.info("No technologies with installed capacity for the selected filters.")
                st.stop()
            TECH_ORDER_NODE = [t for t in TECH_ORDER if t in present_tech]
            df["technology"] = pd.Categorical(df["technology"], categories=TECH_ORDER_NODE, ordered=True)
            POLY_ORDER = sorted(sorted(df["polygon"].dropna().unique()), key=lambda x: (x != "Europe", x))
            full_idx = pd.MultiIndex.from_product([POLY_ORDER, TECH_ORDER_NODE, YEAR_ORDER],names=["polygon", "technology", "year"])
            agg_installed = (df.pivot_table(index=["polygon", "technology", "year"],values="Capacity (GW)",aggfunc="sum",observed=False).reindex(full_idx, fill_value=0).reset_index() )
            agg_installed["polygon"] = pd.Categorical(agg_installed["polygon"], categories=POLY_ORDER, ordered=True)
            agg_installed["technology"] = pd.Categorical(agg_installed["technology"], categories=TECH_ORDER, ordered=True)
            agg_installed["year"] = pd.Categorical(agg_installed["year"], categories=YEAR_ORDER, ordered=True)
            agg_installed["anim_id"] = agg_installed["polygon"].astype(str) + " | " + agg_installed["technology"].astype(str)
            fig_installed = px.bar(agg_installed,x="polygon",y="Capacity (GW)",color="technology",animation_frame="year",animation_group="anim_id", color_discrete_map=color_map,barmode="stack",category_orders={"polygon": POLY_ORDER,"technology": TECH_ORDER_NODE,"year": YEAR_ORDER,},title=f"Installed Capacity by Country ({scenario})")
            fig_installed.update_layout(height=height_value, bargap=0.15,template="plotly_white",legend_title_text="Technology",yaxis_title=("Capacity (GW)" if selected_node not in ["CO2","emission", "cement", "steel","glass","chemicals","ammonia"] else ("CO2 kton/h" if selected_node not in ["cement", "steel","glass","chemicals","ammonia"] else "kton/h")))
            year_totals = agg_installed.pivot_table(index=["year", "polygon"], values="Capacity (GW)", aggfunc="sum", observed=False)
            year_max = year_totals.groupby("year", observed=False).max()
            for frame in fig_installed.frames:
                year_val = int(frame.name)
                y_max = year_max.loc[year_val, "Capacity (GW)"]
                y_padding = y_max * 0.05
                frame.layout.update(yaxis={"range": [0, y_max + y_padding]})
            for slider_step, frame in zip(fig_installed.layout.sliders[0].steps, fig_installed.frames):
                slider_step["args"][1]["frame"]["redraw"] = True
            st.plotly_chart(fig_installed, width="stretch")
            download_plot(fig_installed, "installed_capacity")



    # ----------------------
    # Plot 2: Unit to Flows
    # ----------------------
    with tab2:
        st.header("Energy Production")
        col1, col2 = st.columns(2)
        with col1:
            selected_countries_f = st.multiselect("Countries", ["Europe"] + countries, default=countries, key="flows_countries")
        with col2:
            selected_node_f = st.selectbox("Node", nodes, key="flows_nodes")
        filtered = merged[(merged["scenario"] == scenario) & (merged["node"] == selected_node_f) & (merged["polygon"].isin(selected_countries_f))].copy()

        if filtered.empty:
            st.info("No data for the selected filters.")
        else:
            df = filtered.rename(columns={"UnitFlows": "Flows (TWh)"}).copy()
            POLY_ORDER = sorted(sorted(df["polygon"].dropna().unique()), key=lambda x: (x != "Europe", x))
            df["year"] = df["year"].astype(int)
            present_tech = (df.loc[df["Flows (TWh)"] > 0.001, "technology"].dropna().unique().tolist())
            if not present_tech:
                st.info("No technologies with installed capacity for the selected filters.")
                st.stop()
            TECH_ORDER_NODE = [t for t in TECH_ORDER if t in present_tech]
            df["technology"] = pd.Categorical(df["technology"], categories=TECH_ORDER_NODE, ordered=True)
            full_idx = pd.MultiIndex.from_product([POLY_ORDER, TECH_ORDER, YEAR_ORDER],names=["polygon", "technology", "year"])
            # create those rows that do not exist
            agg_flows = (df.pivot_table(index=["polygon", "technology", "year"],values="Flows (TWh)",aggfunc="sum",observed=False).reindex(full_idx, fill_value=0).reset_index())
            agg_flows["polygon"] = pd.Categorical(agg_flows["polygon"], categories=POLY_ORDER, ordered=True)
            agg_flows["technology"] = pd.Categorical(agg_flows["technology"], categories=TECH_ORDER_NODE, ordered=True)
            agg_flows["year"] = pd.Categorical(agg_flows["year"], categories=YEAR_ORDER, ordered=True)
            agg_flows["anim_id"] = (agg_flows["polygon"].astype(str) + " | " + agg_flows["technology"].astype(str))
            fig_flows = px.bar(agg_flows,x="polygon",y="Flows (TWh)",color="technology",animation_frame="year",animation_group="anim_id",color_discrete_map=color_map,barmode="stack",category_orders={"polygon": POLY_ORDER,"technology": TECH_ORDER_NODE,"year": YEAR_ORDER,},title=f"Energy Production by Country ({scenario})")
            fig_flows.update_layout(height=height_value,bargap=0.15,template="plotly_white",legend_title_text="Technology",yaxis_title=("Flows (TWh)" if selected_node_f not in ["CO2","emission", "cement", "steel","glass","chemicals","ammonia"] else ("CO2 Mton" if selected_node_f not in ["cement", "steel","glass","chemicals","ammonia"] else "Mton")))
            year_totals = agg_flows.pivot_table(index=["year", "polygon"], values="Flows (TWh)", aggfunc="sum", observed=False)
            year_max = year_totals.groupby("year", observed=False).max()
            for frame in fig_flows.frames:
                year_val = int(frame.name)
                y_max = year_max.loc[year_val, "Flows (TWh)"]
                y_padding = y_max * 0.05
                frame.layout.update(yaxis={"range": [0, y_max + y_padding]})
            for slider_step, frame in zip(fig_flows.layout.sliders[0].steps, fig_flows.frames):
                slider_step["args"][1]["frame"]["redraw"] = True
            st.plotly_chart(fig_flows, width="stretch")
            download_plot(fig_flows, "energy_production")

                
    # ----------------------
    # Plot 3: Invested vs Decommissioned
    # ----------------------
    with tab3:
        st.header("Invested vs Decommissioned (by Technology)")
        col1, col2 = st.columns(2)
        with col1:
            selected_countries_id = st.multiselect("Countries", countries, default=countries, key="invested_countries")
        with col2:
            selected_node_id = st.selectbox("Node", nodes, key="invested_nodes")
        filtered = merged[(merged["scenario"] == scenario) & (merged["node"] == selected_node_id) & (merged["polygon"].isin(selected_countries_id))].copy()
        if filtered.empty:
            st.info("No data for the selected filters.")
        else:
            df = filtered[["polygon", "technology", "year", "Invested", "Decommissioned"]].copy()
            df["year"] = df["year"].astype(int)
            present_tech = (df.loc[(df["Invested"] > 0.001)|(df["Decommissioned"] > 0.001), "technology"].dropna().unique().tolist())
            if not present_tech:
                st.info("No technologies with installed capacity for the selected filters.")
                st.stop()
            TECH_ORDER_NODE = [t for t in TECH_ORDER if t in present_tech]
            df["technology"] = pd.Categorical(df["technology"], categories=TECH_ORDER_NODE, ordered=True)
            POLY_ORDER = sorted(sorted(df["polygon"].dropna().unique()), key=lambda x: (x != "Europe", x))
            full_idx = pd.MultiIndex.from_product([POLY_ORDER, TECH_ORDER, YEAR_ORDER],names=["polygon", "technology", "year"])
            inv = (df.pivot_table(index=["polygon", "technology", "year"],values="Invested",aggfunc="sum",observed=False).reindex(full_idx, fill_value=0).reset_index().rename(columns={"Invested": "Value"}).assign(kind="Invested"))
            dec = (df.pivot_table(index=["polygon", "technology", "year"],values="Decommissioned",aggfunc="sum",observed=False).reindex(full_idx, fill_value=0).reset_index().rename(columns={"Decommissioned": "Value"}).assign(kind="Decommissioned"))
            dec["Value"] = -dec["Value"]
            combined = pd.concat([inv, dec], ignore_index=True)
            combined["polygon"] = pd.Categorical(combined["polygon"], categories=POLY_ORDER, ordered=True)
            combined["technology"] = pd.Categorical(combined["technology"], categories=TECH_ORDER_NODE, ordered=True)
            combined["year"] = pd.Categorical(combined["year"], categories=YEAR_ORDER, ordered=True)
            combined["anim_id"] = combined["polygon"].astype(str) + " | " + combined["technology"].astype(str)
            fig_change = px.bar(combined,x="polygon",y="Value",color="technology",animation_frame="year",animation_group="anim_id",barmode="relative",pattern_shape="kind",color_discrete_map=color_map,category_orders={"polygon": POLY_ORDER,"technology": TECH_ORDER_NODE,"year": YEAR_ORDER,},title=f"Invested (+) vs Decommissioned (–) by Country ({scenario})")
            fig_change.update_layout(template="plotly_white",height=height_value,bargap=0.20,legend_title_text="Technology",yaxis_title=("Capacity (GW)" if selected_node_id not in ["CO2","emission", "cement", "steel","glass","chemicals","ammonia"] else ("CO2 kton/h" if selected_node_id not in ["cement", "steel","glass","chemicals","ammonia"] else "kton/h")),xaxis_title="Country")
            
            year_ranges = []
            for year_val in YEAR_ORDER:
                year_data = combined[combined["year"] == year_val].copy()
                pos_stack = year_data[year_data["Value"] > 0].pivot_table(index="polygon", values="Value", aggfunc="sum", observed=False).fillna(0)
                neg_stack = year_data[year_data["Value"] < 0].pivot_table(index="polygon", values="Value", aggfunc="sum", observed=False).fillna(0)
                y_max_val = pos_stack["Value"].max() if len(pos_stack) > 0 else 0
                y_min_val = neg_stack["Value"].min() if len(neg_stack) > 0 else 0
                year_ranges.append((year_val, y_min_val, y_max_val))
            year_ranges_dict = {yr: (mn, mx) for yr, mn, mx in year_ranges}
            for frame in fig_change.frames:
                year_val = int(frame.name)
                y_min_val, y_max_val = year_ranges_dict[year_val]
                y_range = y_max_val - y_min_val
                y_padding = max(y_range * 0.05, 0.1)
                frame.layout.update(yaxis={"range": [y_min_val - y_padding, y_max_val + y_padding], "autorange": False})
            for slider_step, frame in zip(fig_change.layout.sliders[0].steps, fig_change.frames):
                slider_step["args"][1]["frame"]["redraw"] = True
            st.plotly_chart(fig_change, width="stretch")
            download_plot(fig_change, "investment_decommission")

        # ----------------------
    # Plot 4: Invesment Cost
    # ----------------------
    with tab4:
        st.header("Investment Cost")
        col1, col2 = st.columns(2)
        with col1:
            selected_countries = st.multiselect("Countries", countries, default=countries, key="investment_cost_countries")
        with col2:
            selected_node = st.selectbox("Node", nodes, key="investment_cost_nodes")
        filtered = merged[(merged["scenario"] == scenario) & (merged["node"] == selected_node) & (merged["polygon"].isin(selected_countries))].copy()
        if filtered.empty:
            st.info("No data for the selected filters.")
        else:
            df = filtered.rename(columns={"Invested_Cost": "Investment Cost (B€)"}).copy()
            df["year"] = df["year"].astype(int)

            # Technologies present (based on positive investment)
            present_tech = (df.loc[df["Investment Cost (B€)"] > 0.001, "technology"].dropna().unique().tolist())
            if not present_tech:
                st.info("No technologies with investment cost for the selected filters.")
                st.stop()
            TECH_ORDER_NODE = [t for t in TECH_ORDER if t in present_tech]
            df["technology"] = pd.Categorical(df["technology"], categories=TECH_ORDER_NODE, ordered=True)
            POLY_ORDER = sorted(sorted(df["polygon"].dropna().unique()), key=lambda x: (x != "Europe", x))
            df["polygon"] = pd.Categorical(df["polygon"], categories=POLY_ORDER, ordered=True)
            full_idx = pd.MultiIndex.from_product([POLY_ORDER, TECH_ORDER_NODE], names=["polygon", "technology"])
            agg_inv = (df.pivot_table(index=["polygon", "technology"],values="Investment Cost (B€)",aggfunc="sum",observed=False, ).reindex(full_idx, fill_value=0.0).reset_index())
            fig_inv = px.bar(agg_inv,x="polygon",y="Investment Cost (B€)",color="technology",color_discrete_map=color_map,barmode="stack",category_orders={"polygon": POLY_ORDER, "technology": TECH_ORDER_NODE},title=f"Investment Cost from 2030 to 2060 by Country ({scenario})")
            fig_inv.update_layout(height=height_value,bargap=0.15,template="plotly_white",legend_title_text="Technology",yaxis_title="Investment Cost (B€)",)
            y_max = agg_inv.groupby("polygon", observed=False)["Investment Cost (B€)"].sum().max()
            if pd.isna(y_max):
                y_max = 0
            y_pad = y_max * 0.05 if y_max > 0 else 1.0
            fig_inv.update_yaxes(range=[0, y_max + y_pad])
            st.plotly_chart(fig_inv, width="stretch")
            download_plot(fig_inv, "investment_cost_by_country_all_years")

    # ----------------------------
    # Plot 5: Installed Capacity Map
    # ----------------------------

    with tab5:
        st.header("Installed Capacity Map Comparison")
        POLY_COL = "id"
        geojson_obj, gdf_base = load_geodata("config/IC1.geojson", POLY_COL)
        map_tech = st.selectbox("Technology", TECH_ORDER)  # no "All Technologies"

        df_cap = merged[(merged["scenario"] == scenario) & (merged["technology"] == map_tech)].copy()

        if df_cap.empty:
            st.info("No data for the selected filters / technology.")
        else:
            all_polygons = gdf_base[POLY_COL].astype(str).tolist()

            df_cap["year"] = df_cap["year"].astype(int)
            cap_by_poly_year = (df_cap.pivot_table(index=["polygon", "year"],values="Installed",aggfunc="sum",observed=False).reindex(pd.MultiIndex.from_product([all_polygons, YEAR_ORDER],names=["polygon", "year"]),fill_value=0).reset_index().rename(columns={"Installed": "Capacity (GW)"}))

            gdf_plot_long = gdf_base[[POLY_COL, "geometry"]].merge(cap_by_poly_year, left_on=POLY_COL, right_on="polygon", how="left")
            max_cap = float(gdf_plot_long["Capacity (GW)"].round(3).max())

            gdf_plot_long["year"] = pd.Categorical(gdf_plot_long["year"], categories=YEAR_ORDER, ordered=True)

            fig_map = px.choropleth(gdf_plot_long,geojson=geojson_obj,locations=POLY_COL,featureidkey=f"properties.{POLY_COL}",color="Capacity (GW)",animation_frame="year",color_continuous_scale="Cividis",range_color=(0, max_cap),hover_name=POLY_COL,hover_data={"Capacity (GW)": ":.2f"},projection="natural earth",title=f"Installed Capacity – {map_tech} ({scenario})")

            fig_map.update_geos(fitbounds="locations", visible=True, showframe=True, showcoastlines=True, showcountries=True,showocean=True, oceancolor="#1b2a34", showland=True, landcolor="#243647",lataxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.08)", dtick=5),lonaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.08)", dtick=5))
            fig_map.update_layout(uirevision="static")
            st.plotly_chart(fig_map, width="stretch")
        
    # ----------------------
    # Plot 6: Storage
    # ----------------------
    with tab6:
        st.header("Node State by Storage Type and Country")
        scenario_storage = scenario
        df_storage = storage_dict[scenario_storage].copy()
        storage_types = sorted({c.split("_")[0] for c in df_storage.columns})
        col1, col2 = st.columns(2)
        with col1:
            selected_storage_type = st.selectbox("Storage Type", storage_types, index=0)
        with col2:
            selected_countries_storage = st.multiselect("Countries", countries, default="Europe")
        cols_to_plot = []
        for c in df_storage.columns:
            if "Europe" not in selected_countries_storage:
                if c.startswith(selected_storage_type) and (c.split("_")[1] in selected_countries_storage if len(c.split("_"))>1 else True):
                    cols_to_plot.append(c)
            else:
                if c.startswith(selected_storage_type):
                    cols_to_plot.append(c)
        filtered_storage = df_storage[cols_to_plot] if cols_to_plot else df_storage.iloc[:, 0:0]
        if filtered_storage.empty:
            st.info("No data for selected filters.")
        else:
            df_long = (filtered_storage.reset_index().rename(columns={"index": "Time"}).melt(id_vars="Time", var_name="series", value_name="Energy (MWh)"))
            df_long["year"] = df_long["Time"].dt.year.astype(int)
            if 2041 in df_long["year"].unique():
                df_long.loc[df_long["year"]==2041,"year"] = 2040
            parts = df_long["series"].astype(str).str.partition("_")  # returns cols [0, 1, 2]
            df_long["Storage_Country"] = parts[0] + np.where(parts[1] == "", "", "_" + parts[2])
            df_long["year"] = pd.Categorical(df_long["year"], categories=YEAR_ORDER, ordered=True)

            fig_storage = px.line(df_long,x="Time",y="Energy (MWh)", color="Storage_Country",animation_frame="year",animation_group="Storage_Country",render_mode="webgl",title=f"Node State for {selected_storage_type} in {', '.join(selected_countries_storage)} ({scenario_storage})",)
            fig_storage.update_traces(connectgaps=True)
            fig_storage.update_layout(xaxis_title="Time",yaxis_title=("Energy (MWh)" if selected_storage_type not in ["CO2","atmosphere"] else "CO2 tons"),template="plotly_white",height=600,legend_title_text="Storage_Country",uirevision="static",)
            for frame in fig_storage.frames:
                year_val = int(frame.name)
                year_data = df_long[df_long["year"] == year_val]
                if not year_data.empty:
                    x_min = year_data["Time"].min()
                    x_max = year_data["Time"].max()
                    y_min = year_data["Energy (MWh)"].min()
                    y_max = year_data["Energy (MWh)"].max()
                    # Add some padding to y-axis (5%)
                    y_padding = (y_max - y_min) * 0.05
                    frame.layout.update(xaxis={"range": [x_min, x_max]},yaxis={"range": [y_min - y_padding, y_max + y_padding]})

            st.plotly_chart(fig_storage, width="stretch")
            download_plot(fig_storage, "storage_state_anim")

    # -------------------------------
    # Sankey Diagrams
    # -------------------------------
    with tab10:
        st.header("Sankey Diagrams")  # noqa

        col1, col2= st.columns(2)
        with col1: 
            region_option = st.selectbox("Region for Sankey", countries, key="sankey_regions")
        with col2:
            sankey_type = st.selectbox("Sankey Type", ["Energy Flows", "Emissions Flows"], key="sankey_type")

        if sankey_type == "Energy Flows":
            sankey_fig = build_sankey(region_option, scenario, 
                                    energy_flows, crossborder_flows, "Energy Flows Sankey")
        else:
            sankey_fig = build_sankey(region_option, scenario, 
                                    emissions_flows, None, "Emissions Flows Sankey")
        
        st.plotly_chart(sankey_fig, width="stretch")

        html_bytes = sankey_fig.to_html().encode()
        st.download_button(label="Download Sankey (HTML)", data=html_bytes,
                        file_name=f"sankey_{sankey_type.replace(' ', '_')}_{region_option}_{scenario}.html", 
                        mime="text/html")
        try:
            png_bytes = sankey_fig.to_image(format="png")
            st.download_button(label="Download Sankey (PNG)", data=png_bytes,
                            file_name=f"sankey_{sankey_type.replace(' ', '_')}_{region_option}_{scenario}.png", 
                            mime="image/png")
        except Exception:
            st.caption("PNG export requires `kaleido`. Install it via `pip install kaleido`.")

    
    # -------------------------------------------------
    # Flow Map (Cross-border flows)
    # -------------------------------------------------
    with tab11:
        st.header("Flow Map (Cross-border)")  # noqa
        POLY_COL = "id"
        geojson_obj, gdf_base = load_geodata("config/IC1.geojson", POLY_COL)
        if crossborder_flows.empty: st.info("No cross-border flow data loaded."); st.stop()

        # Commodity (node) selection
        commodities = sorted(crossborder_flows["commodity"].astype(str).dropna().unique())
        selected_commodity = st.selectbox("Node (commodity)", commodities, index=0)

        # Years (y2030, y2040, ...)
        year_cols = [c for c in crossborder_flows.columns if isinstance(c, str) and c.startswith("y") and c[1:].isdigit()]
        years = sorted([int(c[1:]) for c in year_cols])
        if not years: st.info("No year columns (e.g., y2030, y2040) found in crossborder_flows."); st.stop()

        # Filter by scenario + commodity, keep only countries present in GeoJSON
        df = crossborder_flows[(crossborder_flows["scenario"] == scenario) & (crossborder_flows["commodity"].astype(str) == selected_commodity)].copy()
        gdf_ll = gdf_base.to_crs(epsg=4326); rep_pts = gdf_ll.representative_point()
        centroids = {str(row.id): (pt.x, pt.y) for row, pt in zip(gdf_ll.itertuples(index=False), rep_pts)}
        df = df[df["source"].astype(str).isin(centroids.keys()) & df["target"].astype(str).isin(centroids.keys())]
        if df.empty: st.info("Countries in flows not found in provided GeoJSON (id codes must match)."); st.stop()

        # Focus map to represented countries
        used = sorted(set(df["source"].astype(str)) | set(df["target"].astype(str)))
        lons = [centroids[c][0] for c in used]; lats = [centroids[c][1] for c in used]
        lon_min, lon_max, lat_min, lat_max = min(lons), max(lons), min(lats), max(lats)
        lon_pad, lat_pad = max(1.0, (lon_max - lon_min) * 0.15), max(1.0, (lat_max - lat_min) * 0.15)
        lon_range, lat_range = [lon_min - lon_pad, lon_max + lon_pad], [lat_min - lat_pad, lat_max + lat_pad]

        # Build flows per unordered pair for all years: flows[(A,B)][y] = (A->B, B->A)
        flows = {}
        for row in df.itertuples(index=False):
            A, B = str(row.source), str(row.target); key = tuple(sorted((A, B)))
            if key not in flows: flows[key] = {}
            for y in years:
                v = float(getattr(row, f"y{y}", 0.0))
                ab = flows[key].get(y, (0.0, 0.0))
                flows[key][y] = (ab[0] + v, ab[1]) if row.source == key[0] else (ab[0], ab[1] + v)

        # Absolute colorscale (same for all frames)
        CS = px.colors.sequential.Viridis
        abs_max = float(df[year_cols].to_numpy().max()) if len(df) else 0.0
        if abs_max <= 0: st.info("All flows are zero for this selection."); st.stop()
        cmin, cmax = 0.0, abs_max

        def color_for(val: float) -> str:
            t = 0.0 if cmax <= 1e-12 else min(1.0, max(0.0, val / cmax))
            return sample_colorscale(CS, t)[0]  # hex string

        CONST_WIDTH = 10  # imposed line width (px), not user-controlled
        LABEL_SIZE = 20  # larger direction labels

        # Helper: add one half-segment (start->end) + large direction label
        def add_half(traces: list, name_from: str, name_to: str, lon_s: float, lat_s: float, lon_e: float, lat_e: float, value: float):
            if value <= 1e-12: return
            color = color_for(value)
            # half-segment line
            traces.append(go.Scattergeo(lon=[lon_s, lon_e], lat=[lat_s, lat_e], mode="lines",
                                        line=dict(color=color, width=CONST_WIDTH), opacity=0.95,
                                        hoverinfo="text", text=f"{name_from} → {name_to} – {selected_commodity}: {value:.2f}"))
            # direction label positioned at 60% along the segment
            lx = lon_s + 0.60 * (lon_e - lon_s); ly = lat_s + 0.60 * (lat_e - lat_s)
            traces.append(go.Scattergeo(lon=[lx], lat=[ly], mode="text", text=[f"{name_from}→{name_to}"],
                                        textfont=dict(color="#111827", size=LABEL_SIZE, family="Arial"), hoverinfo="skip", showlegend=False))

        # ---------- Initial frame ----------
        first_year = years[0]
        traces_first = []
        for (A, B), vals in flows.items():
            lon_A, lat_A = centroids[A]; lon_B, lat_B = centroids[B]
            lon_M, lat_M = (lon_A + lon_B) / 2.0, (lat_A + lat_B) / 2.0
            v_AB, v_BA = vals.get(first_year, (0.0, 0.0))
            # B -> A displayed on A→M
            add_half(traces_first, B, A, lon_A, lat_A, lon_M, lat_M, v_BA)
            # A -> B displayed on M→B
            add_half(traces_first, A, B, lon_M, lat_M, lon_B, lat_B, v_AB)
        fig = go.Figure(data=traces_first)

        # ---------- Animation frames ----------
        frames = []
        for y in years:
            frame_traces = []
            for (A, B), vals in flows.items():
                lon_A, lat_A = centroids[A]; lon_B, lat_B = centroids[B]
                lon_M, lat_M = (lon_A + lon_B) / 2.0, (lat_A + lat_B) / 2.0
                v_AB, v_BA = vals.get(y, (0.0, 0.0))
                add_half(frame_traces, B, A, lon_A, lat_A, lon_M, lat_M, v_BA)
                add_half(frame_traces, A, B, lon_M, lat_M, lon_B, lat_B, v_AB)
            frames.append(go.Frame(data=frame_traces, name=str(y)))
        fig.frames = frames

        # Map & UI (compact one-liners)
        fig.update_geos(projection_type="natural earth", showcoastlines=True, showcountries=True, showocean=True, oceancolor="#1b2a34", showland=True, landcolor="#243647", lonaxis=dict(range=lon_range), lataxis=dict(range=lat_range))
        fig.add_trace(go.Scattergeo(lon=[None], lat=[None], mode="markers", marker=dict(size=0.1, color=[0], colorscale=CS, cmin=cmin, cmax=cmax, colorbar=dict(title=f"{selected_commodity} flow", len=0.4)), showlegend=False, hoverinfo="skip"))
        fig.update_layout(title_text=f"Cross-border Flows – {selected_commodity} – {scenario}", height=700, showlegend=False, template="plotly_white", uirevision="static", updatemenus=[{"type":"buttons","direction":"left","x":0.1,"y":0,"pad":{"r":10,"t":87},"buttons":[{"label":"Play","method":"animate","args":[None,{"frame":{"duration":800,"redraw":True},"fromcurrent":True,"transition":{"duration":300}}]},{"label":"Pause","method":"animate","args":[[None],{"frame":{"duration":0,"redraw":True},"mode":"immediate","transition":{"duration":0}}]}]}], sliders=[{"active":0,"y":0,"x":0.1,"len":0.9,"currentvalue":{"prefix":"Year: ","visible":True},"transition":{"duration":300},"steps":[{"label":str(y),"method":"animate","args":[[str(y)],{"mode":"immediate","frame":{"duration":300,"redraw":True}}]} for y in years]}])

        st.plotly_chart(fig, width="stretch")
        download_plot(fig, f"flow_map_{selected_commodity}_colormap_abs_labels")


    # ----------------------
    # Plot 9: Storage Installed Capacity
    # ----------------------
    with tab7:
        st.header("Storage Installed Capacity")
        col1, col2 = st.columns(2)
        with col1:
            s_sel_countries_inst = st.multiselect("Countries", s_countries, default=s_countries, key="s_installed_countries")
        with col2:
            s_sel_node_inst = st.selectbox("Node", s_nodes, key="s_installed_nodes") if s_nodes else None
        filtered_s = merged_storage[
            (merged_storage["scenario"] == scenario) &
            (merged_storage["polygon"].isin(s_sel_countries_inst))
        ].copy()
        if s_sel_node_inst and "node" in filtered_s.columns:
            filtered_s = filtered_s[filtered_s["node"] == s_sel_node_inst]
        if filtered_s.empty:
            st.info("No data for the selected filters.")
        else:
            df_s = filtered_s.rename(columns={"Installed": "Capacity (GWh)"}).copy()
            df_s["year"] = df_s["year"].astype(int)
            present_tech_s = df_s.loc[df_s["Capacity (GWh)"] > 0.001, "technology"].dropna().unique().tolist() if "technology" in df_s.columns else []
            if not present_tech_s:
                st.info("No technologies with installed capacity for the selected filters.")
            else:
                S_TECH_ORDER_NODE = [t for t in S_TECH_ORDER if t in present_tech_s]
                df_s["technology"] = pd.Categorical(df_s["technology"], categories=S_TECH_ORDER_NODE, ordered=True)
                S_POLY_ORDER = sorted(df_s["polygon"].dropna().unique(), key=lambda x: (x != "Europe", x))
                full_idx_s = pd.MultiIndex.from_product([S_POLY_ORDER, S_TECH_ORDER_NODE, YEAR_ORDER], names=["polygon", "technology", "year"])
                agg_s = (df_s.pivot_table(index=["polygon", "technology", "year"], values="Capacity (GWh)", aggfunc="sum", observed=False)
                         .reindex(full_idx_s, fill_value=0).reset_index())
                agg_s["polygon"] = pd.Categorical(agg_s["polygon"], categories=S_POLY_ORDER, ordered=True)
                agg_s["technology"] = pd.Categorical(agg_s["technology"], categories=S_TECH_ORDER_NODE, ordered=True)
                agg_s["year"] = pd.Categorical(agg_s["year"], categories=YEAR_ORDER, ordered=True)
                agg_s["anim_id"] = agg_s["polygon"].astype(str) + " | " + agg_s["technology"].astype(str)
                fig_s_inst = px.bar(agg_s, x="polygon", y="Capacity (GWh)", color="technology",
                                    animation_frame="year", animation_group="anim_id",
                                    color_discrete_map=s_color_map, barmode="stack",
                                    category_orders={"polygon": S_POLY_ORDER, "technology": S_TECH_ORDER_NODE, "year": YEAR_ORDER},
                                    title=f"Storage Installed Capacity by Country ({scenario})")
                fig_s_inst.update_layout(height=height_value, bargap=0.15, template="plotly_white",
                                         legend_title_text="Technology", yaxis_title="Capacity (GWh)")
                year_totals_s = agg_s.pivot_table(index=["year", "polygon"], values="Capacity (GWh)", aggfunc="sum", observed=False)
                year_max_s = year_totals_s.groupby("year", observed=False).max()
                for frame in fig_s_inst.frames:
                    year_val = int(frame.name)
                    y_max_v = year_max_s.loc[year_val, "Capacity (GWh)"]
                    frame.layout.update(yaxis={"range": [0, y_max_v * 1.05]})
                for slider_step, frame in zip(fig_s_inst.layout.sliders[0].steps, fig_s_inst.frames):
                    slider_step["args"][1]["frame"]["redraw"] = True
                st.plotly_chart(fig_s_inst, width="stretch")
                download_plot(fig_s_inst, "storage_installed_capacity")

    # ----------------------
    # Plot 10: Storage Invested Capacity
    # ----------------------
    with tab8:
        st.header("Storage Invested vs Decommissioned (by Technology)")
        col1, col2 = st.columns(2)
        with col1:
            s_sel_countries_inv = st.multiselect("Countries", s_countries, default=s_countries, key="s_invested_countries")
        with col2:
            s_sel_node_inv = st.selectbox("Node", s_nodes, key="s_invested_nodes") if s_nodes else None
        filtered_s2 = merged_storage[
            (merged_storage["scenario"] == scenario) &
            (merged_storage["polygon"].isin(s_sel_countries_inv))
        ].copy()
        if s_sel_node_inv and "node" in filtered_s2.columns:
            filtered_s2 = filtered_s2[filtered_s2["node"] == s_sel_node_inv]
        if filtered_s2.empty:
            st.info("No data for the selected filters.")
        else:
            df_s2 = filtered_s2[["polygon", "technology", "year", "Invested", "Decommissioned"]].copy()
            df_s2["year"] = df_s2["year"].astype(int)
            present_tech_s2 = df_s2.loc[(df_s2["Invested"] > 0.001) | (df_s2["Decommissioned"] > 0.001), "technology"].dropna().unique().tolist()
            if not present_tech_s2:
                st.info("No technologies with invested/decommissioned capacity for the selected filters.")
            else:
                S_TECH_ORDER_NODE2 = [t for t in S_TECH_ORDER if t in present_tech_s2]
                df_s2["technology"] = pd.Categorical(df_s2["technology"], categories=S_TECH_ORDER_NODE2, ordered=True)
                S_POLY_ORDER2 = sorted(df_s2["polygon"].dropna().unique(), key=lambda x: (x != "Europe", x))
                full_idx_s2 = pd.MultiIndex.from_product([S_POLY_ORDER2, S_TECH_ORDER_NODE2, YEAR_ORDER], names=["polygon", "technology", "year"])
                inv_s = (df_s2.pivot_table(index=["polygon", "technology", "year"], values="Invested", aggfunc="sum", observed=False)
                         .reindex(full_idx_s2, fill_value=0).reset_index().rename(columns={"Invested": "Value"}).assign(kind="Invested"))
                dec_s = (df_s2.pivot_table(index=["polygon", "technology", "year"], values="Decommissioned", aggfunc="sum", observed=False)
                         .reindex(full_idx_s2, fill_value=0).reset_index().rename(columns={"Decommissioned": "Value"}).assign(kind="Decommissioned"))
                dec_s["Value"] = -dec_s["Value"]
                combined_s = pd.concat([inv_s, dec_s], ignore_index=True)
                combined_s["polygon"] = pd.Categorical(combined_s["polygon"], categories=S_POLY_ORDER2, ordered=True)
                combined_s["technology"] = pd.Categorical(combined_s["technology"], categories=S_TECH_ORDER_NODE2, ordered=True)
                combined_s["year"] = pd.Categorical(combined_s["year"], categories=YEAR_ORDER, ordered=True)
                combined_s["anim_id"] = combined_s["polygon"].astype(str) + " | " + combined_s["technology"].astype(str)
                fig_s_inv = px.bar(combined_s, x="polygon", y="Value", color="technology",
                                   animation_frame="year", animation_group="anim_id",
                                   barmode="relative", pattern_shape="kind",
                                   color_discrete_map=s_color_map,
                                   category_orders={"polygon": S_POLY_ORDER2, "technology": S_TECH_ORDER_NODE2, "year": YEAR_ORDER},
                                   title=f"Storage Invested (+) vs Decommissioned (–) by Country ({scenario})")
                fig_s_inv.update_layout(template="plotly_white", height=height_value, bargap=0.20,
                                        legend_title_text="Technology", yaxis_title="Capacity (GWh)", xaxis_title="Country")
                year_ranges_s = []
                for year_val in YEAR_ORDER:
                    year_data_s = combined_s[combined_s["year"] == year_val].copy()
                    pos_s = year_data_s[year_data_s["Value"] > 0].pivot_table(index="polygon", values="Value", aggfunc="sum", observed=False).fillna(0)
                    neg_s = year_data_s[year_data_s["Value"] < 0].pivot_table(index="polygon", values="Value", aggfunc="sum", observed=False).fillna(0)
                    y_max_s = pos_s["Value"].max() if len(pos_s) > 0 else 0
                    y_min_s = neg_s["Value"].min() if len(neg_s) > 0 else 0
                    year_ranges_s.append((year_val, y_min_s, y_max_s))
                year_ranges_dict_s = {yr: (mn, mx) for yr, mn, mx in year_ranges_s}
                for frame in fig_s_inv.frames:
                    year_val = int(frame.name)
                    y_min_v, y_max_v = year_ranges_dict_s[year_val]
                    y_range_v = y_max_v - y_min_v
                    y_padding_v = max(y_range_v * 0.05, 0.1)
                    frame.layout.update(yaxis={"range": [y_min_v - y_padding_v, y_max_v + y_padding_v], "autorange": False})
                for slider_step, frame in zip(fig_s_inv.layout.sliders[0].steps, fig_s_inv.frames):
                    slider_step["args"][1]["frame"]["redraw"] = True
                st.plotly_chart(fig_s_inv, width="stretch")
                download_plot(fig_s_inv, "storage_invested_decommissioned")

    # ----------------------
    # Plot 9: Storage Investment Cost
    # ----------------------
    with tab9:
        st.header("Storage Investment Cost")
        col1, col2 = st.columns(2)
        with col1:
            s_sel_countries_cost = st.multiselect("Countries", s_countries, default=s_countries, key="s_cost_countries")
        with col2:
            s_sel_node_cost = st.selectbox("Node", s_nodes, key="s_cost_nodes") if s_nodes else None
        filtered_s4 = merged_storage[
            (merged_storage["scenario"] == scenario) &
            (merged_storage["polygon"].isin(s_sel_countries_cost))
        ].copy()
        if s_sel_node_cost and "node" in filtered_s4.columns:
            filtered_s4 = filtered_s4[filtered_s4["node"] == s_sel_node_cost]
        if filtered_s4.empty:
            st.info("No data for the selected filters.")
        else:
            df_s4 = filtered_s4.rename(columns={"Invested_Cost": "Investment Cost (B€)"}).copy()
            df_s4["year"] = df_s4["year"].astype(int)
            present_tech_s4 = df_s4.loc[df_s4["Investment Cost (B€)"] > 0.001, "technology"].dropna().unique().tolist() if "technology" in df_s4.columns else []
            if not present_tech_s4:
                st.info("No technologies with investment cost for the selected filters.")
            else:
                S_TECH_ORDER_NODE4 = [t for t in S_TECH_ORDER if t in present_tech_s4]
                df_s4["technology"] = pd.Categorical(df_s4["technology"], categories=S_TECH_ORDER_NODE4, ordered=True)
                S_POLY_ORDER4 = sorted(df_s4["polygon"].dropna().unique(), key=lambda x: (x != "Europe", x))
                full_idx_s4 = pd.MultiIndex.from_product([S_POLY_ORDER4, S_TECH_ORDER_NODE4], names=["polygon", "technology"])
                agg_s4 = (df_s4.pivot_table(index=["polygon", "technology"], values="Investment Cost (B€)", aggfunc="sum", observed=False)
                          .reindex(full_idx_s4, fill_value=0.0).reset_index())
                fig_s_cost = px.bar(agg_s4, x="polygon", y="Investment Cost (B€)", color="technology",
                                    color_discrete_map=s_color_map, barmode="stack",
                                    category_orders={"polygon": S_POLY_ORDER4, "technology": S_TECH_ORDER_NODE4},
                                    title=f"Storage Investment Cost from 2030 to 2060 by Country ({scenario})")
                fig_s_cost.update_layout(height=height_value, bargap=0.15, template="plotly_white",
                                         legend_title_text="Technology", yaxis_title="Investment Cost (B€)")
                y_max_cost = agg_s4.groupby("polygon", observed=False)["Investment Cost (B€)"].sum().max()
                if pd.isna(y_max_cost):
                    y_max_cost = 0
                y_pad_cost = y_max_cost * 0.05 if y_max_cost > 0 else 1.0
                fig_s_cost.update_yaxes(range=[0, y_max_cost + y_pad_cost])
                st.plotly_chart(fig_s_cost, width="stretch")
                download_plot(fig_s_cost, "storage_investment_cost")


if __name__ == "__main__":
    main()