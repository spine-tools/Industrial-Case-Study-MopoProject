import argparse
import hashlib
import io
import warnings
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.colors as mcolors
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.dates as mdates
import dill
warnings.filterwarnings("ignore")
# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
PAGE_W       = 22     # inches page width
PAGE_L       = 25     # inches page length
BAR_H_PER_C  = 0.28  # inches determine the height of the row
MIN_ROW_H    = 5      # inches min altitude
DPI          = 130
BAR_W        = 0.72
# ── Global font sizes ────────────────────────
FS_TITLE     = 22   # suptitle / section headers
FS_AX_TITLE  = 22   # subplot titles
FS_LABEL     = 22   # axis labels
FS_TICK      = 22   # tick labels
FS_LEGEND    = 22   # legend text
# Apply globally so every matplotlib element inherits larger defaults
matplotlib.rcParams.update({ "font.size":        FS_LABEL, "axes.titlesize":   FS_AX_TITLE, "axes.labelsize":   FS_LABEL, "xtick.labelsize":  FS_TICK, "ytick.labelsize":  FS_TICK, "legend.fontsize":  FS_LEGEND, "figure.titlesize": FS_TITLE, })
# ─────────────────────────────────────────────
# COLOR HELPERS
# ─────────────────────────────────────────────
def assign_color(tech_name: str) -> str:
    t = tech_name.lower()
    if "solar" in t or "pv" in t or "photovoltaic" in t:           return "#FFD700"
    if "wind" in t or "eolica" in t or "eólica" in t:              return "#87CEEB"
    if "hydro" in t or "hydra" in t or "water" in t or "dam" in t: return "#1E90FF"
    if "nuclear" in t or "uranium" in t:                            return "#9370DB"
    if "gas" in t and "biogas" not in t:                            return "#A9A9A9"
    if "coal" in t or "carbon" in t or "carbón" in t:              return "#2F4F4F"
    if "oil" in t or "diesel" in t or "fuel" in t:                 return "#8B4513"
    if "biomass" in t or "bio" in t or "waste" in t:               return "#6B8E23"
    if "geothermal" in t or "geo" in t:                             return "#FF6347"
    if "battery" in t or "storage" in t or "bess" in t:            return "#32CD32"
    if "renewable" in t or "green" in t or "clean" in t:           return "#00FA9A"
    if "turbine" in t:                                              return "#B0C4DE"
    if "ccgt" in t or "combined cycle" in t:                        return "#C0C0C0"
    if "chp" in t or "cogeneration" in t or "cogen" in t:          return "#DAA520"
    h = int(hashlib.md5(tech_name.encode()).hexdigest(), 16)
    r, g, b = (h % 155) + 100, ((h >> 8) % 155) + 100, ((h >> 16) % 155) + 100
    return f"#{r:02x}{g:02x}{b:02x}"
def node_color_hex(name: str) -> str:
    h = int(hashlib.md5(name.encode()).hexdigest(), 16)
    return f"#{(h%180)+75:02x}{((h>>8)%180)+75:02x}{((h>>16)%180)+75:02x}"
# ─────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────
def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, index_col=0)
    return df.loc[:, ~df.columns.str.contains(r"^Unnamed")]
def melt_df(df: pd.DataFrame, value_name: str, id_vars) -> pd.DataFrame:
    year_cols = [c for c in df.columns if c.startswith("y") and c[1:].isdigit()]
    return df.melt(id_vars=id_vars, value_vars=year_cols, var_name="year", value_name=value_name)
def load_all(data_dir: str):
    p = Path(data_dir)
    installed      = load_csv(str(p / "installed_capacity.csv"))
    invested       = load_csv(str(p / "invested_capacity.csv"))
    invested_cost  = load_csv(str(p / "invested_cost.csv"))
    decommissioned = load_csv(str(p / "decommissioned_capacity.csv"))
    unit_to_flows  = load_csv(str(p / "unit_to_flows.csv"))
    energy_flows   = load_csv(str(p / "energy_flows.csv"))
    crossborder    = load_csv(str(p / "crossborder_flows.csv"))
    emissions      = load_csv(str(p / "emissions_flows.csv"))
    with open(str(p / "node_state.dill"), "rb") as f:
        storage_dict = dill.load(f)
    s_installed      = load_csv(str(p / "storage_installed_capacity.csv"))
    s_invested       = load_csv(str(p / "storage_invested_capacity.csv"))
    s_cost           = load_csv(str(p / "storage_cost_capacity.csv"))
    s_decommissioned = load_csv(str(p / "storage_decommissioned_capacity.csv"))
    return (installed, invested, invested_cost, decommissioned, unit_to_flows,
            energy_flows, crossborder, emissions, storage_dict,
            s_installed, s_invested, s_cost, s_decommissioned)
def preprocess(installed, invested, invested_cost, decommissioned, unit_to_flows):
    ID_VARS = ["unit_name", "node", "scenario", "polygon", "technology"]
    inst_m = melt_df(installed,      "Installed",      ID_VARS)
    inv_m  = melt_df(invested,       "Invested",       ID_VARS)
    cost_m = melt_df(invested_cost,  "Invested_Cost",  ID_VARS)
    dec_m  = melt_df(decommissioned, "Decommissioned", ID_VARS)
    flow_m = melt_df(unit_to_flows,  "UnitFlows",      ID_VARS)
    merged = (inst_m .merge(inv_m,  on=ID_VARS + ["year"], how="outer") .merge(dec_m,  on=ID_VARS + ["year"], how="outer") .merge(cost_m, on=ID_VARS + ["year"], how="outer") .merge(flow_m, on=ID_VARS + ["year"], how="outer"))
    merged["year"] = merged["year"].str.extract(r"(\d+)")
    merged = merged.dropna(subset=["year"]).copy()
    merged["year"] = merged["year"].astype(int)
    for col in ["technology", "polygon", "node", "scenario"]:
        merged[col] = merged[col].astype(str).str.strip()
    merged["technology"] = merged["technology"].replace({"nan": "Unknown"})
    merged["Invested_Cost"] /= 1e3   # → B€
    merged["UnitFlows"]     /= 1e3   # → TWh
    return merged

