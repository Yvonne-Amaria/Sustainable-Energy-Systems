# feature_transition_generation.py
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px

from models import Site, ScenarioInput
from data_connectors import DataConnectors
from resources import quote_links
from nrel_client import NRELClient   # NREL PVWatts client

# ---------------- Defaults / constants ----------------

CATEGORY_LABELS = ["Individual", "Business", "Community", "City"]

WIND_DEFAULT_DENSITY_MW_PER_KM2 = 4.25
WIND_DEFAULT_CF = 0.40
PV_ROOFTOP_COST_PER_KW = 1800.0
PV_GROUND_COST_PER_KW = 1500.0
WIND_COST_PER_KW = 1500.0
GREEN_PREMIUM_USD_PER_KWH = 0.01
COMMUNITY_SOLAR_DISCOUNT_FRAC = 0.10


# ---------------- Simple PV / Wind Estimators ----------------
# PV function tries PVWatts first, then falls back to classroom logic.

def _pv_kwh_year(
    lat: float | None,
    lon: float | None,
    kwdc: float,
    tilt_deg: float,
    shading_pct: float,
    losses_pct: float = 14.0,
) -> tuple[float, bool]:
    """
    Estimate PV kWh/year.

    Returns:
        (kwh_per_year, used_pvwatts: bool)

    Logic:
    1. If NREL API key + lat/lon available → call PVWatts (AC annual).
    2. If call fails or data missing → fall back to classroom rule-of-thumb.
    """
    st.session_state["pvwatts_last_error"] = None
    pvwatts_used = False

    # ---- Try PVWatts first ----
    if lat is not None and lon is not None:
        nrel = NRELClient()
        if nrel.available():
            ac_annual = nrel.pvwatts_ac_annual(
                lat=lat,
                lon=lon,
                system_capacity_kw=kwdc,
                tilt_deg=tilt_deg,
                azimuth_deg=180.0,
                array_type=1,   # fixed open rack
                module_type=1,  # standard
                losses_pct=losses_pct,
            )
            if ac_annual is not None:
                pvwatts_used = True
                return ac_annual, pvwatts_used
            else:
                # Record why PVWatts failed
                st.session_state["pvwatts_last_error"] = nrel.last_error or "Unknown PVWatts error."

        else:
            st.session_state["pvwatts_last_error"] = "NREL_API_KEY not available."

    # ---- Fallback: classroom rule-of-thumb ----
    if lat is not None and lon is not None:
        resource = DataConnectors.solar_resource(lat, lon)
        ghi = resource.get("GHI_kWhm2_day", 4.2)
    else:
        ghi = 4.2  # default US-ish

    # 300 kWh / (kWdc·yr) per kWh/m²-day is the classroom constant
    base = 300 * ghi
    tilt_factor = 1.0 - min(0.5, abs(tilt_deg - 30) * 0.01)
    shading_factor = max(0.0, 1.0 - shading_pct / 100.0)
    kwh = kwdc * base * tilt_factor * shading_factor
    return kwh, pvwatts_used


def _wind_kwh_year(
    acres: float,
    mw_per_km2: float = WIND_DEFAULT_DENSITY_MW_PER_KM2,
    cf: float = WIND_DEFAULT_CF,
) -> float:
    """
    Very rough wind generation estimate (kWh/yr) for onshore wind.

    - Converts acres to km².
    - Uses MW/km² density and capacity factor to estimate energy.
    """
    km2 = acres / 247.105  # 1 km² = 247.105 acres
    capacity_mw = km2 * mw_per_km2
    return capacity_mw * 1e3 * 8760 * cf  # kWh/yr


def _category_flavor(category: str) -> str:
    if category == "Individual":
        return "We assume a home / small building with a typical residential bill and rooftop potential."
    if category == "Business":
        return "We assume a single commercial building with more roof area and higher daytime load."
    if category == "Community":
        return "We assume multiple buildings and more room for community solar or shared wind."
    if category == "City":
        return (
            "We assume a portfolio of sites and large aggregate load, where utility-scale solar, community solar, "
            "and green tariffs matter most."
        )
    return ""