def preprocess_storage(s_installed, s_invested, s_cost, s_decommissioned):
    """Preprocess storage capacity CSVs into a single merged DataFrame."""
    # Infer id_vars from columns shared across all four files
    candidate_id_vars = ["unit_name", "node", "scenario", "polygon", "technology"]
    id_vars = [c for c in candidate_id_vars if c in s_installed.columns]
    inst_m = melt_df(s_installed,      "Installed",      id_vars)
    inv_m  = melt_df(s_invested,       "Invested",       id_vars)
    cost_m = melt_df(s_cost,           "Invested_Cost",  id_vars)
    dec_m  = melt_df(s_decommissioned, "Decommissioned", id_vars)
    merged = (inst_m
              .merge(inv_m,  on=id_vars + ["year"], how="outer")
              .merge(dec_m,  on=id_vars + ["year"], how="outer")
              .merge(cost_m, on=id_vars + ["year"], how="outer"))
    merged["year"] = merged["year"].str.extract(r"(\d+)")
    merged = merged.dropna(subset=["year"]).copy()
    merged["year"] = merged["year"].astype(int)
    for col in ["technology", "polygon", "node", "scenario"]:
        if col in merged.columns:
            merged[col] = merged[col].astype(str).str.strip()
    if "technology" in merged.columns:
        merged["technology"] = merged["technology"].replace({"nan": "Unknown"})
    merged["Invested_Cost"] /= 1e3   # → B€
    return merged
# ─────────────────────────────────────────────
# PDF LAYOUT HELPERS
# ─────────────────────────────────────────────
def add_cover(pdf: PdfPages, title: str, subtitle: str = ""):
    fig, ax = plt.subplots(figsize=(PAGE_W, 14))
    ax.axis("off")
    ax.text(0.5, 0.60, title,    ha="center", va="center", fontsize=40, fontweight="bold", transform=ax.transAxes)
    ax.text(0.5, 0.50, subtitle, ha="center", va="center", fontsize=20, color="#555", transform=ax.transAxes)
    ax.text(0.5, 0.42, "Generated automatically by generate_report.py", ha="center", va="center", fontsize=14, color="#888", transform=ax.transAxes)
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)
def add_section_title(pdf: PdfPages, text: str):
    fig, ax = plt.subplots(figsize=(PAGE_W, 2.5))
    ax.axis("off")
    ax.text(0.05, 0.55, text, ha="left", va="center", fontsize=26, fontweight="bold", transform=ax.transAxes, color="#1a3a5c")
    ax.axhline(0.18, color="#1a3a5c", linewidth=2, xmin=0.05, xmax=0.95)
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)
def fig_from_png_bytes(png_bytes: bytes) -> plt.Figure:
    """Wrap PNG bytes in a Matplotlib figure to insert into PdfPages."""
    from PIL import Image
    img = Image.open(io.BytesIO(png_bytes))
    w, h = img.size
    fig_h = PAGE_W * h / w
    fig, ax = plt.subplots(figsize=(PAGE_W, fig_h))
    ax.imshow(np.array(img))
    ax.axis("off")
    fig.tight_layout(pad=0)
    return fig
def row_height(n_countries: int) -> float:
    """Row height (in inches) for a bar block, proportional to number of countries."""
    return max(MIN_ROW_H, n_countries * BAR_H_PER_C)