def _goal_weights(goal: str) -> tuple[float, float, float]:
    """
    Map user goal → weights for (savings, CO2, payback) in the final score.
    """
    if goal == "Lower my bill":
        return 0.6, 0.2, 0.2
    if goal == "Maximize CO₂ reduction":
        return 0.3, 0.6, 0.1
    # Balanced
    return 0.4, 0.4, 0.2


# ---------------- Core ranking logic ----------------

def _rank_options(
    category: str,
    scen: ScenarioInput,
    tilt: float,
    shading: float,
    roof_area_m2: float | None,
    wind_acres: float | None,
    goal: str,
    target_load_pct: float,
    wind_density_mw_km2: float,
    wind_cf: float,
    pv_rooftop_cost_kw: float,
    pv_ground_cost_kw: float,
    wind_cost_kw: float,
    green_premium_usd_per_kwh: float,
    community_solar_discount_frac: float,
    pv_losses_pct: float,
) -> tuple[pd.DataFrame, bool]:
    """
    Build a table of candidate generation options and score them based on goal.

    Returns:
        (df, pvwatts_used_any: bool)
    """
    site = scen.site
    annual_kwh = scen.site.annual_electricity_kwh or 10_000
    annual_kwh = float(annual_kwh)
    elec_rate = scen.elec_rate_usd_per_kwh
    grid_kg_per_kwh = scen.grid_emissions_kgco2e_per_kwh or 0.38  # fallback US-ish

    lat, lon = site.lat, site.lon

    rows: list[dict] = []
    pvwatts_used_any = False

    # ---------- Rooftop PV ----------
    if roof_area_m2 and roof_area_m2 > 0:
        kw_roof = max(0.0, roof_area_m2 * 0.2)
    else:
        kw_roof = max(1.0, round(annual_kwh / 1400.0, 1))

    pv_kwh, used_pvwatts = _pv_kwh_year(lat, lon, kw_roof, tilt, shading, pv_losses_pct)

    if used_pvwatts:
        pvwatts_used_any = True

    pv_useful_kwh = min(pv_kwh, annual_kwh * (target_load_pct / 100.0))
    pv_capex = kw_roof * pv_rooftop_cost_kw
    pv_savings = pv_useful_kwh * elec_rate
    pv_co2_t = pv_useful_kwh * grid_kg_per_kwh / 1000.0

    rows.append(
        {
            "Technology": f"Rooftop PV (~{kw_roof:.0f} kWdc)",
            "Type": "On-site solar",
            "Capex_USD": pv_capex,
            "Annual_kWh": pv_kwh,
            "Load_Covered_%": pv_useful_kwh / annual_kwh * 100.0,
            "Annual_Savings_USD": pv_savings,
            "CO2e_Reduction_tpy": pv_co2_t,
            "Notes": (
                "Estimated with PVWatts (AC annual) using local weather data."
                if used_pvwatts
                else "Estimated with classroom rule-of-thumb yield adjusted for tilt & shading."
            ),
        }
    )

    # ---------- Ground / carport PV (if roof limited & category ≠ Individual) ----------
    if category in ("Business", "Community", "City"):
        # aim for ~100% of load (or target) when adding ground/carport
        extra_kw = max(0.0, annual_kwh / 1000.0 - kw_roof)
        if extra_kw > 0:
            extra_kwh, used_pvwatts_2 = _pv_kwh_year(lat, lon, extra_kw, tilt, shading, pv_losses_pct)
            if used_pvwatts_2:
                pvwatts_used_any = True

            extra_useful_kwh = min(
                extra_kwh, max(0.0, annual_kwh * (target_load_pct / 100.0) - pv_useful_kwh)
            )
            extra_capex = extra_kw * pv_ground_cost_kw
            extra_savings = extra_useful_kwh * elec_rate
            extra_co2_t = extra_useful_kwh * grid_kg_per_kwh / 1000.0
            rows.append(
                {
                    "Technology": f"Ground/Carport PV (~{extra_kw:.0f} kWdc)",
                    "Type": "On-site solar",
                    "Capex_USD": extra_capex,
                    "Annual_kWh": extra_kwh,
                    "Load_Covered_%": extra_useful_kwh / annual_kwh * 100.0,
                    "Annual_Savings_USD": extra_savings,
                    "CO2e_Reduction_tpy": extra_co2_t,
                    "Notes": (
                        "Estimated with PVWatts (AC annual) using local weather data."
                        if used_pvwatts_2
                        else "Estimated with classroom rule-of-thumb yield adjusted for tilt & shading."
                    ),
                }
            )

    # ---------- Community solar subscription ----------
    if category in ("Individual", "Business"):
        sub_pct = 0.5
    elif category == "Community":
        sub_pct = 0.4
    else:  # City
        sub_pct = 0.3

    cs_kwh = annual_kwh * sub_pct
    cs_useful_kwh = cs_kwh * (target_load_pct / 100.0)
    # Students can think of this as a discount on the existing rate.
    cs_bill_discount = community_solar_discount_frac * elec_rate
    cs_savings = cs_useful_kwh * cs_bill_discount
    cs_co2_t = cs_useful_kwh * grid_kg_per_kwh / 1000.0

    rows.append(
        {
            "Technology": f"Community Solar Subscription (~{int(sub_pct*100)}% of load)",
            "Type": "Off-site solar",
            "Capex_USD": 0.0,
            "Annual_kWh": cs_kwh,
            "Load_Covered_%": cs_useful_kwh / annual_kwh * 100.0,
            "Annual_Savings_USD": cs_savings,
            "CO2e_Reduction_tpy": cs_co2_t,
            "Notes": "No upfront capex; assumes a bill credit on the subscribed share (e.g., 10% below standard rate).",
        }
    )

    # ---------- Utility green tariff / REC purchase ----------
    green_pct = 0.5 if category in ("Individual", "Business") else 0.3
    green_kwh = annual_kwh * green_pct * (target_load_pct / 100.0)
    green_premium = green_premium_usd_per_kwh
    green_cost = green_kwh * green_premium
    green_co2_t = green_kwh * grid_kg_per_kwh / 1000.0

    rows.append(
        {
            "Technology": f"Utility Green Power / RECs (~{int(green_pct*100)}% load)",
            "Type": "Off-site renewable",
            "Capex_USD": 0.0,
            "Annual_kWh": green_kwh,
            "Load_Covered_%": green_kwh / annual_kwh * 100.0,
            "Annual_Savings_USD": -green_cost,  # negative = costs more
            "CO2e_Reduction_tpy": green_co2_t,
            "Notes": "No capex; adds a small premium to your bill but cuts emissions.",
        }
    )

    # ---------- Small wind (if land provided) ----------
    if wind_acres and wind_acres > 0:
        wind_kwh = _wind_kwh_year(
            acres=wind_acres, mw_per_km2=wind_density_mw_km2, cf=wind_cf
        )
        wind_useful_kwh = min(
            wind_kwh, annual_kwh * (target_load_pct / 100.0)
        )
        # infer approximate AC rating from annual kWh & CF
        approx_kw = wind_kwh / (8760 * wind_cf) if wind_cf > 0 else 0.0
        wind_capex = approx_kw * wind_cost_kw
        wind_savings = wind_useful_kwh * elec_rate
        wind_co2_t = wind_useful_kwh * grid_kg_per_kwh / 1000.0

        rows.append(
            {
                "Technology": f"Onshore Wind (land: {wind_acres:.0f} acres)",
                "Type": "On-site wind",
                "Capex_USD": wind_capex,
                "Annual_kWh": wind_kwh,
                "Load_Covered_%": wind_useful_kwh / annual_kwh * 100.0,
                "Annual_Savings_USD": wind_savings,
                "CO2e_Reduction_tpy": wind_co2_t,
                "Notes": (
                    "Acreage → MW density → kWh. Uses adjustable density & capacity factor above; "
                    "for real projects use pro-grade wind resource data."
                ),
            }
        )

    df = pd.DataFrame(rows)

    # ---------- Financial / performance metrics ----------
    df["Payback_yr"] = np.where(
        df["Annual_Savings_USD"] > 0,
        df["Capex_USD"] / df["Annual_Savings_USD"],
        np.inf,
    )

    # Normalize for scoring
    savings = df["Annual_Savings_USD"].clip(lower=0)
    co2 = df["CO2e_Reduction_tpy"].clip(lower=0)
    payback = df["Payback_yr"].replace([np.inf, 0], np.nan)

    max_s = savings.max() or 1.0
    max_c = co2.max() or 1.0
    min_p = payback.min() if not payback.isna().all() else np.nan

    norm_s = savings / max_s
    norm_c = co2 / max_c
    norm_p = np.where(
        payback.notna(),
        (min_p / payback).clip(lower=0, upper=1),
        0.0,
    )

    w_s, w_c, w_p = _goal_weights(goal)
    score = w_s * norm_s + w_c * norm_c + w_p * norm_p
    df["Score_0to1"] = score.fillna(0)

    return df.sort_values("Score_0to1", ascending=False).reset_index(drop=True), pvwatts_used_any