# ─────────────────────────────────────────────
# STACKED BAR HELPER  (una fila = un año)
# ─────────────────────────────────────────────
def stacked_bar_subplot(ax, df_year, countries, techs, color_map, value_col, title):
    """
    Draw stacked bars in `ax` for a single year.
    Supports both positive and negative values.
    Automatically adjusts ylim to avoid clipping.
    """
    x = np.arange(len(countries))
    bottom_pos = np.zeros(len(countries))
    bottom_neg = np.zeros(len(countries))
    for tech in techs:
        vals = np.array([ float(df_year.loc[(df_year["polygon"] == c) & (df_year["technology"] == tech), value_col].sum()) for c in countries ])
        pos_v = np.where(vals > 0, vals, 0.0)
        neg_v = np.where(vals < 0, vals, 0.0)
        color = color_map.get(tech, "#aaa")
        ax.bar(x, pos_v, bottom=bottom_pos, color=color, label=tech, width=BAR_W)
        ax.bar(x, neg_v, bottom=bottom_neg, color=color,               width=BAR_W)
        bottom_pos += pos_v
        bottom_neg += neg_v
    # Y-limits without clipping, with 10% padding
    y_max = float(bottom_pos.max()) if bottom_pos.max() > 0 else 0.0
    y_min = float(bottom_neg.min()) if bottom_neg.min() < 0 else 0.0
    pad   = max((y_max - y_min) * 0.10, 1.0)
    ax.set_ylim(y_min - pad, y_max + pad)
    ax.set_xticks(x)
    ax.set_xticklabels(countries, rotation=55, ha="right", fontsize=FS_TICK)
    ax.set_title(title, fontsize=FS_AX_TITLE, fontweight="bold")
    ax.axhline(0, color="black", linewidth=0.6, linestyle="--")
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.spines[["top", "right"]].set_visible(False)
# ─────────────────────────────────────────────
# SECTIONS 1-3: Capacity / Production / Inv-Dec
# ─────────────────────────────────────────────
def plot_capacity_section(pdf, merged, scenarios, year_order, color_map, value_col, ylabel_label, section_title):
    add_section_title(pdf, section_title)
    nodes     = sorted(merged["node"].dropna().unique())
    countries = sorted(c for c in merged["polygon"].dropna().unique() if c != "Europe")
    rh = row_height(len(countries))
    for scenario in scenarios:
        for node in nodes:
            df_f = merged[(merged["scenario"] == scenario) & (merged["node"] == node)].copy()
            df_f = df_f[df_f["polygon"] != "Europe"]
            if df_f.empty:
                continue
            present_tech = (df_f.loc[df_f[value_col].abs() > 0.001, "technology"].dropna().unique().tolist())
            if not present_tech:
                continue
            techs  = [t for t in sorted(merged["technology"].unique()) if t in present_tech]
            n_rows = len(year_order)
            fig_h  = rh * n_rows + 1.5
            fig, axes = plt.subplots(n_rows, 1,figsize=(PAGE_W, PAGE_L),constrained_layout=True)
            if n_rows == 1:
                axes = [axes]
            fig.suptitle(f"{section_title}  |  Scenario: {scenario}  |  Node: {node}", fontsize=FS_TITLE, fontweight="bold")
            for ax, year in zip(axes, year_order):
                df_y = df_f[df_f["year"] == year]
                stacked_bar_subplot(ax, df_y, countries, techs, color_map,value_col, f"Year {year}")
                if "GW" in ylabel_label:
                    y_new_label = "Capacity (GW or kton/h in Industry)"
                elif "TWh" in ylabel_label:
                    y_new_label = "Capacity (TWh or Mton in Industry)"
                ax.set_ylabel(y_new_label, fontsize=FS_LABEL)
            # Shared legend below all subplots
            handles = [mpatches.Patch(color=color_map.get(t, "#aaa"), label=t) for t in techs]
            fig.legend(handles=handles,ncol=4,loc="lower center",bbox_to_anchor=(0.5, 1.02),fontsize=FS_LEGEND, frameon=True)
            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)
# ─────────────────────────────────────────────
# SECTION 4: CAPEX
# ─────────────────────────────────────────────
def plot_capex(pdf, merged, scenarios, color_map):
    add_section_title(pdf, "4 · Investment Cost (CAPEX – cumulative)")
    nodes     = sorted(merged["node"].dropna().unique())
    countries = sorted(c for c in merged["polygon"].dropna().unique() if c != "Europe")
    rh = row_height(len(countries))
    for scenario in scenarios:
        for node in nodes:
            df_f = (merged[(merged["scenario"] == scenario) & (merged["node"] == node)] .query("polygon != 'Europe'").copy())
            if df_f.empty or df_f["Invested_Cost"].sum() < 0.001:
                continue
            present_tech = (df_f.loc[df_f["Invested_Cost"] > 0.001, "technology"] .dropna().unique().tolist())
            if not present_tech:
                continue
            techs = sorted(present_tech)
            agg = (df_f.pivot_table(index=["polygon", "technology"], values="Invested_Cost", aggfunc="sum") .reindex(pd.MultiIndex.from_product([countries, techs], names=["polygon", "technology"]), fill_value=0.0) .reset_index())
            fig, ax = plt.subplots(figsize=(PAGE_W, rh + 1.5), constrained_layout=True)
            fig.suptitle(f"CAPEX (cumulative)  |  Scenario: {scenario}  |  Node: {node}", fontsize=FS_TITLE, fontweight="bold")
            x      = np.arange(len(countries))
            bottom = np.zeros(len(countries))
            for tech in techs:
                vals = (agg[agg["technology"] == tech] .set_index("polygon") .reindex(countries, fill_value=0.0)["Invested_Cost"].values)
                ax.bar(x, vals, bottom=bottom, label=tech, color=color_map.get(tech, "#aaa"), width=BAR_W)
                bottom += vals
            y_max = float(bottom.max()) if bottom.max() > 0 else 1.0
            ax.set_ylim(0, y_max * 1.12)
            ax.set_xticks(x)
            ax.set_xticklabels(countries, rotation=55, ha="right", fontsize=FS_TICK)
            ax.set_ylabel("Investment Cost (B€)", fontsize=FS_LABEL)
            ax.grid(axis="y", linestyle="--", alpha=0.35)
            ax.spines[["top", "right"]].set_visible(False)
            handles = [mpatches.Patch(color=color_map.get(t, "#aaa"), label=t) for t in techs]
            ax.legend(handles=handles, loc="upper right", ncol=2, fontsize=FS_LEGEND, frameon=True)
            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)
# ─────────────────────────────────────────────
# SECTIONS 5-7: Storage Capacity / Inv-Dec / CAPEX
# ─────────────────────────────────────────────
def plot_storage_capacity_section(pdf, merged_s, scenarios, year_order, color_map, value_col, ylabel_label, section_title):
    """Mirror of plot_capacity_section for storage DataFrames."""
    add_section_title(pdf, section_title)
    nodes     = sorted(merged_s["node"].dropna().unique()) if "node" in merged_s.columns else ["all"]
    countries = sorted(c for c in merged_s["polygon"].dropna().unique() if c != "Europe")
    rh = row_height(len(countries))
    for scenario in scenarios:
        node_list = nodes if "node" in merged_s.columns else ["all"]
        for node in node_list:
            if "node" in merged_s.columns:
                df_f = merged_s[(merged_s["scenario"] == scenario) & (merged_s["node"] == node)].copy()
            else:
                df_f = merged_s[merged_s["scenario"] == scenario].copy()
            df_f = df_f[df_f["polygon"] != "Europe"]
            if df_f.empty:
                continue
            present_tech = (df_f.loc[df_f[value_col].abs() > 0.001, "technology"].dropna().unique().tolist()
                            if "technology" in df_f.columns else [])
            if not present_tech:
                continue
            techs  = [t for t in sorted(merged_s["technology"].unique()) if t in present_tech]
            n_rows = len(year_order)
            fig, axes = plt.subplots(n_rows, 1, figsize=(PAGE_W, PAGE_L), constrained_layout=True)
            if n_rows == 1:
                axes = [axes]
            node_label = node if node != "all" else "all nodes"
            fig.suptitle(f"{section_title}  |  Scenario: {scenario}  |  Node: {node_label}",
                         fontsize=FS_TITLE, fontweight="bold")
            for ax, year in zip(axes, year_order):
                df_y = df_f[df_f["year"] == year]
                stacked_bar_subplot(ax, df_y, countries, techs, color_map, value_col, f"Year {year}")
                ax.set_ylabel(ylabel_label, fontsize=FS_LABEL)
            handles = [mpatches.Patch(color=color_map.get(t, "#aaa"), label=t) for t in techs]
            fig.legend(handles=handles, ncol=4, loc="lower center",
                       bbox_to_anchor=(0.5, 1.02), fontsize=FS_LEGEND, frameon=True)
            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)


def plot_storage_invdec_section(pdf, merged_s, scenarios, year_order, color_map, section_title):
    """Invested (+) vs Decommissioned (–) for storage, mirroring units section 3."""
    m_pos = (merged_s[["polygon", "technology", "year", "scenario"] +
                       (["node"] if "node" in merged_s.columns else []) + ["Invested"]]
             .rename(columns={"Invested": "InvDec"}))
    m_neg = (merged_s[["polygon", "technology", "year", "scenario"] +
                       (["node"] if "node" in merged_s.columns else []) + ["Decommissioned"]]
             .assign(Decommissioned=lambda d: -d["Decommissioned"])
             .rename(columns={"Decommissioned": "InvDec"}))
    merged_invdec = pd.concat([m_pos, m_neg], ignore_index=True)
    plot_storage_capacity_section(pdf, merged_invdec, scenarios, year_order, color_map,
                                  value_col="InvDec", ylabel_label="Capacity (GW)",
                                  section_title=section_title)


def plot_storage_capex(pdf, merged_s, scenarios, color_map, section_title):
    """Cumulative CAPEX for storage, mirroring units section 4."""
    add_section_title(pdf, section_title)
    nodes     = sorted(merged_s["node"].dropna().unique()) if "node" in merged_s.columns else ["all"]
    countries = sorted(c for c in merged_s["polygon"].dropna().unique() if c != "Europe")
    rh = row_height(len(countries))
    for scenario in scenarios:
        node_list = nodes if "node" in merged_s.columns else ["all"]
        for node in node_list:
            if "node" in merged_s.columns:
                df_f = (merged_s[(merged_s["scenario"] == scenario) & (merged_s["node"] == node)]
                        .query("polygon != 'Europe'").copy())
            else:
                df_f = merged_s[merged_s["scenario"] == scenario].query("polygon != 'Europe'").copy()
            if df_f.empty or df_f["Invested_Cost"].sum() < 0.001:
                continue
            present_tech = (df_f.loc[df_f["Invested_Cost"] > 0.001, "technology"]
                            .dropna().unique().tolist())
            if not present_tech:
                continue
            techs = sorted(present_tech)
            agg = (df_f.pivot_table(index=["polygon", "technology"], values="Invested_Cost", aggfunc="sum")
                   .reindex(pd.MultiIndex.from_product([countries, techs], names=["polygon", "technology"]),
                            fill_value=0.0)
                   .reset_index())
            fig, ax = plt.subplots(figsize=(PAGE_W, rh + 1.5), constrained_layout=True)
            node_label = node if node != "all" else "all nodes"
            fig.suptitle(f"{section_title}  |  Scenario: {scenario}  |  Node: {node_label}",
                         fontsize=FS_TITLE, fontweight="bold")
            x      = np.arange(len(countries))
            bottom = np.zeros(len(countries))
            for tech in techs:
                vals = (agg[agg["technology"] == tech]
                        .set_index("polygon")
                        .reindex(countries, fill_value=0.0)["Invested_Cost"].values)
                ax.bar(x, vals, bottom=bottom, label=tech, color=color_map.get(tech, "#aaa"), width=BAR_W)
                bottom += vals
            y_max = float(bottom.max()) if bottom.max() > 0 else 1.0
            ax.set_ylim(0, y_max * 1.12)
            ax.set_xticks(x)
            ax.set_xticklabels(countries, rotation=55, ha="right", fontsize=FS_TICK)
            ax.set_ylabel("Investment Cost (B€)", fontsize=FS_LABEL)
            ax.grid(axis="y", linestyle="--", alpha=0.35)
            ax.spines[["top", "right"]].set_visible(False)
            handles = [mpatches.Patch(color=color_map.get(t, "#aaa"), label=t) for t in techs]
            ax.legend(handles=handles, loc="upper right", ncol=2, fontsize=FS_LEGEND, frameon=True)
            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)