# ---------------- Main Page ----------------

def page_transition_generation():
    st.header("Transition Tech: Electricity Generation")
    st.caption(
        "Choose who you're planning for, confirm basic details, and explore renewable options "
        "with quick payback and CO₂ estimates. These are educational planning tools."
    )

    scen: ScenarioInput | None = st.session_state.get("scenario")
    if not scen:
        st.warning(
            "In the sidebar, fill out your location, building type, and annual electricity use "
            "to personalize these estimates."
        )
        return

    site = scen.site

    # ---------- Quick summary cards ----------
    col_summary1, col_summary2, col_summary3 = st.columns(3)
    with col_summary1:
        st.markdown("**Location**")
        st.write(f"{site.city or ''}, {site.state or ''} {site.zipcode or ''}")
    with col_summary2:
        st.markdown("**Annual electricity**")
        st.write(f"{(site.annual_electricity_kwh or 0):,.0f} kWh/yr")
        st.write(f"Rate: ${scen.elec_rate_usd_per_kwh:.3f}/kWh")
    with col_summary3:
        st.markdown("**Grid CO₂ intensity**")
        if scen.grid_emissions_kgco2e_per_kwh:
            st.write(f"{scen.grid_emissions_kgco2e_per_kwh:.3f} kg CO₂e/kWh")
        else:
            st.write("Not specified")

    st.markdown("---")

    # ---------- 1. Who & goal ----------
    st.markdown("### 1. Who are you planning for and what is your goal?")

    col_top1, col_top2 = st.columns([2, 1])
    with col_top1:
        category = st.radio(
            "Planning for",
            CATEGORY_LABELS,
            index=0,
            horizontal=True,
            key="tt_cat",
        )
        st.info(_category_flavor(category))
    with col_top2:
        goal = st.selectbox(
            "Primary objective",
            ["Balanced", "Lower my bill", "Maximize CO₂ reduction"],
            index=0,
            key="tt_goal",
        )
        target_load_pct = st.slider(
            "Target share of annual load to cover / green (%)",
            min_value=10,
            max_value=100,
            value=80,
            step=5,
            key="tt_target_load",
        )

    st.markdown("---")

    # ---------- 2. Check assumptions ----------
    st.markdown("### 2. Check location & siting assumptions")

    col_ctx1, col_ctx2 = st.columns([1.3, 1])
    with col_ctx1:
        st.markdown("**Site & building context**")
        st.write(f"- Building type: `{site.building_type or 'unspecified'}`")
        st.write(f"- Planning category: `{category}`")
        st.write(f"- Annual electricity: `{(site.annual_electricity_kwh or 0):,.0f} kWh/yr`")

    with col_ctx2:
        st.markdown("**Electricity & CO₂ (from sidebar)**")
        st.write(f"- Rate: `${scen.elec_rate_usd_per_kwh:.3f}`/kWh")
        if scen.grid_emissions_kgco2e_per_kwh:
            st.write(f"- Grid intensity: `{scen.grid_emissions_kgco2e_per_kwh:.3f} kg CO₂e/kWh`")
        else:
            st.write("- Grid intensity: `N/A`")

    with st.expander("PV & wind siting + cost assumptions (optional)", expanded=True):
        col_s1, col_s2, col_s3 = st.columns(3)
        with col_s1:
            tilt = st.number_input(
                "PV tilt (degrees)",
                min_value=0,
                max_value=60,
                value=27,
                key="tt_tilt",
            )
            shading = st.number_input(
                "PV shading (%)",
                min_value=0,
                max_value=50,
                value=8,
                key="tt_shade",
            )
            losses_pct = st.number_input(
                "PV system losses for PVWatts (%)",
                min_value=0.0,
                max_value=40.0,
                value=14.0,
                step=0.5,
                key="tt_pv_losses",
            )
        with col_s2:
            roof_area_m2 = st.number_input(
                "Approx. roof area available for PV (m²)",
                min_value=0,
                max_value=100_000,
                value=0,
                key="tt_roof",
            )
            pv_rooftop_cost_kw = st.number_input(
                "Rooftop PV installed cost (USD/kWdc)",
                min_value=500.0,
                max_value=10_000.0,
                value=PV_ROOFTOP_COST_PER_KW,
                step=100.0,
                key="tt_pv_roof_cost",
            )
            pv_ground_cost_kw = st.number_input(
                "Ground/carport PV cost (USD/kWdc)",
                min_value=500.0,
                max_value=10_000.0,
                value=PV_GROUND_COST_PER_KW,
                step=100.0,
                key="tt_pv_ground_cost",
            )
        with col_s3:
            wind_acres = st.number_input(
                "Land you could use for wind (acres)",
                min_value=0,
                max_value=100_000,
                value=0,
                key="tt_wind_acres",
            )
            wind_density_mw_km2 = st.number_input(
                "Wind installed capacity density (MW/km²)",
                min_value=0.0,
                max_value=30.0,
                value=WIND_DEFAULT_DENSITY_MW_PER_KM2,
                step=0.25,
                key="tt_wind_density",
            )
            wind_cf = st.number_input(
                "Wind capacity factor (0–1)",
                min_value=0.0,
                max_value=1.0,
                value=WIND_DEFAULT_CF,
                step=0.01,
                key="tt_wind_cf",
            )

        st.caption(
            "If you don't know roof area or land, leave them at zero and the tool will infer reasonable sizes "
            "from your annual kWh."
        )

    with st.expander("Community solar & green tariff assumptions (optional)", expanded=False):
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            community_solar_discount_frac = st.number_input(
                "Community solar bill discount (fraction of base rate)",
                min_value=0.0,
                max_value=0.50,
                value=COMMUNITY_SOLAR_DISCOUNT_FRAC,
                step=0.01,
                key="tt_cs_discount",
                help="0.10 = 10% cheaper than your normal rate on the subscribed share.",
            )
        with col_c2:
            green_premium_usd_per_kwh = st.number_input(
                "Green tariff premium (USD/kWh)",
                min_value=0.0,
                max_value=0.10,
                value=GREEN_PREMIUM_USD_PER_KWH,
                step=0.001,
                key="tt_green_premium",
                help="Typical ranges are 0–0.03 $/kWh for many green power programs.",
            )

    st.markdown("---")

    # ---------- 3. Rank options ----------
    st.markdown("### 3. Recommended generation options")

    df, pvwatts_used_any = _rank_options(
        category=category,
        scen=scen,
        tilt=tilt,
        shading=shading,
        roof_area_m2=roof_area_m2 if roof_area_m2 > 0 else None,
        wind_acres=wind_acres if wind_acres > 0 else None,
        goal=goal,
        target_load_pct=target_load_pct,
        wind_density_mw_km2=wind_density_mw_km2,
        wind_cf=wind_cf,
        pv_rooftop_cost_kw=pv_rooftop_cost_kw,
        pv_ground_cost_kw=pv_ground_cost_kw,
        wind_cost_kw=WIND_COST_PER_KW,
        green_premium_usd_per_kwh=green_premium_usd_per_kwh,
        community_solar_discount_frac=community_solar_discount_frac,
        pv_losses_pct=losses_pct,
    )

    if df.empty:
        st.warning("No options could be generated with the current inputs.")
        return

    top = df.iloc[0]
    second = df.iloc[1] if len(df) > 1 else None

    if pvwatts_used_any:
        st.success("PV results are using **NREL PVWatts** where possible, with classroom estimates as fallback.")
    else:
        st.info(
            "PV results are currently using **classroom rule-of-thumb** estimates. "
            "Add an NREL API key in `.streamlit/secrets.toml` (NREL_API_KEY) and provide a location "
            "to use PVWatts instead."
        )

    top_scores = df["Score_0to1"].head(2)
    score_sum = top_scores.sum() or 1.0
    conf = (top_scores / score_sum * 100).round(0).tolist()
    conf_top = conf[0]
    conf_second = conf[1] if len(conf) > 1 else None

    col_rec1, col_rec2 = st.columns([2, 1])
    with col_rec1:
        st.markdown("#### Best-fit option for your goal")
        st.metric("Top option", top["Technology"])
        st.write(
            f"- **Type**: {top['Type']}\n"
            f"- **Load coverage**: {top['Load_Covered_%']:.1f}% of annual load\n"
            f"- **Annual savings**: ${top['Annual_Savings_USD']:,.0f}/yr\n"
            f"- **Estimated CO₂ reduction**: {top['CO2e_Reduction_tpy']:.1f} tCO₂e/yr\n"
            f"- **Simple payback**: "
            f"{'N/A' if np.isinf(top['Payback_yr']) else f'{top['Payback_yr']:.1f} years'}"
        )

        if goal == "Lower my bill":
            st.info("Weights emphasize **bill savings**, so cheaper, high-savings options rise to the top.")
        elif goal == "Maximize CO₂ reduction":
            st.info("Weights emphasize **CO₂ reduction**, so options with big tCO₂ cuts dominate.")
        else:
            st.info("Weights are **balanced**, so you get a compromise between cost, savings, CO₂ and payback.")

        if second is not None:
            st.markdown("#### Runner-up to consider")
            st.write(
                f"- **{second['Technology']}** – covers {second['Load_Covered_%']:.1f}% of load, "
                f"saves about ${second['Annual_Savings_USD']:,.0f}/yr, "
                f"and avoids {second['CO2e_Reduction_tpy']:.1f} tCO₂e/yr."
            )

    with col_rec2:
        st.markdown("#### Relative ranking")
        top2 = df.head(2).copy()
        if len(top2) == 1:
            top2["Confidence_%"] = [100]
        else:
            top2["Confidence_%"] = conf

        fig_conf = px.bar(
            top2,
            x="Technology",
            y="Confidence_%",
            text="Confidence_%",
            title="Relative ranking of best options",
        )
        fig_conf.update_layout(
            yaxis_title="Score share (%)",
            xaxis_title="",
            margin=dict(l=10, r=10, t=40, b=40),
        )
        fig_conf.update_traces(textposition="outside")
        st.plotly_chart(fig_conf, width='stretch')

    st.markdown("---")

    # ---------- 4. Compare all options ----------
    st.markdown("### 4. Compare all technologies")

    display_cols = [
        "Technology",
        "Type",
        "Load_Covered_%",
        "Annual_kWh",
        "Annual_Savings_USD",
        "CO2e_Reduction_tpy",
        "Payback_yr",
        "Capex_USD",
        "Notes",
    ]
    df_display = df[display_cols].copy()
    df_display.rename(
        columns={
            "Load_Covered_%": "Load covered (%)",
            "Annual_kWh": "Annual generation (kWh/yr)",
            "Annual_Savings_USD": "Annual savings (USD/yr)",
            "CO2e_Reduction_tpy": "CO₂ reduction (t/yr)",
            "Payback_yr": "Simple payback (yr)",
            "Capex_USD": "Capex (USD)",
        },
        inplace=True,
    )
    st.dataframe(df_display, width='stretch')

    csv_data = df_display.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download results as CSV",
        data=csv_data,
        file_name="transition_generation_options.csv",
        mime="text/csv",
        key="tt_download_csv",
    )

    st.markdown("#### Visual comparison")

    col_viz1, col_viz2 = st.columns(2)
    with col_viz1:
        fig_co2 = px.scatter(
            df,
            x="Capex_USD",
            y="CO2e_Reduction_tpy",
            size=df["Annual_kWh"],
            color="Type",
            hover_name="Technology",
            labels={
                "Capex_USD": "Capex (USD)",
                "CO2e_Reduction_tpy": "CO₂ reduction (t/yr)",
                "Annual_kWh": "Annual generation (kWh/yr)",
            },
            title="Capex vs CO₂ reduction",
        )
        st.plotly_chart(fig_co2, width='stretch')

    with col_viz2:
        fig_cov = px.bar(
            df,
            x="Technology",
            y="Load_Covered_%",
            color="Type",
            labels={"Load_Covered_%": "Load covered (%)"},
            title="Share of annual load covered / greened",
        )
        fig_cov.update_layout(xaxis_title="", yaxis_title="Load covered (%)")
        st.plotly_chart(fig_cov, width='stretch')

    st.markdown("---")

    # ---------- 5. Optional: PVWatts-style detailed output ----------
    with st.expander("PVWatts detailed output for rooftop PV (optional)", expanded=False):
        nrel = NRELClient()
        if not nrel.available():
            st.warning("Set `NREL_API_KEY` in `.streamlit/secrets.toml` or your environment to use PVWatts here.")
        elif site.lat is None or site.lon is None:
            st.warning("Latitude/longitude are missing – add a location in the sidebar to run PVWatts.")
        else:
            # Reconstruct the rooftop system size with the same logic as ranking
            annual_kwh = float(site.annual_electricity_kwh or 10_000)
            if roof_area_m2 and roof_area_m2 > 0:
                kw_roof = max(0.0, roof_area_m2 * 0.2)
            else:
                kw_roof = max(1.0, round(annual_kwh / 1400.0, 1))

            st.markdown(
                f"Running PVWatts for a **{kw_roof:.1f} kWdc** rooftop system at "
                f"({site.lat:.3f}, {site.lon:.3f}), tilt **{tilt}°**, losses **{losses_pct:.1f}%**."
            )

            outputs = nrel.pvwatts_full(
                lat=site.lat,
                lon=site.lon,
                system_capacity_kw=kw_roof,
                tilt_deg=tilt,
                azimuth_deg=180.0,
                array_type=1,   # fixed open rack/roof
                module_type=1,  # standard
                losses_pct=losses_pct,
            )

            if outputs is None:
                st.error(f"PVWatts error: {nrel.last_error or 'Unknown error'}")
            else:
                ac_annual = outputs.get("ac_annual")
                dc_annual = outputs.get("dc_annual")
                solrad_annual = outputs.get("solrad_annual")
                ac_monthly = outputs.get("ac_monthly", [])
                dc_monthly = outputs.get("dc_monthly", [])
                solrad_monthly = outputs.get("solrad_monthly", [])

                months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
                df_pvw = pd.DataFrame(
                    {
                        "Month": months[: len(ac_monthly)],
                        "AC output (kWh)": ac_monthly,
                        "DC output (kWh)": dc_monthly if dc_monthly else [None] * len(ac_monthly),
                        "Solar irradiance (kWh/m²/day)": solrad_monthly if solrad_monthly else [None] * len(ac_monthly),
                    }
                )

                col_pvw1, col_pvw2 = st.columns(2)
                with col_pvw1:
                    if ac_annual is not None:
                        st.metric("Annual AC output", f"{ac_annual:,.0f} kWh/yr")
                    if solrad_annual is not None:
                        st.metric("Annual solar irradiance", f"{solrad_annual:.2f} kWh/m²/day")
                with col_pvw2:
                    if ac_annual is not None:
                        cf = ac_annual / (kw_roof * 8760.0)
                        st.metric("Approx. capacity factor", f"{cf*100:.1f}%")
                    if dc_annual is not None:
                        st.metric("Annual DC output", f"{dc_annual:,.0f} kWh/yr")

                st.markdown("##### Monthly PVWatts outputs (similar to NREL UI)")
                st.dataframe(df_pvw, width='stretch')

                csv_pvw = df_pvw.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "Download PVWatts monthly table as CSV",
                    data=csv_pvw,
                    file_name="pvwatts_monthly_output.csv",
                    mime="text/csv",
                    key="tt_pvwatts_download",
                )

                st.caption(
                    "Source: NREL PVWatts v8. This is the same engine behind the web tool, "
                    "just embedded in this app for easier use in assignments."
                )

    # ---------- 6. Quotes & resources ----------
    st.markdown("---")
    st.markdown("### 6. Get quotes & learn more")

    links = quote_links(site.state or "")
    if links:
        st.write("These links are **generic starting points** for quotes and more detailed design:")
        for label, url in links.items():
            st.markdown(f"- [{label}]({url})")
    else:
        st.write(
            "Add state-specific resources in `resources.quote_links` to surface local installers and tools here."
        )

    with st.expander("Classroom assumptions & how to improve them"):
        st.markdown(
            """
            - **PV**: NREL **PVWatts** when location + API key are available, else a rule-of-thumb:
              300 × GHI (kWh/m²-day) for kWh per kWdc-year.
            - **PV costs**: Defaults (e.g. 1800 $/kWdc rooftop, 1500 $/kWdc ground) are illustrative and adjustable above.
            - **Wind**: Capacity density and CF can be tuned; real projects need site-specific wind data.
            - **Community solar & green tariffs**: Bill credit and premium levels are placeholders; adjust to match real programs.
            - **CO₂**: Grid intensity comes from the sidebar scenario; for better accuracy, swap in eGRID-by-ZIP values.
            """
        )
        st.caption(
            "For homework, document which assumptions you changed and why. "
            "For real projects, every line above should be replaced by program- or site-specific numbers."
        )

    # ---------- Optional: PVWatts / NREL status ----------
    with st.expander("Technical: PVWatts / NREL API status", expanded=False):
        nrel = NRELClient()
        st.write(f"**NREL_API_KEY loaded**: {'✅ Yes' if nrel.available() else '❌ No'}")
        st.write(f"**Latitude / Longitude**: {site.lat}, {site.lon}")
        last_err = st.session_state.get("pvwatts_last_error")
        if last_err:
            st.write(f"**Last PVWatts error**: `{last_err}`")
        else:
            st.write("No PVWatts errors recorded this run.")