# ─────────────────────────────────────────────
# SECTION 5: STORAGE STATE (node_state.dill)
# ─────────────────────────────────────────────
def plot_storage(pdf, storage_dict, year_order=None):
    # Define the target years and how to map the "odd" one
    # If 2041 appears, we show it in the subplot meant for 2040.
    target_years = [2030, 2040, 2050]
    
    # Styling
    plt.rcParams.update({'font.size': 10})
    cmap = plt.get_cmap("tab20")
    for scenario, df_raw in storage_dict.items():
        if df_raw is None or df_raw.empty:
            continue
        # --- INITIAL CLEANUP ---
        df = df_raw.copy()
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()
        # REMOVE DUPLICATES: this prevents ValueError
        # If two rows share the same hour, keep the last one (keep='last')
        df = df[~df.index.duplicated(keep='last')]
        # FILL GAPS WITH NaN:
        # Now that the index is unique, create a row for every hour.
        # Hours with no data will be NaN and therefore break the line in the plot.
        df = df.resample('H').asfreq()
        # Identify technologies (prefix before the '_')
        techs = sorted(list(set(col.split('_')[0] for col in df.columns)))
        for tech in techs:
            tech_cols = [c for c in df.columns if c.startswith(f"{tech}_")]
            if not tech_cols:
                continue
            
            # Build the figure with 3 subplots (one for each target year)
            fig, axes = plt.subplots(3, 1, figsize=(11, 14), sharex=False)
            fig.suptitle(f"Storage State | Scenario: {scenario} | Tech: {tech}", fontsize=14, fontweight='bold', y=0.98)
            # Color map so the same country keeps the same color across the 3 subplots
            countries = sorted(tech_cols)
            color_map = {c: cmap(i % 20) for i, c in enumerate(countries)}
            for i, target_yr in enumerate(target_years):
                ax = axes[i]
                
                # Plot each country
                for col in tech_cols:
                    country_label = col.split('_', 1)[1] if '_' in col else col
                    # Matplotlib omitirá automáticamente los NaNs creados por .asfreq()
                    df_final = df_raw[col][(df_raw[col].notna())&(df_raw[col].index.year == target_yr if target_yr!= 2040 else (df_raw[col].index.year == 2040) | (df_raw[col].index.year == 2041))]
                    ax.plot(df_final.index, df_final.values/1e3, label=country_label, color=color_map[col], linewidth=1.2)
                # Aesthetics
                ax.set_title(f"Representation of Year {target_yr}", loc='left', fontweight='semibold')
                ax.set_ylabel("TWh")
                ax.grid(True, linestyle=':', alpha=0.6)
                
                # X axis: show month and day
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
                ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2)) # Un tick cada 2 meses
                
                # Remove borders for a cleaner look
                ax.spines['top'].set_visible(False)
                ax.spines['right'].set_visible(False)
            # Global legend for the technology (bottom)
            handles, labels = axes[0].get_legend_handles_labels()
            if handles:
                fig.legend(handles, labels, loc='lower center', ncol=8, bbox_to_anchor=(0.5, 0.02), fontsize=FS_LEGEND, frameon=True)
            plt.tight_layout(rect=[0, 0.05, 1, 0.96])
            pdf.savefig(fig)
            plt.close(fig)
# ─────────────────────────────────────────────
# SECTION 6: SANKEY  (Plotly → PNG, uno por año)
# ─────────────────────────────────────────────
def _build_sankey_links(flow_data, cb_data, scenario, region, year, flow_label, all_nodes):
    """Return (src_list, tgt_list, val_list, clr_list, node_colors) for a year."""
    ycol      = f"y{year}"
    node_idx  = {n: i for i, n in enumerate(all_nodes)}
    node_clrs = [node_color_hex(n) for n in all_nodes]
    thresh    = 0.001 if "Emission" not in flow_label else 1000
    src_l, tgt_l, val_l, clr_l = [], [], [], []
    df = flow_data[flow_data["scenario"] == scenario].copy()
    if region != "Europe" and "polygon" in df.columns:
        df = df[df["polygon"] == region]
    if ycol not in df.columns:
        return src_l, tgt_l, val_l, clr_l, node_clrs
    df = df.groupby(["source", "target"])[ycol].sum().reset_index()
    for _, row in df.iterrows():
        if row[ycol] <= thresh:
            continue
        sn, tn = row["source"], row["target"]
        if sn not in node_idx or tn not in node_idx:
            continue
        src_l.append(node_idx[sn]); tgt_l.append(node_idx[tn])
        val_l.append(float(row[ycol]))
        nc = node_clrs[node_idx[sn]].lstrip("#")
        r, g, b = int(nc[0:2], 16), int(nc[2:4], 16), int(nc[4:6], 16)
        clr_l.append(f"rgba({r},{g},{b},0.4)")
    # Include cross-border links only for per-country charts (NOT for Europe aggregation)
    if cb_data is not None and region != "Europe" and ycol in cb_data.columns:
        cb_df = cb_data[(cb_data["source"] == region) | (cb_data["target"] == region)]
        for _, row in cb_df.iterrows():
            if row[ycol] <= 0.001:
                continue
            sn = f"Import-{row['source']}" if row["target"] == region else row["commodity"]
            tn = row["commodity"]            if row["target"] == region else f"Export-{row['target']}"
            if sn not in node_idx or tn not in node_idx:
                continue
            src_l.append(node_idx[sn]); tgt_l.append(node_idx[tn])
            val_l.append(float(row[ycol]))
            nc = node_clrs[node_idx[sn]].lstrip("#")
            r, g, b = int(nc[0:2], 16), int(nc[2:4], 16), int(nc[4:6], 16)
            clr_l.append(f"rgba({r},{g},{b},0.4)")
    return src_l, tgt_l, val_l, clr_l, node_clrs

def plot_sankey(pdf, energy_flows, crossborder_flows, emissions_flows, scenarios, year_order):
    try:
        import plotly.graph_objects as go
    except ImportError:
        print("  ⚠  plotly not found – skipping Sankey")
        add_section_title(pdf, "6 · Sankey – NOT AVAILABLE (install plotly + kaleido)")
        return
        
    add_section_title(pdf, "6 · Sankey Diagrams")
    flow_datasets = [ 
        ("Energy Flows", energy_flows, crossborder_flows), 
        ("Emissions Flows", emissions_flows, None), 
    ]
    
    # 1. NEW: Get all unique regions (countries) from the dataset dynamically
    all_regions = ["Europe"]
    if "polygon" in energy_flows.columns:
        countries = [c for c in energy_flows["polygon"].dropna().unique() if c != "Europe"]
        all_regions.extend(countries)

    for scenario in scenarios:
        # 2. NEW: Use the dynamic list of regions instead of the hardcoded ["Europe"]
        regions = all_regions 
        
        for flow_label, flow_data, cb_data in flow_datasets:
            year_cols_fd = [c for c in flow_data.columns if isinstance(c, str) and c.startswith("y") and c[1:].isdigit()]
            avail_years = sorted([int(c[1:]) for c in year_cols_fd if int(c[1:]) in year_order])
            
            if not avail_years:
                continue
                
            for region in regions:
                # ── Recopilar todos los nodos sobre todos los años ──────────
                all_nodes: set = set()
                thresh = 0.001 if "Emission" not in flow_label else 1000
                
                for year in avail_years:
                    ycol = f"y{year}"
                    df = flow_data[flow_data["scenario"] == scenario].copy()
                    
                    if region != "Europe" and "polygon" in df.columns:
                        df = df[df["polygon"] == region]
                        
                    if ycol not in df.columns:
                        continue
                        
                    df = df.groupby(["source", "target"])[ycol].sum().reset_index()
                    for _, row in df.iterrows():
                        if row[ycol] > thresh:
                            all_nodes.update([row["source"], row["target"]])
                            
                # Include cross-border links only for per-country charts (NOT for Europe aggregation)
                if cb_data is not None and region != "Europe" and ycol in cb_data.columns:
                    cb_df = cb_data[(cb_data["source"] == region) | (cb_data["target"] == region)]
                    for _, row in cb_df.iterrows():
                        if row.get(ycol, 0) > 0.001:
                            if row["target"] == region:
                                all_nodes.update([f"Import-{row['source']}", row["commodity"]])
                            else:
                                all_nodes.update([row["commodity"], f"Export-{row['target']}"])
                                
                if not all_nodes:
                    continue
                    
                nodes = sorted(all_nodes)
                
                # ── Una página (PNG) por año ──────────────────────────────
                for year in avail_years:
                    src_l, tgt_l, val_l, clr_l, node_clrs = _build_sankey_links(
                        flow_data, cb_data, scenario, region, year, flow_label, nodes
                    )
                    
                    if not src_l:
                        continue
                        
                    # 3. NEW: Dynamic title so it doesn't always say "Europe"
                    region_label = "Europe (aggregated)" if region == "Europe" else region
                    title = f"Sankey – {flow_label} | Region: {region_label} | Scenario: {scenario} | Year: {year}"
                    
                    fig_p = go.Figure(go.Sankey(
                        arrangement="snap",
                        node=dict(
                            pad=15, thickness=20,
                            line=dict(color="black", width=0.5),
                            label=nodes, color=node_clrs
                        ),
                        link=dict(
                            source=src_l, target=tgt_l, value=val_l, color=clr_l
                        )
                    ))
                    
                    fig_p.update_layout(
                        title_text=title,
                        font=dict(size=11, family="Arial"),
                        height=800, width=1600,
                        margin=dict(l=30, r=30, t=60, b=30)
                    )
                    
                    try:
                        png = fig_p.to_image(format="png", scale=1.0)
                        mpl_fig = fig_from_png_bytes(png)
                        pdf.savefig(mpl_fig, bbox_inches="tight")
                        plt.close(mpl_fig)
                    except Exception as e:
                        print(f"  ⚠  Sankey PNG falló ({e}) – {region}/{scenario}/{year}")

# ─────────────────────────────────────────────
# SECTION 7: FLOW MAP  (geopandas + matplotlib)
# ─────────────────────────────────────────────
def plot_flow_maps(pdf, crossborder_flows, scenarios, year_order, geo_path: str = None):
    add_section_title(pdf, "7 · Cross-border Flow Maps")
    if crossborder_flows.empty:
        return
    # Load GeoDataFrame (if available)
    gdf       = None
    centroids = {}
    if geo_path and Path(geo_path).exists():
        try:
            import geopandas as gpd
            gdf = gpd.read_file(geo_path).to_crs(epsg=4326)
            gdf["geometry"] = gdf["geometry"].simplify(tolerance=0.02)
            centroids = { str(row["id"]): (row.geometry.centroid.x, row.geometry.centroid.y) for _, row in gdf.iterrows() }
            print(f"  ✓  GeoJSON cargado: {len(gdf)} polygons, {len(centroids)} centroids")
        except Exception as e:
            print(f"  ⚠  No se pudo cargar GeoJSON ({e}) – usando layout circular")
    else:
        print("  ⚠  GeoJSON no encontrado – usando layout circular")
    year_cols   = [c for c in crossborder_flows.columns if isinstance(c, str) and c.startswith("y") and c[1:].isdigit()]
    avail_years = sorted([int(c[1:]) for c in year_cols if int(c[1:]) in year_order])
    commodities = sorted(crossborder_flows["commodity"].astype(str).dropna().unique())
    cmap_flow   = plt.get_cmap("plasma")
    for scenario in scenarios:
        for commodity in commodities:
            df = crossborder_flows[ (crossborder_flows["scenario"] == scenario) & (crossborder_flows["commodity"].astype(str) == commodity) ].copy()
            if df.empty:
                continue
            all_nodes = sorted( set(df["source"].astype(str)) | set(df["target"].astype(str)) )
            if not all_nodes:
                continue
            # ── Posiciones: centroids GeoJSON o layout circular ──────────
            if centroids:
                pos = {nd: centroids[nd] for nd in all_nodes if nd in centroids}
                missing = [nd for nd in all_nodes if nd not in centroids]
                if missing:
                    xs = [v[0] for v in pos.values()] or [0.0]
                    ys = [v[1] for v in pos.values()] or [0.0]
                    cx, cy = float(np.mean(xs)), float(np.mean(ys))
                    r_off  = max(float(np.ptp(xs)), float(np.ptp(ys))) * 0.6 + 5
                    for i, nd in enumerate(missing):
                        a = 2 * np.pi * i / max(len(missing), 1)
                        pos[nd] = (cx + r_off * np.cos(a), cy + r_off * np.sin(a))
            else:
                n   = len(all_nodes)
                pos = {nd: (np.cos(2 * np.pi * i / n), np.sin(2 * np.pi * i / n)) for i, nd in enumerate(all_nodes)}
            # Global color scaling
            ycols_present = [f"y{y}" for y in avail_years if f"y{y}" in df.columns]
            abs_max = float(df[ycols_present].to_numpy().max()) if ycols_present else 1.0
            abs_max = abs_max if abs_max > 1e-12 else 1.0
            # Axis limits adjusted to the GeoDataFrame
            if gdf is not None and pos:
                lons = [pos[nd][0] for nd in all_nodes if nd in pos]
                lats = [pos[nd][1] for nd in all_nodes if nd in pos]
                lon_pad = max(2.0, (max(lons) - min(lons)) * 0.18)
                lat_pad = max(2.0, (max(lats) - min(lats)) * 0.18)
                xlim = (min(lons) - lon_pad, max(lons) + lon_pad)
                ylim = (min(lats) - lat_pad, max(lats) + lat_pad)
            else:
                xlim = ylim = None
            # Figure: rows of subplots (one subplot per year)
            n_rows    = len(avail_years)
            map_row_h = 7   # inches por fila de mapa
            fig, axes = plt.subplots( n_rows, 1, figsize=(PAGE_W, map_row_h * n_rows), constrained_layout=True )
            if n_rows == 1:
                axes = [axes]
            fig.suptitle( f"Cross-border Flows – {commodity}  |  Scenario: {scenario}", fontsize=FS_TITLE, fontweight="bold" )
            for ax, year in zip(axes, avail_years):
                ycol = f"y{year}"
                # Background map
                if gdf is not None:
                    gdf.plot(ax=ax, color="#dce8f0", edgecolor="#9ab", linewidth=0.35, zorder=1)
                # Flow arrows
                for _, row in df.iterrows():
                    if ycol not in df.columns:
                        continue
                    val = float(row[ycol]) if not pd.isna(row.get(ycol, np.nan)) else 0.0
                    if val < 1e-12:
                        continue
                    snd, tnd = str(row["source"]), str(row["target"])
                    if snd not in pos or tnd not in pos:
                        continue
                    x0, y0 = pos[snd]
                    x1, y1 = pos[tnd]
                    t     = min(1.0, val / abs_max)
                    color = cmap_flow(t)
                    lw    = max(t * 5, 0.8)
                    ax.annotate( "", xy=(x1, y1), xytext=(x0, y0), arrowprops=dict( arrowstyle="->,head_width=0.35,head_length=0.25", color=color, lw=lw, connectionstyle="arc3,rad=0.20" ), zorder=3 )
                # Node labels
                for nd in all_nodes:
                    if nd not in pos:
                        continue
                    x, y = pos[nd]
                    ax.plot(x, y, "o", markersize=6, color="#1a3a5c", zorder=4)
                    y_offset = 0.5 if gdf is None else 0.6
                    ax.text(x, y + y_offset, nd, ha="center", va="bottom", fontsize=FS_TICK, zorder=5, bbox=dict(boxstyle="round,pad=0.15", fc="white", alpha=0.75, lw=0))
                ax.set_title(f"Year {year}", fontsize=FS_AX_TITLE, fontweight="bold")
                ax.axis("off")
                if xlim and ylim:
                    ax.set_xlim(*xlim)
                    ax.set_ylim(*ylim)
            # Shared colorbar
            sm = plt.cm.ScalarMappable(cmap=cmap_flow, norm=plt.Normalize(vmin=0, vmax=abs_max))
            sm.set_array([])
            fig.colorbar(sm, ax=list(axes), shrink=0.5, pad=0.01, label=f"{commodity} flow")
            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)
# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Generate energy model PDF report")
    parser.add_argument("--out",      default="report.pdf", help="Output PDF path  (default: report.pdf)")
    parser.add_argument("--data-dir", default="files_out", help="Directory with CSV/dill files  (default: files_out)")
    parser.add_argument("--geo",      default="config/IC1.geojson", help="GeoJSON for flow maps  (default: config/IC1.geojson)")
    args = parser.parse_args()
    print(f"[1/11] Loading data from '{args.data_dir}' ...")
    (installed, invested, invested_cost, decommissioned, unit_to_flows,
     energy_flows, crossborder, emissions, storage_dict,
     s_installed, s_invested, s_cost, s_decommissioned) = load_all(args.data_dir)
    print("[2/11] Preprocessing units ...")
    merged = preprocess(installed, invested, invested_cost, decommissioned, unit_to_flows)
    scenarios  = sorted(merged["scenario"].dropna().unique())
    year_order = sorted(merged["year"].dropna().astype(int).unique())
    tech_order = sorted(merged["technology"].dropna().unique())
    color_map  = {t: assign_color(t) for t in tech_order}
    print("[3/11] Preprocessing storage capacities ...")
    merged_s = preprocess_storage(s_installed, s_invested, s_cost, s_decommissioned)
    s_tech_order = sorted(merged_s["technology"].dropna().unique()) if "technology" in merged_s.columns else tech_order
    s_color_map  = {t: assign_color(t) for t in s_tech_order}
    print(f"       Scenarios : {scenarios}")
    print(f"       Years     : {year_order}")
    print(f"       Tech count (units)  : {len(tech_order)}")
    print(f"       Tech count (storage): {len(s_tech_order)}")
    print(f"[4/11] Writing PDF to '{args.out}' ...")
    with PdfPages(args.out) as pdf:
        add_cover(pdf, "European Energy Model – Report", subtitle=f"Scenarios: {', '.join(scenarios)}")
        # ── 1. Installed Capacity ──────────────────────────────────────────────
        print("[4/11] Section 1: Installed Capacity ...")
        plot_capacity_section(pdf, merged, scenarios, year_order, color_map,
                              value_col="Installed", ylabel_label="Capacity (GW)",
                              section_title="1 · Installed Capacity")
        # ── 2. Energy Production ───────────────────────────────────────────────
        print("[5/11] Section 2: Energy Production ...")
        plot_capacity_section(pdf, merged, scenarios, year_order, color_map,
                              value_col="UnitFlows", ylabel_label="Flows (TWh)",
                              section_title="2 · Energy Production")
        # ── 3. Invested vs Decommissioned ─────────────────────────────────────
        print("[6/11] Section 3: Invested vs Decommissioned ...")
        m_pos = (merged[["polygon", "technology", "year", "scenario", "node", "Invested"]]
                 .rename(columns={"Invested": "InvDec"}))
        m_neg = (merged[["polygon", "technology", "year", "scenario", "node", "Decommissioned"]]
                 .assign(Decommissioned=lambda d: -d["Decommissioned"])
                 .rename(columns={"Decommissioned": "InvDec"}))
        merged_invdec = pd.concat([m_pos, m_neg], ignore_index=True)
        plot_capacity_section(pdf, merged_invdec, scenarios, year_order, color_map,
                              value_col="InvDec", ylabel_label="Capacity (GW)",
                              section_title="3 · Invested (+) vs Decommissioned (–)")
        # ── 4. CAPEX ──────────────────────────────────────────────────────────
        print("[7/11] Section 4: CAPEX ...")
        plot_capex(pdf, merged, scenarios, color_map)
        # ── 5. Storage Installed Capacity ─────────────────────────────────────
        print("[8/11] Section 5: Storage Installed Capacity ...")
        plot_storage_capacity_section(pdf, merged_s, scenarios, year_order, s_color_map,
                                      value_col="Installed", ylabel_label="Capacity (GW)",
                                      section_title="5 · Storage Installed Capacity")
        # ── 6. Storage Invested vs Decommissioned ─────────────────────────────
        print("[8/11] Section 6: Storage Invested vs Decommissioned ...")
        plot_storage_invdec_section(pdf, merged_s, scenarios, year_order, s_color_map,
                                    section_title="6 · Storage Invested (+) vs Decommissioned (–)")
        # ── 7. Storage CAPEX ──────────────────────────────────────────────────
        print("[8/11] Section 7: Storage CAPEX ...")
        plot_storage_capex(pdf, merged_s, scenarios, s_color_map,
                           section_title="7 · Storage Investment Cost (CAPEX – cumulative)")
        # ── 8. Storage State ──────────────────────────────────────────────────
        print("[8/11] Section 8: Storage State ...")
        plot_storage(pdf, storage_dict, year_order)
        # ── 9. Sankey ─────────────────────────────────────────────────────────
        print("[9/11] Section 9: Sankey Diagrams  (Plotly → PNG, uno por año) ...")
        # plot_sankey(pdf, energy_flows, crossborder, emissions, scenarios, year_order)
        # ── 10. Flow Maps ─────────────────────────────────────────────────────
        print("[10/11] Section 10: Cross-border Flow Maps (geopandas) ...")
        plot_flow_maps(pdf, crossborder, scenarios, year_order, geo_path=args.geo)
    print(f"\n✅  Reporte guardado en: {args.out}")
if __name__ == "__main__":
    main()
# python generate_report.py --data-dir files_out --out report.pdf