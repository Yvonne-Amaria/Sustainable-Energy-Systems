# Project: Sustainable Energy Systems Solutions — Streamlit App (Feature 2: Transition Tech — Electricity Generation)

# app.py
from __future__ import annotations

import streamlit as st
import os
import requests
import numpy as np
import pandas as pd
import datetime as dt
import plotly.express as px
from typing import Optional

from models import Site, ScenarioInput
from data_connectors import DataConnectors
from recommender import Recommender
from tools import (
    pv_area_for_avg_power,
    capacity_factor,
    panel_efficiency,
    carbon_intensity_from_fc_hhv,
    carbon_intensity_from_formula,
    wind_region_potential,
    biomass_poplar_land_for_power,
    trucks_per_day,
    ev_tou_cost,
)
from eia_client import EIA
from guides import household_actions, policy_advocacy, incentive_blurbs
from ui_components import feature_card, pill, two_col_metrics, user_inputs_panel, note
from conversions import convert_value, UNITS, PREFIXES, conversion_quicktips
from feature_calculations import page_energy_calculations
from feature_transition_generation import page_transition_generation
from ideal_society import page_ideal_society

# ---------------------------------
# App State / Navigation
# ---------------------------------

PAGES = {
    "Home": "home",
    "Build Your Ideal Society (Game)": "ideal_society",
    "Assignment Tools": "homework",
    "Energy Calculations (Solver)": "calc",
    "Calculate Efficiency & PV": "pv_tools",
    "Conversion Factors & Units": "conversions",
    "Transition Tech: Electricity Generation": "transition_gen",
    "Transition Tech: Transportation": "transition_transport",
    "Transition Tech: Home Utilities": "home_utilities",
    "Fuel & Energy Data (EIA)": "eia",
    "Annual Energy Review": "monthly_review",
    "Carbon Sequestration": "sequestration",
    "AI, Education & Policy": "knowledge",
    "About": "about",
}


def _init_state():
    if "page" not in st.session_state:
        st.session_state.page = "home"
    if "scenario" not in st.session_state:
        st.session_state.scenario = None


# ---------------------------------
# Shared sidebar
# ---------------------------------

def sidebar_site() -> ScenarioInput:
    # ---------- NAVIGATION ----------
    with st.sidebar:
        st.markdown("###  Navigate features")

        # Figure out current page so the radio highlights the right one
        current_page_key = st.session_state.get("page", None)
        page_labels = list(PAGES.keys())
        page_keys = list(PAGES.values())

        if current_page_key and current_page_key in page_keys:
            current_index = page_keys.index(current_page_key)
        else:
            current_index = 0

        selected_label = st.radio(
            "Go to",
            page_labels,
            index=current_index,
            label_visibility="collapsed",
            key="nav_radio",
        )

        # Update the route when selection changes
        selected_route_key = PAGES[selected_label]
        if selected_route_key != current_page_key:
            _set_page(selected_route_key)

        st.markdown("---")

        # ---------- SITE / BUILDING / TARIFF ----------
        st.markdown("### Site, Building & Tariff")
        st.caption(
            "These inputs drive almost all calculations in the app. "
            "If you change them, the results on each feature page will update."
        )

        # Location block
        st.markdown("**Location**")
        col_loc1, col_loc2 = st.columns(2)
        with col_loc1:
            country = st.selectbox("Country", ["USA"], index=0, key="site_country")
            state = st.text_input("State", value="MI", help="Two-letter code (e.g., MI, CA, NY).", key="site_state")
        with col_loc2:
            zipcode = st.text_input("ZIP code", value="48202", key="site_zip")
            city = st.text_input("City (optional)", value="", key="site_city")

        # Geocode (best-effort; don't crash if it fails)
        try:
            lat, lon = DataConnectors.geocode(zipcode) if zipcode else (None, None)
        except Exception:
            lat, lon = None, None

        # Building block
        st.markdown("**Building / user type**")
        building_type = st.selectbox(
            "Building type",
            ["residential", "commercial", "industrial", "campus", "community"],
            index=0,
            key="site_bldg_type",
        )

        annual_kwh = st.number_input(
            "Annual electricity use (kWh)",
            min_value=0,
            value=10_000,
            step=500,
            key="site_annual_kwh",
            help="Rough annual kWh for the site. For homework, you can estimate from bills.",
        )

        # Tariff / emissions auto-fill
        base_rate_default = DataConnectors.utility_rate(Site(state=state))
        # Allow EIA page to override this via st.session_state["elec_rate_sidebar"]
        elec_rate_default = st.session_state.get("elec_rate_sidebar", base_rate_default)

        st.markdown("**Energy prices**")
        col_rates1, col_rates2 = st.columns(2)
        with col_rates1:
            elec_rate = st.number_input(
                "Electric rate (USD/kWh)",
                min_value=0.00,
                value=float(elec_rate_default or 0.00),
                step=0.01,
                key="elec_rate_sidebar",
            )
        with col_rates2:
            gas_rate = st.number_input(
                "Gas rate (USD/therm)",
                min_value=0.00,
                value=1.20,
                step=0.05,
                key="gas_rate_sidebar",
            )

        # Grid emissions (read-only, derived)
        try:
            grid_kg_per_kwh = DataConnectors.grid_emissions(Site(state=state, zipcode=zipcode))
        except Exception:
            grid_kg_per_kwh = None

        st.markdown("**Grid emissions (informational)**")
        if grid_kg_per_kwh is not None:
            st.caption(f"Estimated grid intensity: **{grid_kg_per_kwh:.3f} kg CO₂e/kWh** based on state/ZIP.")
        else:
            st.caption("Grid intensity: *not available* (falling back to defaults in calculations).")

        # Finance horizon (advanced, but still important)
        with st.expander("💰 Financial assumptions", expanded=False):
            col_fin1, col_fin2 = st.columns(2)
            with col_fin1:
                discount = st.slider(
                    "Discount rate",
                    min_value=0.01,
                    max_value=0.12,
                    value=0.07,
                    step=0.01,
                    key="site_discount_rate",
                    help="Used for NPV/LCOE-style calculations. 7% is a common classroom default.",
                )
            with col_fin2:
                years = st.slider(
                    "Analysis years",
                    min_value=10,
                    max_value=30,
                    value=25,
                    step=1,
                    key="site_analysis_years",
                    help="Typical ranges are 20–30 years for solar and major equipment.",
                )

        # Build objects
        site = Site(
            country=country,
            state=state,
            city=city or None,
            zipcode=zipcode or None,
            lat=lat,
            lon=lon,
            building_type=building_type,
            annual_electricity_kwh=annual_kwh,
        )
        scen = ScenarioInput(
            site=site,
            elec_rate_usd_per_kwh=elec_rate,
            gas_rate_usd_per_therm=gas_rate,
            discount_rate=discount,
            analysis_years=years,
            grid_emissions_kgco2e_per_kwh=grid_kg_per_kwh,
        )

        # Store in session for other pages
        st.session_state.scenario = scen

        # Tiny summary chip at the bottom
        st.markdown("---")
        st.caption(
            f"Current scenario: **{building_type}** in **{state} {zipcode or ''}**, "
            f"{annual_kwh:,} kWh/yr at ${elec_rate:.3f}/kWh."
        )

    return scen


# ---------------------------------
# Pages
# ---------------------------------

def page_home():
    scen: ScenarioInput | None = st.session_state.get("scenario", None)

    # ---------- Title + intro ----------
    st.title("Sustainable Energy Systems: Explore Energy Solutions and Prospects for Climate Stability")
    st.caption(
        "This app is a beginner friendly workspace for exploring sustainable energy systems: calculations for class, "
        "quick planning tools for buildings and transport, and background on policy, AI, and carbon."
    )

    col_hero1, col_hero2 = st.columns([2, 1])
    with col_hero1:
        st.markdown(
            """
            Use the sidebar to describe a site (location, building type, and energy use), then
            explore the tools below to:

            - Estimate energy use, costs, and emissions for common scenarios  
            - Compare options for electricity generation, transport, and home upgrades  
            - Read concise explanations of carbon sequestration and sustainability topics  
            """
        )
    with col_hero2:
        try:
            st.image("header.png", width='stretch')
        except Exception:
            pass  # stay quiet if the image is missing

    st.markdown("---")

    # ---------- Core tools ----------
    st.subheader("Core tools")

    col_core1, col_core2 = st.columns(2)
    with col_core1:
        feature_card(
            "Energy Calculations (Student)",
            "Set up common homework-style calculations with optional inputs, units, and EIA auto-fill.",
            on_click=lambda: _set_page("calc"),
            key="home_calc",
        )

        feature_card(
            "Electricity Generation Planning",
            "Compare rooftop PV, ground-mount, community solar, wind, and green power for a site.",
            on_click=lambda: _set_page("transition_gen"),
            key="home_transition_gen",
        )

        feature_card(
            "Transport & Mobility Planning",
            "Explore mode shift, EVs, and transit options for individuals, households, fleets, or communities.",
            on_click=lambda: _set_page("transition_transport"),
            key="home_transition_transport",
        )

    with col_core2:
        feature_card(
            "Home Utilities & Household",
            "Look at appliances, water heaters, plug loads, and practical actions for renters and owners.",
            on_click=lambda: _set_page("home_utilities"),
            key="home_home_utils",
        )

        feature_card(
            "Carbon Sequestration",
            "Work with formulas and simple calculators for biological sequestration, CCS, DAC, and mineralization.",
            on_click=lambda: _set_page("sequestration"),
            key="home_sequestration",
        )

        feature_card(
            "Build Your Ideal Sustainable Society",
            "A sandbox game to sketch an ideal building or community with energy systems, transport, and policies.",
            on_click=lambda: _set_page("ideal_society"),
            key="home_ideal_society",
        )

    st.markdown("---")

    # ---------- Data, conversions, and background ----------
    st.subheader("Data, conversions, and background")

    col_more1, col_more2 = st.columns(2)
    with col_more1:
        feature_card(
            "Conversions & Units",
            "Quick conversions (J ↔ Btu, kWh ↔ Btu, hp ↔ kW, area units, prefixes) for problem solving.",
            on_click=lambda: _set_page("conversions"),
            key="home_conv",
        )

        feature_card(
            "Fuel & Energy Data (EIA)",
            "Pull fuel prices and emission factors by year and state; export tables for assignments.",
            on_click=lambda: _set_page("eia"),
            key="home_eia",
        )

    with col_more2:
        feature_card(
            "AI, Policy & Sustainability",
            "Read short explanations and guidance on AI’s energy use, policy and incentives, and social dimensions.",
            on_click=lambda: _set_page("ai_sustainability"),
            key="home_ai_sust",
        )

        feature_card(
            "Annual Energy Review",
            "Browse summarized national energy statistics and download data for context in reports.",
            on_click=lambda: _set_page("monthly_review"),
            key="home_mer",
        )


def page_homework_tools():
    st.header("Assignment Tools & Formulas")
    st.caption(
        "This page groups key formulas and tools by assignment. "
        "Use it as a map to the calculators elsewhere in the app."
    )

    tabs = st.tabs([
        "A1 – Energy & Power",
        "A2 – Energy Accounting & MER",
        "A3 – Growth & Carbon Intensity",
        "A4 – Life-Cycle Energy",
        "A5 – Power Plant Economics",
        "A6 – Wind Energy",
        "A7 – Photovoltaic Electricity",
        "A8 – Biomass Energy",
        "A9 – Climate Wedges & EVs",
    ])

    # --- A1 ---
    with tabs[0]:
        st.subheader("Core relationships")
        st.latex(r"P = \frac{E}{t}")
        st.latex(r"E = P \, t")
        st.latex(r"\eta = \frac{W_{\text{out}}}{Q_{\text{in}}}")
        st.caption("Use the Conversion & Energy Calculations pages for numerical work.")

    # --- A2 ---
    with tabs[1]:
        st.subheader("Energy accounting basics")
        st.latex(r"\bar{P} = \frac{E_{\text{primary}}}{\Delta t}")
        st.latex(r"P_{\text{per capita}} = \frac{\bar{P}}{\text{population}}")
        st.latex(r"\text{Energy intensity} = \frac{E_{\text{primary}}}{\text{GDP}}")
        st.latex(r"\eta_{\text{elec}} = \frac{E_{\text{delivered}}}{E_{\text{delivered}} + E_{\text{losses}}}")
        st.info(
            "Use: Energy Calculations → (future A2 tab) and Fuel & Energy Data (EIA) "
            "to pull MER-style numbers."
        )

    # --- A3 ---
    with tabs[2]:
        st.subheader("Growth & doubling time")
        st.latex(r"E(t) = E_0 \, e^{r t}")
        st.latex(r"r \approx \frac{1}{t} \ln \left( \frac{E(t)}{E_0} \right)")
        st.latex(r"t_{\text{double}} = \frac{\ln 2}{r}")
        st.subheader("Fuel carbon intensity")
        st.latex(r"\text{CI} = \frac{f_C \cdot 44/12}{\text{HHV}}")
        st.latex(
            r"f_C = \frac{12 n_C}{12 n_C + 1 n_H} \quad \Rightarrow \quad "
            r"\text{CI} = \frac{f_C \cdot 44/12}{\text{HHV}}"
        )
        st.caption("Use: Energy Calculations → Fuel Carbon Intensity tab for the numeric CI calculations.")

    # --- A4 ---
    with tabs[3]:
        st.subheader("Total fuel cycle energy")
        st.latex(r"E_{\text{total}} = \alpha \, E_{\text{combustion}}")
        st.latex(r"\eta_{\text{LCA}} = \frac{E_{\text{delivered}}}{E_{\text{total}}}")
        st.caption(
            r"Here $\alpha$ is an upstream factor (>1) that accounts for mining, processing, and delivery."
        )

    # --- A5 ---
    with tabs[4]:
        st.subheader("Capital recovery & LCOE")
        st.latex(
            r"\text{CRF}(i, n) = \frac{i (1 + i)^n}{(1 + i)^n - 1}"
        )
        st.latex(
            r"\text{LCOE} = \frac{\text{CRF}_\text{eff} \, K}{8760 \, D} "
            r"+ \text{fuel cost per kWh} + \text{O\&M per kWh}"
        )
        st.caption(
            "Use: future Power Plant Economics tab (to be wired into Energy Calculations). "
            "Here K is capital cost per kW and D is duty factor (capacity factor)."
        )

    # --- A6 ---
    with tabs[5]:
        st.subheader("Wind power & capacity factor")
        st.latex(r"\bar{P} = \sum_v P(v) \, f(v)")
        st.latex(r"E_{\text{year}} = \bar{P} \times 8760")
        st.latex(r"\text{CF} = \frac{E_{\text{year}}}{P_{\text{rated}} \times 8760}")
        st.caption("Use: Calculate Efficiency & PV → Wind tab and Excel/CSV presets for A6.")

    # --- A7 ---
    with tabs[6]:
        st.subheader("PV sizing & capacity factor")
        st.latex(r"A = \frac{P_{\text{avg}} \cdot 24}{\eta \, G_{\text{year}}}")
        st.latex(r"\eta = \frac{P_{\text{out}}}{G \, A}")
        st.latex(r"\text{CF} = \frac{E_{\text{month}}}{P_{\text{AC}} \cdot 24 \cdot \text{days}}")
        st.caption("Use: Energy Calculations → Efficiency & PV tab and Calculate Efficiency & PV page.")

    # --- A8 ---
    with tabs[7]:
        st.subheader("Biomass electricity")
        st.latex(r"E_{\text{elec,year}} = P_{\text{plant}} \cdot 8760 \cdot \text{CF}")
        st.latex(r"E_{\text{biomass}} = \frac{E_{\text{elec,year}}}{\eta_{\text{net}}}")
        st.latex(
            r"A_{\text{land}} = \frac{E_{\text{biomass}}}{\text{HHV} \cdot Y} "
            r"\quad \text{where } Y = \text{yield (Mg/ha-yr)}"
        )
        st.caption("Use: Calculate Efficiency & PV → Biomass tab for the land and truck calculations.")

    # --- A9 ---
    with tabs[8]:
        st.subheader("Climate wedges & vehicle emissions")
        st.latex(r"E_{\text{veh}} = \text{VMT} \times \frac{1}{\text{mpg}} \times \text{EF}_{\text{fuel}}")
        st.latex(r"\Delta E_{\text{veh}} = E_{\text{baseline}} - E_{\text{new tech}}")
        st.latex(r"N_{\text{vehicles}} = \frac{1 \, \text{GtC/yr}}{\Delta E_{\text{veh}}}")
        st.caption(
            "Use: future A9 wedge tool plus EV Charging & Vehicle Transition for cost and usage modeling."
        )


def page_pv_tools():
    st.header("Calculate Efficiency & PV")
    t = st.tabs(["PV Area", "Monthly Capacity Factor", "Panel Efficiency", "Wind", "Biomass"])

    with t[0]:
        st.caption("PV system sizing formula:")
        st.latex(r"A = \frac{P_{\text{avg}} \cdot 24}{\eta \, G_{\text{year}}}")
        pavg_mw = st.number_input("Target average power (MW)", 0.0, 1000.0, 10.0)
        eta = st.number_input("PV conversion efficiency (0-1)", 0.00, 1.00, 0.23)
        G_year = st.number_input("Yearly avg solar resource G_year [kWh/m²-day]", 0.1, 12.0, 4.2)
        area_m2 = pv_area_for_avg_power(pavg_mw * 1000.0, eta, G_year)
        st.metric("Required PV area", f"{area_m2:,.0f} m²")

    with t[1]:
        st.caption("Monthly capacity factor formula:")
        st.latex(r"\text{CF} = \frac{E_{\text{month}}}{P_{\text{AC}} \cdot 24 \cdot \text{days}}")
        monthly_kwh = st.number_input("Monthly AC energy (kWh)", 0.0, 1e9, 1500.0)
        ac_kw = st.number_input("AC nameplate (kW)", 0.0, 1e6, 8.0)
        days = st.number_input("Days in month", 1, 31, 30)
        cf = capacity_factor(monthly_kwh, ac_kw, days)
        st.metric("Capacity Factor", f"{100 * cf:.1f}%")

    with t[2]:
        st.caption("Panel efficiency formula:")
        st.latex(r"\eta = \frac{P_{\text{out}}}{G \, A}")
        p = st.number_input("Peak power (W)", 0.0, 20000.0, 560.0)
        area = st.number_input("Panel area (m²)", 0.0, 10.0, 2.26)
        eta = panel_efficiency(p, area)
        st.metric("Module efficiency", f"{100 * eta:.2f}%")


    with t[3]:
        area = st.number_input("Region area (km²)", 0.0, 1e6, 1500.0)
        mw_density = st.number_input("Installed capacity density (MW/km²)", 0.0, 20.0, 4.25)
        cf = st.number_input("Capacity factor (0-1)", 0.0, 1.0, 0.40)
        twh = wind_region_potential(area, mw_density, cf)
        st.metric("Annual generation", f"{twh:.2f} TWh/yr")

    with t[4]:
        plant_mw = st.number_input("Plant net output (MW)", 0.0, 2000.0, 135.0)
        cf = st.number_input("Capacity factor (0-1)", 0.0, 1.0, 0.83)
        net_eff = st.number_input("Net electrical efficiency (J_e/J_fuel)", 0.0, 1.0, 0.372)
        HHV_kJkg = st.number_input("Biomass HHV (kJ/kg)", 0.0, 40000.0, 20270.0)
        yield_Mg_ha_yr = st.number_input("Avg annual dry yield (Mg/ha-yr)", 0.0, 100.0, 13.0)
        area_ha = biomass_poplar_land_for_power(net_eff, cf, plant_mw, HHV_kJkg, yield_Mg_ha_yr)
        st.metric("Required plantation area", f"{area_ha:,.0f} ha")
        kg_year = (plant_mw * 1e6 * 8760.0 * cf * 3.6) / net_eff * 1e6 / HHV_kJkg
        trucks = trucks_per_day(kg_year, kg_per_truck=18000.0)
        st.metric("Truckloads per day", f"{trucks:.0f} trucks/day")


def page_transition_transport(scen: ScenarioInput):
    st.header("Transition Tech: Transportation")
    st.caption(
        "Explore household travel changes, EV charging, community transit planning, and project rankings "
        "in one place."
    )

    # ---------- Scenario context ----------
    if scen is None:
        st.warning(
            "Fill out your site details in the sidebar (location, building type, utility rates) "
            "for location-aware costs and emissions. "
            "You can still use the household and community calculators with default assumptions."
        )
    else:
        site = scen.site
        with st.expander("Scenario context", expanded=False):
            col_ctx1, col_ctx2, col_ctx3 = st.columns(3)
            with col_ctx1:
                st.write("**Location**")
                st.write(f"{site.city or ''} {site.state or ''} {site.zipcode or ''}")
            with col_ctx2:
                st.write("**Building type**")
                st.write(site.building_type or "N/A")
            with col_ctx3:
                try:
                    st.write("**Grid CO₂ intensity**")
                    st.write(f"{scen.grid_emissions_kgco2e_per_kwh:.3f} kg CO₂/kWh")
                except Exception:
                    st.write("Using default grid assumptions.")

    st.markdown("---")

    # ---------- Main navigation (tabs) ----------
    tab_household, tab_ev, tab_community, tab_mcda = st.tabs(
        [
            "Household & Personal Travel",
            "EV Charging & Public Stations",
            "Community & Transit Planning",
            "Project Comparison (MCDA)",
        ]
    )

    # =====================================================================
    # TAB 1 – Household & personal travel
    # =====================================================================
    with tab_household:
        st.subheader("Household & Personal Travel")

        col1, col2 = st.columns(2)
        with col1:
            category = st.selectbox(
                "Planning for",
                ["Individual", "Household", "Fleet driver / company car"],
                index=1,
            )
            household_size = st.number_input("Household size", 1, 10, 2, key="hh_size")
            current_car_setup = st.selectbox(
                "Current car situation",
                [
                    "No car",
                    "1 small car",
                    "1 mid-size / SUV",
                    "2+ cars",
                    "Company / fleet vehicles",
                ],
                index=2,
                key="hh_car_setup",
            )
            daily_miles = st.number_input(
                "Average driving distance per day (miles)",
                min_value=0.0,
                max_value=300.0,
                value=30.0,
                key="hh_daily_miles",
            )
            context = st.selectbox(
                "Context",
                ["Urban, good transit", "Suburban", "Rural / limited transit"],
                index=1,
                key="hh_context",
            )
        with col2:
            transit_quality = st.slider(
                "Local transit quality (0 = none, 10 = excellent)",
                0,
                10,
                4,
                help="Rough sense of bus/rail frequency, coverage, and reliability.",
                key="hh_transit_quality",
            )
            car_dependence = st.slider(
                "How car-dependent is life right now?",
                0.0,
                1.0,
                0.8,
                help="0 = almost everything reachable without a car; 1 = car needed for almost every trip.",
                key="hh_car_dep",
            )
            shift_feasible = st.slider(
                "Trips that could realistically shift to walking/biking/transit (%)",
                0,
                100,
                40,
                key="hh_shift_feasible",
            )
            target_ev_share = st.slider(
                "Share of remaining car miles you want to electrify (%)",
                0,
                100,
                70,
                key="hh_ev_share",
            )

        st.markdown("##### Emissions assumptions")

        col3, col4 = st.columns(2)
        with col3:
            mpg = st.number_input(
                "Current vehicle fuel economy (mpg)",
                min_value=5.0,
                max_value=80.0,
                value=28.0,
                key="hh_mpg",
            )
            ev_eff_kwh_per_100_mi = st.number_input(
                "EV electricity use (kWh per 100 miles)",
                min_value=10.0,
                max_value=60.0,
                value=27.0,
                key="hh_ev_eff",
            )
        with col4:
            default_ci = 0.4
            if scen is not None and getattr(scen, "grid_emissions_kgco2e_per_kwh", None) is not None:
                default_ci = float(scen.grid_emissions_kgco2e_per_kwh)
            grid_intensity_kg_per_kwh = st.number_input(
                "Grid emissions intensity (kg CO₂ per kWh)",
                min_value=0.0,
                max_value=1.0,
                value=default_ci,
                help="Rough default; you can override with a local value if you know it.",
                key="hh_grid_ci",
            )

        # --- Emissions model ---
        annual_miles = daily_miles * 365.0
        gasoline_kg_per_gallon = 8.887  # EPA
        gasoline_kg_per_mile = gasoline_kg_per_gallon / max(mpg, 1e-9)

        baseline_kg = annual_miles * gasoline_kg_per_mile

        shift_frac = shift_feasible / 100.0
        ev_frac = target_ev_share / 100.0

        avoided_miles = annual_miles * shift_frac
        remaining_miles = annual_miles * (1.0 - shift_frac)
        ev_miles = remaining_miles * ev_frac
        gas_miles = remaining_miles * (1.0 - ev_frac)

        ev_kwh = ev_miles * (ev_eff_kwh_per_100_mi / 100.0)
        ev_kg = ev_kwh * grid_intensity_kg_per_kwh
        gas_kg = gas_miles * gasoline_kg_per_mile

        target_kg = ev_kg + gas_kg

        baseline_t = baseline_kg / 1000.0
        target_t = target_kg / 1000.0
        reduction_t = baseline_t - target_t

        two_col_metrics(
            [
                ("Baseline transport emissions", f"{baseline_t:,.2f} tCO₂/yr"),
                ("After changes", f"{target_t:,.2f} tCO₂/yr"),
            ],
            [
                ("Annual reduction", f"{max(reduction_t, 0):,.2f} tCO₂/yr"),
                ("Miles avoided (mode shift)", f"{avoided_miles:,.0f} mi/yr"),
            ],
        )
        st.caption("Educational calculator – direct tailpipe + EV electricity only (no full lifecycle).")

        st.markdown("##### What this suggests for you")

        suggestions = []

        if shift_feasible >= 50 and car_dependence <= 0.6 and context != "Rural / limited transit":
            suggestions.append(
                "Realistic path to a **one-car or no-car household**, leaning heavily on bus/rail and biking."
            )
        elif target_ev_share >= 60:
            suggestions.append(
                "A **small battery EV** plus more walking/biking for short trips is a strong fit."
            )
        else:
            suggestions.append(
                "Start with **reducing unnecessary car trips** and **right-sizing** to the most efficient vehicle."
            )

        if transit_quality >= 7:
            suggestions.append(
                "With strong transit, many commute trips can move to **bus / light rail / commuter rail**. "
                "Using a **monthly pass** instead of pay-per-ride often saves money."
            )
        elif transit_quality >= 3:
            suggestions.append(
                "Transit is usable some of the time – try **peak-hour bus routes or rail** and combine with "
                "**bike/scooter** for first/last mile."
            )
        else:
            suggestions.append(
                "Transit is limited – prioritize **carpooling/vanpool**, telework where possible, and moving at "
                "least one vehicle to a **hybrid or EV**."
            )

        for s in suggestions:
            st.write(f"- {s}")

    # =====================================================================
    # TAB 2 – EV charging & public stations
    # =====================================================================
    with tab_ev:
        st.subheader("EV Charging & Public Stations")

        col_ev1, col_ev2 = st.columns(2)
        with col_ev1:
            batt_kwh = st.number_input(
                "EV battery size (kWh)",
                min_value=0.0,
                max_value=200.0,
                value=60.0,
                key="ev_batt_kwh",
            )
            soc_deplete = st.slider(
                "Typical daily depletion (state-of-charge fraction)",
                0.0,
                1.0,
                0.5,
                key="ev_soc_deplete",
            )
            days_between_fullish = st.slider(
                "Days between full-ish charges",
                1,
                14,
                2,
                help="For example, if you fully charge every 2 days, this is 2.",
                key="ev_days_between",
            )
        with col_ev2:
            start_hour = st.number_input(
                "Charge start time (hour of day, 0–23)",
                0,
                23,
                22,
                key="ev_start_hour",
            )
            charger_kw = st.selectbox(
                "Home charger power",
                [1.0, 3.3, 7.0, 11.0],
                index=2,
                key="ev_charger_kw",
            )
            default_ci_ev = 0.4
            if scen is not None and getattr(scen, "grid_emissions_kgco2e_per_kwh", None) is not None:
                default_ci_ev = float(scen.grid_emissions_kgco2e_per_kwh)
            grid_intensity_kg_per_kwh_ev = st.number_input(
                "Grid emissions intensity for EV (kg CO₂ per kWh)",
                0.0,
                1.0,
                default_ci_ev,
                key="ev_grid_ci",
            )

        kwh_per_session = batt_kwh * soc_deplete
        hours_per_session = kwh_per_session / max(charger_kw, 1e-9)
        sessions_per_month = 30.0 / float(days_between_fullish)
        kwh_per_month = kwh_per_session * sessions_per_month
        ev_emissions_t_per_year = (kwh_per_month * 12.0 * grid_intensity_kg_per_kwh_ev) / 1000.0

        planA = [((7, 11), 0.14), ((11, 19), 0.25), ((19, 24), 0.14), ((0, 7), 0.14)]
        planB = [((23, 24), 0.14), ((0, 7), 0.14), ((7, 15), 0.18), ((15, 19), 0.26), ((19, 23), 0.18)]

        costA_session = ev_tou_cost(kwh_per_session, start_hour, charger_kw, planA)
        costB_session = ev_tou_cost(kwh_per_session, start_hour, charger_kw, planB)

        costA_month = costA_session * sessions_per_month
        costB_month = costB_session * sessions_per_month

        cheaper = "Plan A (off-peak heavy)" if costA_month <= costB_month else "Plan B (steeper peak pricing)"

        two_col_metrics(
            [
                ("Energy per session", f"{kwh_per_session:,.1f} kWh"),
                ("Time per session", f"{hours_per_session:,.1f} hours"),
                ("Sessions per month", f"{sessions_per_month:,.1f}"),
            ],
            [
                ("Monthly cost – Plan A", f"${costA_month:,.2f}"),
                ("Monthly cost – Plan B", f"${costB_month:,.2f}"),
                ("Approx. EV emissions", f"{ev_emissions_t_per_year:,.2f} tCO₂/yr"),
            ],
        )

        st.info(f"With these assumptions, **{cheaper}** is cheaper for home charging.")

        st.markdown("##### Nearby public charging")

        if scen is None:
            st.warning("Enter a ZIP / location in the sidebar so we can look up nearby stations.")
        else:
            site = scen.site
            lat = getattr(site, "lat", None)
            lon = getattr(site, "lon", None)

            if not (lat and lon):
                st.warning("Enter a ZIP / location in the sidebar so we can look up nearby stations.")
            else:
                api_key = st.secrets.get("NREL_API_KEY", None) or os.getenv("NREL_API_KEY")

                if not api_key:
                    st.warning(
                        "Add `NREL_API_KEY` to `.streamlit/secrets.toml` or as an environment variable "
                        "to enable live lookup from NREL's Alternative Fuels API.\n\n"
                        "Example in `.streamlit/secrets.toml`:\n\n"
                        "```toml\nNREL_API_KEY = \"YOUR_REAL_KEY_HERE\"\n```"
                    )
                else:
                    radius = st.slider(
                        "Search radius (miles)",
                        1,
                        50,
                        10,
                        step=1,
                        key="ev_station_radius",
                    )

                    try:
                        params = {
                            "api_key": api_key,
                            "fuel_type": "ELEC",
                            "latitude": lat,
                            "longitude": lon,
                            "radius": radius,
                            "limit": 25,
                        }
                        resp = requests.get(
                            "https://developer.nrel.gov/api/alt-fuel-stations/v1/nearest.json",
                            params=params,
                            timeout=10,
                        )
                        resp.raise_for_status()
                        data = resp.json()
                        stations = data.get("fuel_stations", [])
                    except Exception as e:
                        st.error(f"Error calling NREL Alt Fuels API: {e}")
                        stations = []

                    if not stations:
                        st.info("No public charging stations found within this radius.")
                    else:
                        for stn in stations:
                            name = stn.get("station_name", "Charging station")
                            with st.expander(name):
                                addr = stn.get("street_address", "")
                                city = stn.get("city", "")
                                state = stn.get("state", "")
                                zipc = stn.get("zip", "")
                                st.write(f"{addr}")
                                st.write(f"{city}, {state} {zipc}")

                                network = stn.get("ev_network") or "Unknown network"
                                st.write(f"**Network:** {network}")

                                ev_level = []
                                if stn.get("ev_level1_evse_num"):
                                    ev_level.append("Level 1")
                                if stn.get("ev_level2_evse_num"):
                                    ev_level.append("Level 2")
                                if stn.get("ev_dc_fast_num"):
                                    ev_level.append("DC fast")
                                if ev_level:
                                    st.write("**Charging levels:** " + ", ".join(ev_level))

                                connectors = stn.get("ev_connector_types")
                                if connectors:
                                    st.write("**Connector types:** " + ", ".join(connectors))

    # =====================================================================
    # TAB 3 – Community & transit planning
    # =====================================================================
    with tab_community:
        st.subheader("Community & Transit Planning")

        col_c1, col_c2 = st.columns(2)
        with col_c1:
            population = st.number_input(
                "Population (residents / students / workers)",
                1_000,
                20_000_000,
                50_000,
                step=1_000,
                key="city_pop",
            )
            trips_per_person = st.number_input(
                "Average motorized trips per person per day",
                0.0,
                10.0,
                2.0,
                key="city_trips_per_person",
            )
            avg_trip_miles = st.number_input(
                "Average trip length (miles)",
                0.1,
                50.0,
                7.0,
                key="city_trip_length",
            )
        with col_c2:
            car_share_base = st.slider(
                "Car share – baseline (%)",
                0,
                100,
                70,
                key="city_car_base",
            )
            transit_share_base = st.slider(
                "Public transit share – baseline (%)",
                0,
                100,
                20,
                key="city_transit_base",
            )
            active_share_base = st.slider(
                "Walk / bike / micromobility share – baseline (%)",
                0,
                100,
                10,
                key="city_active_base",
            )
            total_base = car_share_base + transit_share_base + active_share_base
            st.caption(f"Baseline mode-share total: **{total_base}%** (normalized to 100% in calculations).")

        st.markdown("##### Target mode share")

        col_c3, col_c4 = st.columns(2)
        with col_c3:
            car_share_target = st.slider(
                "Car share – target (%)",
                0,
                100,
                40,
                key="city_car_target",
            )
            transit_share_target = st.slider(
                "Public transit share – target (%)",
                0,
                100,
                35,
                key="city_transit_target",
            )
        with col_c4:
            active_share_target = st.slider(
                "Walk / bike / micromobility share – target (%)",
                0,
                100,
                25,
                key="city_active_target",
            )
            total_target = car_share_target + transit_share_target + active_share_target
            st.caption(f"Target mode-share total: **{total_target}%** (normalized to 100% in calculations).")

        # Emissions factors
        car_kg_per_mile = 0.404
        transit_kg_per_mile = 0.18
        active_kg_per_mile = 0.0

        def _compute_emissions(car_share, transit_share, active_share):
            total = car_share + transit_share + active_share
            if total <= 0:
                return 0.0

            car_frac = car_share / total
            transit_frac = transit_share / total
            active_frac = active_share / total

            daily_passenger_miles = population * trips_per_person * avg_trip_miles
            annual_passenger_miles = daily_passenger_miles * 365.0

            car_miles = annual_passenger_miles * car_frac
            transit_miles = annual_passenger_miles * transit_frac
            active_miles = annual_passenger_miles * active_frac

            kg = (
                car_miles * car_kg_per_mile
                + transit_miles * transit_kg_per_mile
                + active_miles * active_kg_per_mile
            )
            return kg / 1000.0  # tCO₂/yr

        baseline_t_city = _compute_emissions(
            car_share_base, transit_share_base, active_share_base
        )
        target_t_city = _compute_emissions(
            car_share_target, transit_share_target, active_share_target
        )
        reduction_t_city = baseline_t_city - target_t_city

        two_col_metrics(
            [
                ("Baseline transport emissions", f"{baseline_t_city:,.0f} tCO₂/yr"),
                ("After mode shift", f"{target_t_city:,.0f} tCO₂/yr"),
            ],
            [
                ("Annual reduction", f"{max(reduction_t_city, 0):,.0f} tCO₂/yr"),
                (
                    "Per-person reduction",
                    f"{max(reduction_t_city, 0) * 1000.0 / max(population, 1):,.1f} kgCO₂/person·yr",
                ),
            ],
        )

        st.caption(
            "Use this as a rough check of how shifting trips out of private cars and into transit/active modes "
            "changes community-wide emissions."
        )

        st.markdown("##### Bus, rail, and community transit ideas")

        # Re-use transit_quality if user set it on household tab, else default 4
        tq = st.session_state.get("hh_transit_quality", 4)

        if tq >= 7:
            st.success(
                "Transit quality is high – priorities can include:\n"
                "- **Frequent bus / light rail** on core corridors.\n"
                "- **Car-light or car-free districts** near major stations.\n"
                "- Strong **integration with bike lanes and safe crossings** around stops.\n"
            )
        elif tq >= 3:
            st.info(
                "Transit quality is moderate – helpful next steps:\n"
                "- Upgrade key routes into **frequent bus lines or bus rapid transit (BRT)**.\n"
                "- Improve **first/last mile** with bike lanes, scooters, and safe sidewalks.\n"
                "- Add **transit signal priority** and bus-only lanes on congested segments.\n"
            )
        else:
            st.warning(
                "Transit is limited – focus on:\n"
                "- **Microtransit, community shuttles, and demand-responsive services**.\n"
                "- **Park-and-ride** facilities paired with any regional rail/bus.\n"
                "- Long-term, building a core **frequent bus spine** with good sidewalks.\n"
            )

    # =====================================================================
    # TAB 4 – MCDA project comparison (Recommender)
    # =====================================================================
    with tab_mcda:
        st.subheader("Project Comparison (MCDA – Transport Options)")

        if scen is None:
            st.warning(
                "MCDA uses your scenario details. Fill out the sidebar to enable this view."
            )
            return

        col_w1, col_w2, col_w3, col_w4 = st.columns(4)
        with col_w1:
            w_cost_raw = st.slider(
                "Upfront cost importance",
                0, 10, 3,
                help="Higher = you care more about keeping upfront cost low.",
                key="trn_trans_cost",
            )
        with col_w2:
            w_sav_raw = st.slider(
                "Annual cost savings importance",
                0, 10, 7,
                help="Higher = you care more about lower fuel/operating costs.",
                key="trn_trans_sav",
            )
        with col_w3:
            w_co2_raw = st.slider(
                "CO₂ reduction importance",
                0, 10, 8,
                help="Higher = you care more about cutting transport emissions.",
                key="trn_trans_co2",
            )
        with col_w4:
            w_pay_raw = st.slider(
                "Simple payback importance",
                0, 10, 4,
                help="Higher = you dislike long payback periods.",
                key="trn_trans_pay",
            )

        raw_vec = np.array([w_cost_raw, w_sav_raw, w_co2_raw, w_pay_raw], dtype=float)
        raw_sum = raw_vec.sum()
        if raw_sum == 0:
            weights = np.array([0.2, 0.4, 0.3, 0.1], dtype=float)
        else:
            weights = raw_vec / raw_sum
        w_cost, w_sav, w_co2, w_pay = weights.tolist()

        st.caption(
            f"Normalized weights → Cost: **{w_cost:.2f}**, Savings: **{w_sav:.2f}**, "
            f"CO₂: **{w_co2:.2f}**, Payback: **{w_pay:.2f}**."
        )

        try:
            df_all = Recommender.score_options(scen)
        except Exception as e:
            st.error(f"Error running Recommender.score_options: {e}")
            return

        if df_all is None or df_all.empty:
            st.warning("The recommender did not return any options for this scenario.")
            return

        if "Option" not in df_all.columns:
            st.error("Recommender output is missing an 'Option' column.")
            st.dataframe(df_all, width='stretch')
            return

        transport_keywords = [
            "transport", "vehicle", "EV", "car", "fleet", "transit",
            "bus", "rail", "bike", "biking", "walking",
        ]

        mask_trans = df_all["Option"].str.contains(
            "|".join(transport_keywords), case=False, na=False
        )

        if "Category" in df_all.columns:
            cat_mask = df_all["Category"].str.contains(
                "transport|vehicle|mobility", case=False, na=False
            )
            mask_trans = mask_trans | cat_mask

        df = df_all[mask_trans].copy()

        if df.empty:
            st.info(
                "The recommender did not return any obviously transport-related options.\n\n"
                "- Make sure `Recommender.score_options` defines transport measures with "
                "`Category='transport'` and EV / transit wording in the `Option` names.\n"
                "- Once those rows exist, this section will auto-populate with scores."
            )
            return

        required_cols = [
            "Capex_USD",
            "Annual_Savings_USD",
            "Simple_Payback_yr",
            "CO2e_Reduction_tpy",
        ]
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            st.error(f"Transport view is missing required column(s): {missing}")
            st.dataframe(df, width='stretch')
            return

        capex = df["Capex_USD"].clip(lower=0)
        savings = df["Annual_Savings_USD"].clip(lower=0)
        co2 = df["CO2e_Reduction_tpy"].clip(lower=0)
        payback = df["Simple_Payback_yr"].replace([np.inf, 0], np.nan)

        def _norm_positive(x: pd.Series) -> pd.Series:
            m = x.max()
            return x / m if m and m > 0 else x * 0.0

        def _norm_cost(x: pd.Series) -> pd.Series:
            m = x.min()
            if m and m > 0:
                return (m / x).clip(0, 1)
            return x * 0.0

        norm_sav = _norm_positive(savings)
        norm_co2 = _norm_positive(co2)
        norm_cost = _norm_cost(capex)
        norm_pay = _norm_cost(payback)

        custom_score = (
            w_cost * norm_cost.fillna(0)
            + w_sav * norm_sav.fillna(0)
            + w_co2 * norm_co2.fillna(0)
            + w_pay * norm_pay.fillna(0)
        )

        df["Custom_Score_0to1"] = custom_score
        has_mcda = "MCDA_Score_0to1" in df.columns

        df_sorted = df.sort_values("Custom_Score_0to1", ascending=False).reset_index(drop=True)
        top = df_sorted.iloc[0]
        second = df_sorted.iloc[1] if len(df_sorted) > 1 else None

        col_top1, col_top2 = st.columns([2, 1])
        with col_top1:
            st.markdown("##### Best-fit option")
            st.metric("Top option", top["Option"])

            payback_val = top["Simple_Payback_yr"]
            payback_str = "N/A" if np.isinf(payback_val) else f"{payback_val:.1f} years"

            st.write(
                f"- **Custom score**: {top['Custom_Score_0to1']:.2f}\n"
                + (f"- **Original MCDA score**: {top['MCDA_Score_0to1']:.2f}\n" if has_mcda else "")
                + f"- **Capex**: ${top['Capex_USD']:,.0f}\n"
                f"- **Annual savings**: ${top['Annual_Savings_USD']:,.0f}/yr\n"
                f"- **Simple payback**: {payback_str}\n"
                f"- **CO₂ reduction**: {top['CO2e_Reduction_tpy']:.2f} tCO₂e/yr"
            )

        with col_top2:
            st.markdown("##### Score comparison (top 2)")
            top2 = df_sorted.head(2).copy()
            if len(top2) == 1:
                top2["Custom_Score_%"] = 100.0
            else:
                s = top2["Custom_Score_0to1"]
                s_sum = s.sum() or 1.0
                top2["Custom_Score_%"] = (s / s_sum * 100.0).round(1)

            fig_score = px.bar(
                top2,
                x="Option",
                y="Custom_Score_%",
                text="Custom_Score_%",
                labels={"Custom_Score_%": "Relative score (%)"},
                title="Relative ranking of top transport options",
            )
            fig_score.update_traces(textposition="outside")
            fig_score.update_layout(xaxis_title="", yaxis_title="Score (%)")
            st.plotly_chart(fig_score, width='stretch')

        st.markdown("##### All transport-related options (sortable)")
        st.dataframe(
            df_sorted[
                [
                    "Option",
                    "Category",
                    "Capex_USD",
                    "Annual_Savings_USD",
                    "Simple_Payback_yr",
                    "CO2e_Reduction_tpy",
                    "Custom_Score_0to1",
                ]
                + (["MCDA_Score_0to1"] if has_mcda else [])
            ],
            width='stretch',
        )

def page_home_utilities(scen: ScenarioInput | None):
    st.header("Home Utilities, Appliances & Household Sustainability")
    st.caption(
        "Plan upgrades, run quick appliance calculations, and explore practical actions for renters and owners."
    )

    # Optional context – helps tie recommendations to the scenario
    if scen is not None:
        site = scen.site
        with st.expander("Scenario context (optional)", expanded=False):
            col1, col2, col3 = st.columns(3)
            with col1:
                st.write("**Location**")
                st.write(f"{site.city or ''} {site.state or ''} {site.zipcode or ''}")
            with col2:
                st.write("**Building type**")
                st.write(site.building_type or "N/A")
            with col3:
                try:
                    st.write("**Grid CO₂ intensity**")
                    st.write(f"{scen.grid_emissions_kgco2e_per_kwh:.3f} kg CO₂/kWh")
                except Exception:
                    st.write("N/A")

    tab_plan, tab_calcs, tab_guide = st.tabs(
        ["Upgrade Planner", "Appliance & Utility Calculators", "Household Guide"]
    )

    # =====================================================================
    # TAB 1 – Upgrade Planner (MCDA over efficiency + utilities)
    # =====================================================================
    with tab_plan:
        st.subheader("Upgrade Planner")

        st.markdown(
            "Use this tab to prioritize **home utilities and appliance upgrades** based on your goals: "
            "lower bills, comfort, emissions, or payback."
        )

        col0, col1, col2 = st.columns([1.2, 1, 1])
        with col0:
            occupant_type = st.selectbox(
                "I am a...",
                ["Renter", "Homeowner", "Campus housing / dorm", "Small business"],
                index=1,
                key="home_occ_type",
            )
        with col1:
            budget_level = st.selectbox(
                "Budget level",
                ["Very limited", "Moderate", "Can invest for long-term"],
                index=1,
                key="home_budget_level",
            )
        with col2:
            time_horizon = st.selectbox(
                "Time horizon for upgrades",
                ["Next 6–12 months", "Next 3–5 years", "Next 10–20 years"],
                index=1,
                key="home_time_horizon",
            )

        st.markdown("#### What matters most to you? (weights for recommendations)")

        colw1, colw2, colw3, colw4 = st.columns(4)
        with colw1:
            w_cost_raw = st.slider(
                "Low upfront cost",
                0, 10, 5,
                key="home_w_cost",
            )
        with colw2:
            w_sav_raw = st.slider(
                "Lower bills",
                0, 10, 8,
                key="home_w_sav",
            )
        with colw3:
            w_co2_raw = st.slider(
                "CO₂ reduction",
                0, 10, 7,
                key="home_w_co2",
            )
        with colw4:
            w_pay_raw = st.slider(
                "Short payback",
                0, 10, 6,
                key="home_w_pay",
            )

        raw_vec = np.array([w_cost_raw, w_sav_raw, w_co2_raw, w_pay_raw], dtype=float)
        raw_sum = raw_vec.sum()
        if raw_sum == 0:
            weights = np.array([0.25, 0.25, 0.25, 0.25], dtype=float)
        else:
            weights = raw_vec / raw_sum
        w_cost, w_sav, w_co2, w_pay = weights.tolist()

        st.caption(
            f"Normalized weights → Upfront cost: **{w_cost:.2f}**, Bills: **{w_sav:.2f}**, "
            f"CO₂: **{w_co2:.2f}**, Payback: **{w_pay:.2f}**."
        )

        if scen is None:
            st.warning(
                "Fill out site details in the sidebar to enable data-based recommendations "
                "(electricity rates, grid CO₂, etc.)."
            )
        else:
            # --- Get recommender options and filter to utilities/efficiency ---
            try:
                df_all = Recommender.score_options(scen)
            except Exception as e:
                st.error(f"Error running Recommender.score_options: {e}")
                df_all = None

            if df_all is None or df_all.empty:
                st.warning("No options returned by the recommender for this scenario.")
            else:
                if "Category" not in df_all.columns:
                    st.error("Recommender output is missing a 'Category' column.")
                    st.dataframe(df_all, width='stretch')
                else:
                    mask = df_all["Category"].str.contains(
                        "efficiency|utilities|appliance|heat pump|water heater",
                        case=False,
                        na=False,
                    )
                    df = df_all[mask].copy()

                    if df.empty:
                        st.info(
                            "No obviously utilities/appliance-related rows found in the Recommender.\n\n"
                            "Make sure some rows have Category like 'efficiency' or 'utilities'."
                        )
                    else:
                        required_cols = [
                            "Capex_USD",
                            "Annual_Savings_USD",
                            "Simple_Payback_yr",
                            "CO2e_Reduction_tpy",
                        ]
                        missing = [c for c in required_cols if c not in df.columns]
                        if missing:
                            st.error(f"Missing required column(s): {missing}")
                            st.dataframe(df, width='stretch')
                        else:
                            capex = df["Capex_USD"].clip(lower=0)
                            savings = df["Annual_Savings_USD"].clip(lower=0)
                            co2 = df["CO2e_Reduction_tpy"].clip(lower=0)
                            payback = df["Simple_Payback_yr"].replace([np.inf, 0], np.nan)

                            def _norm_positive(x: pd.Series) -> pd.Series:
                                m = x.max()
                                return x / m if m and m > 0 else x * 0.0

                            def _norm_cost(x: pd.Series) -> pd.Series:
                                m = x.min()
                                if m and m > 0:
                                    return (m / x).clip(0, 1)
                                return x * 0.0

                            norm_sav = _norm_positive(savings)
                            norm_co2 = _norm_positive(co2)
                            norm_cost = _norm_cost(capex)
                            norm_pay = _norm_cost(payback)

                            custom_score = (
                                w_cost * norm_cost.fillna(0)
                                + w_sav * norm_sav.fillna(0)
                                + w_co2 * norm_co2.fillna(0)
                                + w_pay * norm_pay.fillna(0)
                            )

                            df["Custom_Score_0to1"] = custom_score
                            df_sorted = df.sort_values("Custom_Score_0to1", ascending=False).reset_index(drop=True)

                            st.markdown("#### Recommended upgrades (top 3)")

                            top_n = min(3, len(df_sorted))
                            for i in range(top_n):
                                row = df_sorted.iloc[i]
                                with st.expander(f"{i+1}. {row['Option']}"):
                                    st.write(
                                        f"- **Category:** {row.get('Category', 'N/A')}\n"
                                        f"- **Capex:** ${row['Capex_USD']:,.0f}\n"
                                        f"- **Annual savings:** ${row['Annual_Savings_USD']:,.0f}/yr\n"
                                        f"- **Simple payback:** "
                                        f"{'N/A' if np.isinf(row['Simple_Payback_yr']) else f'{row['Simple_Payback_yr']:.1f} years'}\n"
                                        f"- **CO₂ reduction:** {row['CO2e_Reduction_tpy']:.2f} tCO₂/yr\n"
                                        f"- **Score (0–1):** {row['Custom_Score_0to1']:.2f}"
                                    )

                                    # Quick qualitative guidance
                                    if occupant_type == "Renter":
                                        st.info(
                                            "As a renter, focus on **low-commitment measures** first "
                                            "(smart strips, LEDs, smart thermostats where allowed, fridge settings, plugs), "
                                            "and coordinate with your landlord for bigger upgrades like heat pumps."
                                        )
                                    else:
                                        st.info(
                                            "As an owner, you can bundle this with other work (roofing, HVAC replacement) "
                                            "to reduce disruption and sometimes access better incentives."
                                        )

                            st.markdown("#### All utilities/efficiency options (sortable)")
                            st.dataframe(
                                df_sorted[
                                    [
                                        "Option",
                                        "Category",
                                        "Capex_USD",
                                        "Annual_Savings_USD",
                                        "Simple_Payback_yr",
                                        "CO2e_Reduction_tpy",
                                        "Custom_Score_0to1",
                                    ]
                                ],
                                width='stretch',
                            )

    # =====================================================================
    # TAB 2 – Appliance & Utility Calculators
    # =====================================================================
    with tab_calcs:
        st.subheader("Appliance & Utility Calculators")
        st.caption("Quick, order-of-magnitude tools – good for homework and sanity checks.")

        calc_choice = st.radio(
            "Choose a calculator",
            ["Heat pump water heater vs electric", "Lighting: old bulbs vs LED", "Plug / standby load"],
            key="home_calc_choice",
        )

        # ---------------------------------------------------------------
        # Heat pump WH vs electric resistance
        # ---------------------------------------------------------------
        if calc_choice == "Heat pump water heater vs electric":
            st.markdown("### Heat pump water heater vs electric resistance")

            st.latex(
                r"E_{\text{annual}} = \frac{m_{\text{water}} \, c_p \, \Delta T \, 365}{\eta \, 3.6 \times 10^6}"
            )
            st.caption(
                "Annual electrical energy E_annual [kWh] depends on water use, temperature rise, "
                "and efficiency (η or COP). We’ll use a simplified approach here."
            )

            col1, col2 = st.columns(2)
            with col1:
                gallons_per_day = st.number_input(
                    "Hot water use (gallons/day)",
                    min_value=0.0,
                    max_value=500.0,
                    value=60.0,
                    step=5.0,
                    key="hpwh_gal_day",
                )
                temp_rise_F = st.number_input(
                    "Temperature rise (°F)",
                    min_value=10.0,
                    max_value=100.0,
                    value=50.0,
                    step=5.0,
                    key="hpwh_temp_rise",
                )
            with col2:
                cop_hpwh = st.number_input(
                    "Heat pump water heater COP",
                    min_value=1.0,
                    max_value=5.0,
                    value=3.0,
                    step=0.1,
                    key="hpwh_cop",
                )
                eff_resistance = st.number_input(
                    "Electric resistance efficiency (fraction)",
                    min_value=0.5,
                    max_value=1.0,
                    value=0.95,
                    step=0.01,
                    key="hpwh_eff_res",
                )

            # Very simple energy estimate using rule-of-thumb: ~0.293 Wh per gallon·°F
            wh_per_gal_F = 0.293
            daily_wh = gallons_per_day * temp_rise_F * wh_per_gal_F
            annual_kwh_heat = daily_wh * 365.0 / 1000.0

            kwh_res = annual_kwh_heat / max(eff_resistance, 1e-6)
            kwh_hpwh = annual_kwh_heat / max(cop_hpwh, 1e-6)

            # Use scenario electricity rate if available
            elec_rate = float(getattr(scen, "elec_rate_usd_per_kwh", 0.18) or 0.18)
            co2_per_kwh = float(getattr(scen, "grid_emissions_kgco2e_per_kwh", 0.4) or 0.4)

            cost_res = kwh_res * elec_rate
            cost_hpwh = kwh_hpwh * elec_rate
            co2_res_t = (kwh_res * co2_per_kwh) / 1000.0
            co2_hpwh_t = (kwh_hpwh * co2_per_kwh) / 1000.0

            two_col_metrics(
                [
                    ("Electric resistance use", f"{kwh_res:,.0f} kWh/yr"),
                    ("HPWH use", f"{kwh_hpwh:,.0f} kWh/yr"),
                ],
                [
                    ("Annual bill – resistance", f"${cost_res:,.0f}/yr"),
                    ("Annual bill – HPWH", f"${cost_hpwh:,.0f}/yr"),
                ],
            )

            st.markdown("###### Emissions comparison")
            st.write(
                f"- Electric resistance: **{co2_res_t:,.2f} tCO₂/yr**  \n"
                f"- Heat pump WH: **{co2_hpwh_t:,.2f} tCO₂/yr**  \n"
                f"- Difference: **{co2_res_t - co2_hpwh_t:,.2f} tCO₂/yr** avoided"
            )

            st.info(
                "Use this to argue for HPWHs in assignments: you can show both **kWh and CO₂ savings** for a typical home."
            )

        # ---------------------------------------------------------------
        # Lighting calculator
        # ---------------------------------------------------------------
        elif calc_choice == "Lighting: old bulbs vs LED":
            st.markdown("### Lighting: old bulbs vs LED")

            st.latex(r"E_{\text{annual}} = P \times N \times h_{\text{day}} \times 365 / 1000")
            st.caption(
                "E_annual [kWh] = power (W) × number of bulbs × hours per day × 365 / 1000. "
                "We’ll compare two wattages for the same light output."
            )

            col1, col2 = st.columns(2)
            with col1:
                n_bulbs = st.number_input(
                    "Number of bulbs",
                    min_value=0,
                    max_value=500,
                    value=20,
                    step=1,
                    key="light_n_bulbs",
                )
                hours_per_day = st.number_input(
                    "Average hours per day (per bulb)",
                    min_value=0.0,
                    max_value=24.0,
                    value=3.0,
                    step=0.5,
                    key="light_hours",
                )
            with col2:
                watt_old = st.number_input(
                    "Old bulb wattage (W) (e.g., 60W incandescent)",
                    min_value=1.0,
                    max_value=200.0,
                    value=60.0,
                    step=1.0,
                    key="light_w_old",
                )
                watt_new = st.number_input(
                    "LED wattage (W) (e.g., 9W LED)",
                    min_value=1.0,
                    max_value=200.0,
                    value=9.0,
                    step=1.0,
                    key="light_w_new",
                )

            kwh_old = watt_old * n_bulbs * hours_per_day * 365.0 / 1000.0
            kwh_new = watt_new * n_bulbs * hours_per_day * 365.0 / 1000.0

            elec_rate = float(getattr(scen, "elec_rate_usd_per_kwh", 0.18) or 0.18)
            co2_per_kwh = float(getattr(scen, "grid_emissions_kgco2e_per_kwh", 0.4) or 0.4)

            cost_old = kwh_old * elec_rate
            cost_new = kwh_new * elec_rate
            co2_old_t = (kwh_old * co2_per_kwh) / 1000.0
            co2_new_t = (kwh_new * co2_per_kwh) / 1000.0

            two_col_metrics(
                [
                    ("Old bulbs energy", f"{kwh_old:,.0f} kWh/yr"),
                    ("LED energy", f"{kwh_new:,.0f} kWh/yr"),
                ],
                [
                    ("Old bulbs cost", f"${cost_old:,.0f}/yr"),
                    ("LED cost", f"${cost_new:,.0f}/yr"),
                ],
            )

            st.write(
                f"- Emissions: **{co2_old_t:,.2f} tCO₂/yr → {co2_new_t:,.2f} tCO₂/yr**, "
                f"saving **{co2_old_t - co2_new_t:,.2f} tCO₂/yr**."
            )

            st.info("This is a nice, simple example for students to show in a ‘quick win’ section of a report.")

        # ---------------------------------------------------------------
        # Plug / standby load
        # ---------------------------------------------------------------
        else:  # "Plug / standby load"
            st.markdown("### Plug / standby load")

            st.latex(r"E_{\text{annual}} = P_{\text{standby}} \times h_{\text{year}} / 1000")
            st.caption(
                "For always-on devices, h_year ≈ 8760 hours. Many small standby loads add up over a year."
            )

            col1, col2 = st.columns(2)
            with col1:
                n_devices = st.number_input(
                    "Number of similar devices",
                    min_value=0,
                    max_value=200,
                    value=10,
                    step=1,
                    key="standby_n",
                )
                standby_watts = st.number_input(
                    "Standby power per device (W)",
                    min_value=0.0,
                    max_value=100.0,
                    value=3.0,
                    step=0.5,
                    key="standby_w",
                )
            with col2:
                hours_per_day = st.number_input(
                    "Hours per day in standby",
                    min_value=0.0,
                    max_value=24.0,
                    value=24.0,
                    step=1.0,
                    key="standby_hours",
                )

            kwh_year = standby_watts * n_devices * hours_per_day * 365.0 / 1000.0

            elec_rate = float(getattr(scen, "elec_rate_usd_per_kwh", 0.18) or 0.18)
            co2_per_kwh = float(getattr(scen, "grid_emissions_kgco2e_per_kwh", 0.4) or 0.4)

            cost = kwh_year * elec_rate
            co2_t = (kwh_year * co2_per_kwh) / 1000.0

            two_col_metrics(
                [
                    ("Standby energy", f"{kwh_year:,.0f} kWh/yr"),
                ],
                [
                    ("Annual cost", f"${cost:,.0f}/yr"),
                ],
            )

            st.write(f"- Emissions: **{co2_t:,.2f} tCO₂/yr** from this set of standby devices.")
            st.info(
                "Use this to justify **smart strips, full shutoff of electronics, and better default power settings**."
            )

    # =====================================================================
    # TAB 3 – Household Guide
    # =====================================================================
    with tab_guide:
        st.subheader("Household Sustainability Guide")

        st.caption("A structured set of ideas for renters, owners, and different budget levels.")

        audience = st.selectbox(
            "Which best describes you?",
            ["Renter", "Homeowner", "Campus housing / dorm", "Small business tenant"],
            key="guide_audience",
        )
        budget = st.selectbox(
            "Budget level",
            ["Very limited", "Moderate", "Can invest for long-term"],
            key="guide_budget",
        )

        st.markdown("#### 1. No-cost / low-effort actions")

        if audience in ["Renter", "Campus housing / dorm"]:
            st.markdown(
                """
                - Adjust **thermostat setpoints** within comfort ranges (especially at night)  
                - Turn off **lights, monitors, TVs** when not in use  
                - Use **power strips** and fully switch off clusters of devices  
                - Use blinds/curtains for **passive heating and cooling**  
                - Wash clothes in **cold water** where possible  
                """
            )
        else:
            st.markdown(
                """
                - Fine-tune **thermostat schedules** for occupancy  
                - Identify rooms or zones that can be **set back** more aggressively  
                - Verify **filters** are clean and vents are not blocked  
                - Check **water heater setpoint** (often 120°F is enough for safety + comfort)  
                - Do a simple **walk-through audit** looking for obvious waste  
                """
            )

        st.markdown("#### 2. Low- to medium-cost upgrades (1–3 year horizon)")

        if budget == "Very limited":
            st.markdown(
                """
                - **LED bulbs** wherever they’re still missing  
                - **Weatherstripping** around leaky doors/windows  
                - **Smart plugs** or smart strips for TVs, consoles, and PCs  
                - Low-flow **showerheads and aerators** to cut hot water use  
                """
            )
        else:
            st.markdown(
                """
                - All of the above, plus:  
                - **Smart thermostat** (if you control heating/cooling)  
                - Upgrade the **most-used appliances** to efficient models (fridge, washer)  
                - Basic **air sealing & attic insulation** where accessible  
                - Add **ceiling fans** to allow a slightly higher summer setpoint  
                """
            )

        st.markdown("#### 3. Major projects (5–20 year horizon)")

        if audience in ["Homeowner", "Small business tenant"]:
            st.markdown(
                """
                - Plan for **heat pump** systems (space heating/cooling) at end-of-life of existing equipment  
                - Consider **heat pump water heaters** when tanks fail or are due for replacement  
                - Combine **roofing, insulation, and PV** planning so envelope and solar work together  
                - If you own parking, plan for **EV-ready circuits** and some charging  
                """
            )
        else:
            st.markdown(
                """
                - Ask landlords or campus facilities about plans for **more efficient heating/cooling**  
                - Encourage **building-wide projects** (insulation, window upgrades, controls)  
                - Organize with neighbors or other tenants to articulate **clear asks** (e.g., “LEDs + controls across all corridors”).  
                """
            )

        st.markdown("#### 4. How to talk about this in assignments")

        st.markdown(
            """
            - Group actions into **tiers** (no-cost, low-cost, major capex) and tie them to a timeline.  
            - Use simple numbers from the **calculators tab** or your scenario to estimate **kWh, $ and tCO₂** impacts.  
            - Emphasize that **behavior + small upgrades** are fast, while big equipment changes happen at **end-of-life**.  
            - Connect home decisions to **grid impacts**, **peak demand**, and **equity** (who can access upgrades first).  
            """
        )


def page_sequestration(scen: "ScenarioInput | None" = None):
    st.header("Carbon Sequestration")
    st.markdown(
        """
        **Carbon sequestration** is the process of taking carbon dioxide (CO₂) out of the atmosphere and storing it
        in plants, soils, oceans, rocks, or engineered reservoirs.

        In climate planning, sequestration is meant to:
        - **Complement deep emission reductions**, not replace them  
        - Address **hard-to-avoid emissions** (e.g., some industrial processes, aviation)  
        - Help **draw down past emissions** over the long term  

        On this page, you'll connect simple formulas to rough calculators so you can see how big different
        sequestration options really are and how they might fit into a campus, community, or national plan.
        """
    )

    st.caption(
        "Use the math to estimate sequestration potential and the notes to understand what it means "
        "for real projects and assignments."
    )

    # Optional scenario context so students can relate numbers to their site
    if scen is not None:
        site = scen.site
        with st.expander("Scenario context (optional)", expanded=False):
            col1, col2, col3 = st.columns(3)
            with col1:
                st.write("**Location**")
                st.write(f"{site.city or ''} {site.state or ''} {site.zipcode or ''}")
            with col2:
                st.write("**Building / campus**")
                st.write(site.building_type or "N/A")
            with col3:
                try:
                    st.write("**Grid CO₂ intensity**")
                    st.write(f"{scen.grid_emissions_kgco2e_per_kwh:.3f} kg CO₂/kWh")
                except Exception:
                    st.write("N/A")

    tabs = st.tabs(["Biological", "Point-source CCS", "Direct Air Capture", "Mineralization & Soils"])

    # =====================================================================
    # TAB 1 – Biological sequestration
    # =====================================================================
    with tabs[0]:
        st.subheader("Biological sequestration (trees, forests, land)")

        st.markdown("##### Core formulas")

        st.latex(r"E_{\text{CO2,trees}} = N_{\text{trees}} \times s_{\text{tree}}")
        st.caption(
            "Variables: N_trees = number of surviving trees; "
            "s_tree = sequestration rate per tree [kg CO₂/year]; "
            "E_CO2,trees = annual CO₂ removal [kg CO₂/year]."
        )

        st.latex(r"E_{\text{CO2,forest}} = A_{\text{forest}} \times s_{\text{forest}}")
        st.caption(
            "Variables: A_forest = forest/restored area (acres or hectares); "
            "s_forest = sequestration per unit area [t CO₂/(acre·year) or t CO₂/(ha·year)]."
        )

        st.markdown("##### Simple calculator (rough, educational)")

        col1, col2 = st.columns(2)
        with col1:
            n_trees = st.number_input(
                "Number of new trees (surviving long-term)",
                min_value=0,
                max_value=1_000_000,
                value=100,
                step=10,
                key="bio_trees_n",
            )
            s_tree = st.number_input(
                "Sequestration per tree (kg CO₂ / year)",
                min_value=0.0,
                max_value=200.0,
                value=22.0,
                step=1.0,
                help="Classroom rule-of-thumb: ~10–25 kg CO₂ per tree per year.",
                key="bio_trees_s",
            )

            years = st.slider(
                "Time horizon (years)",
                min_value=1,
                max_value=100,
                value=30,
                key="bio_years",
            )
        with col2:
            forest_acres = st.number_input(
                "Forest / restored land area (acres)",
                min_value=0.0,
                max_value=1_000_000.0,
                value=10.0,
                step=1.0,
                key="bio_forest_acres",
            )
            s_forest = st.number_input(
                "Sequestration rate (t CO₂ / acre / year)",
                min_value=0.0,
                max_value=20.0,
                value=4.0,
                step=0.5,
                help="Very rough average – varies by climate, species, and age.",
                key="bio_forest_s",
            )

        # Calculations
        annual_tree_kg = n_trees * s_tree
        annual_tree_t = annual_tree_kg / 1000.0

        annual_forest_t = forest_acres * s_forest
        annual_total_t = annual_tree_t + annual_forest_t
        total_over_horizon_t = annual_total_t * years

        st.markdown("###### Results")
        colr1, colr2 = st.columns(2)
        with colr1:
            st.metric("Trees only (annual)", f"{annual_tree_t:,.2f} t CO₂ / year")
            st.metric("Forest only (annual)", f"{annual_forest_t:,.2f} t CO₂ / year")
        with colr2:
            st.metric("Total nature-based (annual)", f"{annual_total_t:,.2f} t CO₂ / year")
            st.metric(f"Total over {years} years", f"{total_over_horizon_t:,.0f} t CO₂")

        st.markdown("###### How to use this in homework")
        st.write(
            "- Compare **annual removal** to a building, campus, or city footprint.\n"
            "- Ask: *If emissions are 50,000 t CO₂/year, is this a big or tiny contribution?*\n"
            "- Discuss **land availability, permanence (fire/logging), and co-benefits**, not just the number."
        )

        with st.expander("Offsets & critical thinking (for essays)"):
            st.markdown(
                """
                - Additionality – would these trees/forests really not exist without the project?  
                - Permanence – what could cause the stored carbon to be released again?  
                - Leakage – does protecting one area just shift deforestation elsewhere?  
                - Monitoring – who tracks tree survival and growth over time?  
                """
            )

        st.warning(
            "Biological sequestration is valuable but **reversible**. In projects, present it as a complement "
            "to deep emission cuts, not a license to keep emitting."
        )

    # =====================================================================
    # TAB 2 – Point-source CCS
    # =====================================================================
    with tabs[1]:
        st.subheader("Point-source CCS (capture on smokestacks)")

        st.markdown("##### Core formulas")

        st.latex(r"E_{\text{captured}} = E_{\text{emissions}} \times f_{\text{capture}}")
        st.caption(
            "E_emissions = baseline stack emissions [t CO₂/year]; "
            "f_capture = capture fraction (0–1); "
            "E_captured = captured CO₂ at the stack [t CO₂/year]."
        )

        st.latex(
            r"E_{\text{energy}} = E_{\text{captured}} \times e_{\text{CCS}} \times I_{\text{grid}} / 1000"
        )
        st.caption(
            "e_CCS = extra energy use per tonne captured [kWh/t CO₂]; "
            "I_grid = grid emissions intensity [kg CO₂/kWh]; "
            "E_energy = emissions caused by that energy [t CO₂/year]."
        )

        st.latex(r"E_{\text{net}} = E_{\text{captured}} - E_{\text{energy}}")
        st.caption("E_net = net CO₂ removed from the atmosphere [t CO₂/year].")

        st.markdown("##### CCS calculator")

        col1, col2 = st.columns(2)
        with col1:
            baseline_emissions = st.number_input(
                "Baseline stack emissions (t CO₂ / year)",
                min_value=0.0,
                max_value=50_000_000.0,
                value=100_000.0,
                step=1_000.0,
                key="ccs_baseline",
            )
            capture_frac_pct = st.slider(
                "Capture fraction (%)",
                min_value=0,
                max_value=100,
                value=90,
                key="ccs_frac",
            )
        with col2:
            energy_kwh_per_t = st.number_input(
                "Extra energy use (kWh per t CO₂ captured)",
                min_value=0.0,
                max_value=5_000.0,
                value=250.0,
                step=25.0,
                help="Order of magnitude for many CCS designs.",
                key="ccs_energy_per_t",
            )
            grid_intensity = st.number_input(
                "Grid CO₂ intensity (kg CO₂ / kWh)",
                min_value=0.0,
                max_value=1.0,
                value=0.4,
                step=0.05,
                key="ccs_grid_intensity",
            )

        f_capture = capture_frac_pct / 100.0
        captured_t = baseline_emissions * f_capture

        annual_energy_kwh = captured_t * energy_kwh_per_t
        energy_emissions_t = (annual_energy_kwh * grid_intensity) / 1000.0
        net_removed_t = max(0.0, captured_t - energy_emissions_t)

        st.markdown("###### Results")
        colr1, colr2 = st.columns(2)
        with colr1:
            st.metric("Gross captured", f"{captured_t:,.0f} t CO₂ / year")
            st.metric("Energy use", f"{annual_energy_kwh/1e6:,.2f} GWh / year")
        with colr2:
            st.metric("Energy-related emissions", f"{energy_emissions_t:,.0f} t CO₂ / year")
            st.metric("Net removed (after energy)", f"{net_removed_t:,.0f} t CO₂ / year")

        st.markdown("###### Interpretation for students")
        st.write(
            "- **Net** removals matter for the climate, not just gross capture.\n"
            "- Cleaner electricity (lower grid intensity) or waste heat improves E_net.\n"
            "- In write-ups: always comment on **capture fraction**, **energy penalty**, and whether CCS is "
            "applied to a sector that also needs to **shrink** its emissions overall."
        )

    # =====================================================================
    # TAB 3 – Direct Air Capture
    # =====================================================================
    with tabs[2]:
        st.subheader("Direct Air Capture (DAC)")

        st.markdown("##### Core formulas")

        st.latex(r"C_{\text{gross}} = C_{\text{capacity}} \times CF")
        st.caption(
            "C_capacity = rated DAC capacity [t CO₂/year if run at full output]; "
            "CF = capacity factor (0–1) for how often it actually runs; "
            "C_gross = gross CO₂ captured [t CO₂/year]."
        )

        st.latex(
            r"E_{\text{energy}} = C_{\text{gross}} \times e_{\text{DAC}} \times I_{\text{grid}} / 1000"
        )
        st.caption(
            "e_DAC = energy use per tonne captured [kWh/t CO₂]; "
            "I_grid = grid emissions intensity [kg CO₂/kWh]; "
            "E_energy = emissions from DAC energy use [t CO₂/year]."
        )

        st.latex(r"C_{\text{net}} = C_{\text{gross}} - E_{\text{energy}}")
        st.caption("C_net = net removals after accounting for the energy used [t CO₂/year].")

        st.markdown("##### DAC calculator")

        col1, col2 = st.columns(2)
        with col1:
            dac_capacity = st.number_input(
                "DAC rated capacity (t CO₂ / year)",
                min_value=0.0,
                max_value=5_000_000.0,
                value=50_000.0,
                step=1_000.0,
                key="dac_capacity",
            )
            capacity_factor = st.slider(
                "Capacity factor (0–1)",
                min_value=0.0,
                max_value=1.0,
                value=0.9,
                step=0.05,
                key="dac_cf",
            )
            energy_kwh_per_t_dac = st.number_input(
                "Energy use (kWh per t CO₂ captured)",
                min_value=0.0,
                max_value=10_000.0,
                value=1500.0,
                step=50.0,
                help="Many DAC concepts fall around 1,000–3,000 kWh/t.",
                key="dac_energy_per_t",
            )
        with col2:
            grid_intensity_dac = st.number_input(
                "Grid CO₂ intensity (kg CO₂ / kWh)",
                min_value=0.0,
                max_value=1.0,
                value=0.4,
                step=0.05,
                key="dac_grid_intensity",
            )
            renew_share_dac = st.slider(
                "Share of DAC energy from renewables (%)",
                min_value=0,
                max_value=100,
                value=60,
                key="dac_renew_share",
            )

        gross_captured_t = dac_capacity * capacity_factor
        annual_energy_kwh_dac = gross_captured_t * energy_kwh_per_t_dac

        nonrenew_frac = 1.0 - (renew_share_dac / 100.0)
        nonrenew_kwh = annual_energy_kwh_dac * nonrenew_frac

        energy_emissions_dac_t = (nonrenew_kwh * grid_intensity_dac) / 1000.0
        net_captured_dac_t = max(0.0, gross_captured_t - energy_emissions_dac_t)

        st.markdown("###### Results")
        colr1, colr2 = st.columns(2)
        with colr1:
            st.metric("Gross CO₂ captured", f"{gross_captured_t:,.0f} t CO₂ / year")
            st.metric("Energy use", f"{annual_energy_kwh_dac/1e6:,.2f} GWh / year")
        with colr2:
            st.metric("Energy-related emissions", f"{energy_emissions_dac_t:,.0f} t CO₂ / year")
            st.metric("Net CO₂ removed", f"{net_captured_dac_t:,.0f} t CO₂ / year")

        st.markdown("###### Notes for interpretation")
        st.write(
            "- DAC is **energy-intensive**, so net benefit depends heavily on the **carbon intensity of power**.\n"
            "- In a high-carbon grid, DAC can erase much of its own benefit unless paired with renewables.\n"
            "- For essays, compare **net CO₂ removed per kWh** to what that same energy could do in "
            "**efficiency or direct renewable deployment**."
        )

    # =====================================================================
    # TAB 4 – Mineralization & soils
    # =====================================================================
    with tabs[3]:
        st.subheader("Mineralization & long-term storage in rock/soils")

        st.markdown("##### Core formula (rock required)")

        st.latex(r"M_{\text{rock}} = \frac{E_{\text{CO2}}}{r_{\text{rock}}}")
        st.caption(
            "E_CO2 = CO₂ to be stored [t CO₂]; "
            "r_rock = storage capacity [t CO₂ per t rock]; "
            "M_rock = mass of reactive rock needed [t rock]."
        )

        st.markdown(
            "Mineralization can be **in situ** (injecting CO₂ into basalt or other reactive rocks) or "
            "**ex situ** (accelerated weathering of crushed rock). This is a simplified mass-balance view."
        )

        col1, col2 = st.columns(2)
        with col1:
            co2_to_store_t = st.number_input(
                "CO₂ to store (t CO₂)",
                min_value=0.0,
                max_value=10_000_000.0,
                value=100_000.0,
                step=1_000.0,
                key="min_co2_store",
            )
        with col2:
            rock_capacity = st.number_input(
                "Rock capacity (t CO₂ per t rock)",
                min_value=0.01,
                max_value=1.0,
                value=0.2,
                step=0.01,
                help="Example: 0.2 → 1 t rock can bind 0.2 t CO₂.",
                key="min_rock_capacity",
            )

        rock_mass_needed_t = co2_to_store_t / rock_capacity if rock_capacity > 0 else 0.0

        st.markdown("###### Result")
        st.metric("Rock required", f"{rock_mass_needed_t:,.0f} t rock")

        st.markdown("##### Permanence & constraints")
        st.write(
            "- Mineralized CO₂ is typically **very long-lived** (hundreds–thousands of years).\n"
            "- Constraints include **mining, grinding energy, transport**, and **local geology**.\n"
            "- Soil carbon can be lost quickly if land management changes (tilling, erosion, drainage).\n"
        )

        st.markdown("###### How to use this tab in assignments")
        st.write(
            "- Use the mass of rock to get a feel for **physical scale** (trucks, mines, infrastructure).\n"
            "- Combine with biological and DAC/CCS tabs to design a **portfolio** of sequestration wedges.\n"
            "- Always connect the math to **feasibility, environmental justice, and trade-offs**."
        )


def page_ai_education_policy(scen: Optional[ScenarioInput]):
    st.header("AI, Education & Policy for Sustainable Energy Systems")
    st.caption(
        "A hub to explore how AI intersects with sustainability, learn what different actors can do, "
        "and find policy & incentive resources."
    )

    # Optional scenario context (if available)
    if scen is not None:
        site = scen.site
        with st.expander("Scenario context (optional)", expanded=False):
            col1, col2, col3 = st.columns(3)
            with col1:
                st.write("**Location**")
                st.write(f"{site.city or ''} {site.state or ''} {site.zipcode or ''}")
            with col2:
                st.write("**Site type**")
                st.write(site.building_type or "N/A")
            with col3:
                st.write("**Grid CO₂ intensity**")
                try:
                    st.write(f"{scen.grid_emissions_kgco2e_per_kwh:.3f} kg CO₂/kWh")
                except Exception:
                    st.write("N/A")

    st.markdown("---")

    tab_ai, tab_edu, tab_policy = st.tabs(
        ["AI & Sustainability", "Education & Actions", "Policy & Incentives"]
    )

    # =====================================================================
    # TAB 1 – AI & Sustainability
    # =====================================================================
    with tab_ai:
        st.subheader("AI & Sustainability")

        col_ai1, col_ai2 = st.columns([2, 1])
        with col_ai1:
            st.markdown("#### How AI affects sustainability")
            st.markdown(
                """
                **AI can help or hurt sustainability depending on how it's used:**
                
                - **Energy use & data centers** – Large models and high-uptime servers consume a lot of electricity  
                  (and sometimes water for cooling).  
                - **Cleaner grids & optimization** – AI can help with **forecasting solar/wind**, balancing the grid,  
                  and improving building/industrial efficiency.  
                - **Materials & design** – AI tools can speed up **material discovery**, **system design**, and  
                  modeling of complex energy systems.  
                - **Behavior & demand** – Recommendation systems can encourage **more sustainable choices** or  
                  increase consumption, depending on incentives.
                """
            )
        with col_ai2:
            st.markdown("#### Quick framing")
            st.markdown(
                """
                - Ask: **What problem am I solving with AI?**  
                - Estimate: **Energy, emissions, and water** for training & inference.  
                - Prefer **low-carbon grids**, **efficient hardware**, and **right-sized models**.  
                """
            )

        st.markdown("#### AI use-cases that clearly support sustainability")
        col_use1, col_use2 = st.columns(2)
        with col_use1:
            st.markdown("**Good candidates for AI**")
            st.markdown(
                """
                - **Grid operations:** forecasting load, solar/wind, and congestion  
                - **Building optimization:** smart schedules for HVAC, lighting, and storage  
                - **Fleet & routing:** route optimization for delivery trucks, transit, and logistics  
                - **Fault detection:** catching equipment issues early in solar/wind farms or plants  
                - **Planning scenarios:** exploring thousands of grid or policy scenarios quickly  
                """
            )
        with col_use2:
            st.markdown("**Use with caution**")
            st.markdown(
                """
                - Generating **huge volumes of low-value content**  
                - Always-on, **high-power inference** for trivial tasks  
                - Training **oversized models** when a smaller one would do  
                """
            )

        st.markdown("---")
        st.subheader("“Should I build a data center here?” (educational tool)")

        col_dc1, col_dc2 = st.columns(2)
        with col_dc1:
            it_load_mw = st.number_input(
                "Planned IT load (MW)",
                min_value=0.1,
                max_value=200.0,
                value=10.0,
                step=0.1,
                key="dc_it_load_mw",
            )
            pue = st.number_input(
                "Power Usage Effectiveness (PUE)",
                min_value=1.05,
                max_value=2.5,
                value=1.3,
                step=0.05,
                help="Total facility power / IT power. Lower is better.",
                key="dc_pue",
            )
            renewables_share = st.slider(
                "Share of data center electricity from renewables (%)",
                0,
                100,
                60,
                key="dc_renewables_share",
            )
        with col_dc2:
            if scen is not None and getattr(scen, "grid_emissions_kgco2e_per_kwh", None) is not None:
                default_ci = float(scen.grid_emissions_kgco2e_per_kwh)
            else:
                default_ci = 0.4
            grid_ci = st.number_input(
                "Grid CO₂ intensity at site (kg CO₂ per kWh)",
                min_value=0.0,
                max_value=1.0,
                value=default_ci,
                key="dc_grid_ci",
            )
            water_cooling = st.selectbox(
                "Cooling strategy",
                ["Air-cooled", "Water-cooled (tower)", "Water-cooled (once-through)", "Hybrid / adiabatic"],
                key="dc_cooling",
            )
            water_stress = st.selectbox(
                "Local water stress level",
                ["Low", "Moderate", "High", "Very high / scarce"],
                key="dc_water_stress",
            )

        # Simple annual energy & emissions
        it_kw = it_load_mw * 1000.0
        total_kw = it_kw * pue
        annual_kwh = total_kw * 8760.0 / 1000.0  # MWh
        annual_kwh = annual_kwh * 1000.0  # convert back to kWh for clarity
        annual_mwh = annual_kwh / 1000.0

        renew_frac = renewables_share / 100.0
        non_renew_kwh = annual_kwh * (1.0 - renew_frac)
        annual_co2_t = (non_renew_kwh * grid_ci) / 1000.0

        # Very rough water factors (illustrative only)
        if water_cooling.startswith("Air"):
            water_m3_per_mwh = 0.1
        elif "tower" in water_cooling.lower():
            water_m3_per_mwh = 1.5
        elif "once-through" in water_cooling.lower():
            water_m3_per_mwh = 0.5
        else:
            water_m3_per_mwh = 0.8

        annual_water_m3 = annual_mwh * water_m3_per_mwh

        col_dc3, col_dc4 = st.columns(2)
        with col_dc3:
            st.metric("Annual energy use", f"{annual_mwh:,.0f} MWh/yr")
            st.metric("Annual CO₂ (approx.)", f"{annual_co2_t:,.0f} tCO₂/yr")
        with col_dc4:
            st.metric("Implied PUE-adjusted load", f"{total_kw/1000.0:,.1f} MW total")
            st.metric("Cooling water (very rough)", f"{annual_water_m3:,.0f} m³/yr")

        st.caption(
            "Illustrative only – this is not a siting tool. It’s meant to show the scale of energy and water "
            "impacts from large data centers."
        )

        # High-level siting guidance
        st.markdown("##### High-level siting guidance (qualitative)")

        issues = []
        if grid_ci > 0.5 and renewables_share < 50:
            issues.append("High grid CO₂ with relatively low renewable share.")
        if water_stress in ["High", "Very high / scarce"] and "water" in water_cooling.lower():
            issues.append("Significant water use in a high-stress / scarce watershed.")
        if pue > 1.5:
            issues.append("PUE above ~1.5 – efficiency improvements may be needed.")

        if issues:
            st.warning(
                "Potential red flags for building here:\n\n- " + "\n- ".join(issues)
            )
        else:
            st.success(
                "On paper, this location looks more suitable than average – especially if paired with "
                "strong renewable PPAs and waste-heat reuse."
            )

        st.markdown(
            "_Best practice: locate large data centers on **low-carbon grids**, in **low to moderate water-stress regions**, "
            "with **efficient cooling**, and ideally with options for **waste-heat recovery** and local community benefit._"
        )

    # =====================================================================
    # TAB 2 – Education & Actions
    # =====================================================================
    with tab_edu:
        st.subheader("Education & Actions")

        audience = st.selectbox(
            "Who are you most interested in?",
            [
                "Individuals & households",
                "Students & educators",
                "Communities & campuses",
                "Companies & organizations",
                "Policy-makers & advocates",
            ],
            key="edu_audience",
        )

        st.markdown("#### What to focus on")

        if audience == "Individuals & households":
            col_e1, col_e2 = st.columns(2)
            with col_e1:
                st.markdown("**Everyday actions**")
                st.markdown(
                    """
                    - Track **electricity, gas, and fuel use** over a year  
                    - Tackle **no-cost** steps first (thermostat, behavior, turning things fully off)  
                    - Move to **low-cost** upgrades (LEDs, smart power strips, basic air sealing)  
                    - Plan for **bigger upgrades** over time (heat pumps, insulation, EVs)  
                    - Reduce **over-consumption**: clothes, electronics, and food waste  
                    """
                )
            with col_e2:
                st.markdown("**What to learn about**")
                st.markdown(
                    """
                    - Your **utility bill** (rate structure, TOU windows if any)  
                    - **Carbon intensity** of your local grid  
                    - Basic concepts: **kWh vs kW**, Btu, COP, mpg-e  
                    - Key programs: **rebates, tax credits, weatherization assistance**  
                    """
                )

        elif audience == "Students & educators":
            col_e1, col_e2 = st.columns(2)
            with col_e1:
                st.markdown("**In the classroom / projects**")
                st.markdown(
                    """
                    - Use real **campus or community data** for assignments  
                    - Compare **different technologies** (PV vs efficiency vs EVs) with simple economics  
                    - Explore **climate wedges** and how different actions add up  
                    - Design **mini-scenarios** using this app for a building or neighborhood  
                    """
                )
            with col_e2:
                st.markdown("**Clubs & groups**")
                st.markdown(
                    """
                    - Energy / sustainability clubs can adopt **one building** as a lab  
                    - Run **“energy treasure hunts”** to spot waste on campus  
                    - Partner with facilities to **pilot new tech** (sensors, small PV, etc.)  
                    - Communicate results with **simple visuals and stories**, not just numbers  
                    """
                )

        elif audience == "Communities & campuses":
            col_e1, col_e2 = st.columns(2)
            with col_e1:
                st.markdown("**Priority areas**")
                st.markdown(
                    """
                    - **Transit & active transport**: safe routes, frequent service in a few corridors  
                    - **Building retrofits**: start with public / campus buildings  
                    - **Public lighting**: LEDs + smart controls  
                    - **Community solar** or shared PV on schools/libraries  
                    """
                )
            with col_e2:
                st.markdown("**Engagement & equity**")
                st.markdown(
                    """
                    - Co-design programs with **frontline communities**  
                    - Track who benefits from **rebates & upgrades**  
                    - Add **translation, childcare, and scheduling** support for public meetings  
                    - Make data **open & understandable** (simple dashboards, maps)  
                    """
                )

        elif audience == "Companies & organizations":
            col_e1, col_e2 = st.columns(2)
            with col_e1:
                st.markdown("**Operations & facilities**")
                st.markdown(
                    """
                    - Measure **scope 1 & 2 emissions** and set reduction targets  
                    - Prioritize **efficiency projects** with strong payback and co-benefits  
                    - Electrify **fleet vehicles** where duty cycles fit EVs  
                    - Procure **renewable electricity** (on-site PV, PPAs, green tariffs)  
                    """
                )
            with col_e2:
                st.markdown("**Culture & decision-making**")
                st.markdown(
                    """
                    - Include **sustainability criteria** in major capex decisions  
                    - Train staff on **energy literacy** and climate basics  
                    - Avoid “greenwashing”: report **transparent, verified** metrics  
                    - Align incentives so that **energy savings** are actually rewarded  
                    """
                )

        else:  # "Policy-makers & advocates"
            col_e1, col_e2 = st.columns(2)
            with col_e1:
                st.markdown("**Policy levers**")
                st.markdown(
                    """
                    - Building codes (insulation, electrification readiness, EV-ready parking)  
                    - **Transit & active transport** funding and street design standards  
                    - Utility regulation: **time-of-use rates**, demand response, low-income protections  
                    - Incentives for **heat pumps, PV, EVs, storage**, and efficiency  
                    """
                )
            with col_e2:
                st.markdown("**Advocacy focus**")
                st.markdown(
                    """
                    - Push for **reliable, frequent public transit**, not just roads  
                    - Support **performance-based building standards**  
                    - Advocate for **pollution reductions** in overburdened communities  
                    - Emphasize **co-benefits**: health, comfort, affordability, jobs  
                    """
                )

        st.markdown("---")
        st.subheader("Topic-based quick reference")

        topic = st.selectbox(
            "Pick a topic to explore",
            [
                "Recycling & consumption",
                "Energy at home / in buildings",
                "Transportation & mobility",
                "Food & land use",
                "Policy & advocacy basics",
            ],
            key="edu_topic",
        )

        if topic == "Recycling & consumption":
            st.markdown(
                """
                - Focus first on **reducing** and **reusing**; recycling comes after.  
                - Electronics and textiles are often **high-impact** even in small volumes.  
                - Look for **repair cafes**, second-hand options, and product take-back programs.  
                - Avoid “wish-cycling”: check local rules to prevent contamination.  
                """
            )
        elif topic == "Energy at home / in buildings":
            st.markdown(
                """
                - Know your **baseline**: 12 months of energy bills.  
                - Tackle **envelope & air sealing**, then **heating/cooling systems**, then **appliances**.  
                - Use **smart thermostats** and scheduling before major replacements.  
                - In many climates, **heat pumps + insulation** are the biggest long-term win.  
                """
            )
        elif topic == "Transportation & mobility":
            st.markdown(
                """
                - Combine **mode shift** (walk/bike/transit) with **vehicle efficiency** (EVs, hybrids).  
                - Reduce **peak-hour solo driving**; carpool or adjust schedules where possible.  
                - Right-size vehicles: small EVs or efficient cars instead of oversized SUVs where possible.  
                - Think about **total miles per year**, not just mpg or range.  
                """
            )
        elif topic == "Food & land use":
            st.markdown(
                """
                - Reduce **food waste** first – planning, storage, and leftovers matter a lot.  
                - Shift toward more **plant-forward diets** over time.  
                - Support **local/regional producers** where possible, especially those using sustainable practices.  
                - Protect and restore **trees, wetlands, and natural areas** in and around communities.  
                """
            )
        else:  # Policy & advocacy basics
            st.markdown(
                """
                - Start at the **local level**: city council, transit board, school board, utility commissions.  
                - Know **which level of government** controls which levers (building codes, transit, rates, etc.).  
                - Build coalitions across **health, housing, labor, and environmental groups**.  
                - Focus on **clear, specific asks**: e.g., “fund 15-minute bus service on Route X” rather than “fix transit.”  
                """
            )

    # =====================================================================
    # TAB 3 – Policy & Incentives
    # =====================================================================
    with tab_policy:
        st.subheader("Policy & Incentives Finder (high-level)")

        st.caption(
            "This is an educational guide, not a live database. It points you toward where incentives usually live "
            "and what to look for."
        )

        country = st.selectbox(
            "Country (for now this content is US-focused)",
            ["United States", "Other / general guidance"],
            key="pol_country",
        )

        if country == "United States":
            # Basic state/category filters
            col_p1, col_p2 = st.columns(2)
            with col_p1:
                state_input = st.text_input(
                    "State or territory (e.g. MI, California)",
                    value=(scen.site.state if scen is not None and scen.site.state else ""),
                    key="pol_state",
                )
            with col_p2:
                focus_area = st.multiselect(
                    "Focus areas",
                    [
                        "Residential solar PV",
                        "Community solar / shared renewables",
                        "Home efficiency & weatherization",
                        "Heat pumps & electrification",
                        "EVs & charging",
                        "Commercial / industrial",
                    ],
                    default=["Home efficiency & weatherization", "EVs & charging"],
                    key="pol_focus",
                )

            st.markdown("#### Where to look for incentives (US)")

            col_p3, col_p4 = st.columns(2)
            with col_p3:
                st.markdown("**Key sources**")
                st.markdown(
                    """
                    - **State & local energy offices**  
                    - Your **utility** (electric & gas) rebate pages  
                    - **DSIRE** database (Database of State Incentives for Renewables & Efficiency)  
                    - U.S. DOE and EPA program pages  
                    - Local **housing & community development** agencies  
                    """
                )
            with col_p4:
                st.markdown("**Program types you may find**")
                st.markdown(
                    """
                    - **Upfront rebates** at the point of sale or via application  
                    - **Tax credits** for equipment and efficiency upgrades  
                    - **Low-income or no-upfront-cost** weatherization & electrification programs  
                    - **On-bill financing** or low-interest loans  
                    - **Performance-based incentives** (buy-back rates, SRECs in some states)  
                    """
                )

            st.markdown("#### How to use this in practice")

            bullets = []
            if "Residential solar PV" in focus_area:
                bullets.append(
                    "- For **solar PV**, check: net metering / export rules, interconnection timelines, "
                    "and any state/utility rebates or performance payments."
                )
            if "Community solar / shared renewables" in focus_area:
                bullets.append(
                    "- For **community solar**, look for programs that allow **renters** and households without good roofs "
                    "to subscribe to off-site projects."
                )
            if "Home efficiency & weatherization" in focus_area:
                bullets.append(
                    "- For **efficiency/weatherization**, search for low-income weatherization, whole-home retrofit programs, "
                    "and free/discounted audits."
                )
            if "Heat pumps & electrification" in focus_area:
                bullets.append(
                    "- For **heat pumps**, look for stackable federal + state + utility rebates, and make sure installers "
                    "are familiar with cold-climate equipment if relevant."
                )
            if "EVs & charging" in focus_area:
                bullets.append(
                    "- For **EVs & charging**, check federal tax credits, state point-of-sale rebates, and any utility "
                    "**home charger** or **TOU rate** incentives."
                )
            if "Commercial / industrial" in focus_area:
                bullets.append(
                    "- For **commercial/industrial**, check for custom efficiency incentives, strategic energy management "
                    "programs, and demand response offerings."
                )

            if bullets:
                st.markdown("**Based on your focus areas:**")
                st.markdown("\n".join(bullets))
            else:
                st.info("Select one or more focus areas above to see tailored guidance.")

            st.markdown("---")
            st.markdown("#### Policy ideas you might see or advocate for")

            st.markdown(
                """
                - **Building codes** that require better insulation, air sealing, and EV-ready wiring  
                - Stronger **appliance and equipment standards** (HVAC, lighting, etc.)  
                - **Transit funding** and street design that supports walking/biking  
                - **Time-of-use rates** paired with customer protections and clear communication  
                - Targeted **incentives for low-income households** and overburdened communities  
                """
            )

        else:
            st.markdown("#### General guidance (outside US)")

            st.markdown(
                """
                - Start with your **national energy or environment ministry** websites.  
                - Check for **national climate or energy plans**, which often list priority sectors and support programs.  
                - Look for **local or regional** programs in your state/province or city.  
                - Ask utilities or retailers about **rebates and efficiency programs** at the point of sale.  
                - International organizations (UNDP, World Bank, regional development banks) sometimes support projects and pilots.  
                """
            )

        st.info(
            "For assignments or projects, you can treat this tab as a checklist: "
            "identify **which level of government** and **which type of incentive** is most relevant for your idea."
        )



def page_eia():
    st.header("Fuel & Energy Data (EIA)")
    st.caption(
        "Use this page as your **MIA helper**: look up state electricity prices and "
        "MER-style total energy values directly from EIA. When the API is unavailable, "
        "you can still work in **classroom mode** with manual inputs."
    )

    # --- EIA key + status ---
    # Try to get a server-side key first (your key)
    server_key = st.secrets.get("EIA_API_KEY", None)

    if server_key:
        # In deployment: use your secret key, but don't expose it
        st.caption("Using developer configured API key.")
        api_key = server_key
    else:
        # Local dev / classroom mode: user can paste their own key if they have one
        api_key = st.text_input(
            "EIA API Key (optional, not stored)",
            value="",
            type="password",
            help=(
                "If you have your own EIA API key from eia.gov/opendata, paste it here. "
                "Leave blank to use built-in demo / fallback behavior."
            ),
        )
        api_key = api_key or None

    client = EIA(api_key) if api_key else None

    if client is None or not client.available():
        st.error(
            "No EIA_API_KEY available. Add it to `.streamlit/secrets.toml` "
            "or the deployment secrets. You can still use manual values below."
        )
        eia_ok = False
    else:
        eia_ok = True

    tabs = st.tabs([
        "Electricity Price by State",
        "MER / Total Energy (U.S.)",
        "Fuel Use by Resource",
    ])

    # ------------------------------------------------------------------
    # Tab 1: Electricity price
    # ------------------------------------------------------------------
    with tabs[0]:
        st.subheader("State average retail electricity price")

        col1, col2, col3 = st.columns(3)
        with col1:
            year = st.number_input(
                "Year", 1990, 2100, 2024, step=1, key="eia_price_year"
            )
        with col2:
            state = st.text_input("State (2-letter)", "MI", key="eia_price_state").upper()
        with col3:
            sector = st.selectbox(
                "Sector",
                ["total", "residential", "commercial", "industrial"],
                index=0,
                key="eia_price_sector",
            )

        st.markdown(
            "This uses the v2 `electricity/retail-sales` dataset (price in **cents/kWh**). "
            "If the API call fails (e.g., 403 Forbidden), you'll see a friendly message and "
            "can fall back to your classroom assumption."
        )

        col_left, col_right = st.columns([2, 1])
        with col_left:
            if st.button("Fetch from EIA", key="fetch_elec_price"):
                if not eia_ok:
                    st.error("Provide a valid EIA API key above to query live data.")
                else:
                    df = client.fetch_state_price(
                        year=int(year),
                        state=state,
                        sector=sector,
                    )
                    if df is None:
                        st.warning("EIA query returned no data.")
                        if client.last_error:
                            st.code(f"EIA error: {client.last_error}")
                        if client.last_url:
                            st.caption(f"Requested URL: `{client.last_url}`")
                    else:
                        st.success("EIA data loaded.")
                        st.dataframe(df, width='stretch')

                        if "price_usd_per_kwh" in df.columns:
                            price_usd = float(df["price_usd_per_kwh"].iloc[0])
                            st.metric(
                                "Average retail price",
                                f"{price_usd:.3f} USD/kWh",
                                help="Annual average for this state and sector.",
                            )
        with col_right:
            st.markdown("#### Classroom / manual value")
            manual_price = st.number_input(
                "Manual price (USD/kWh)",
                min_value=0.0,
                value=0.18 if state == "MI" else 0.16,
                step=0.005,
                key="eia_manual_price",
                help="Use this if EIA is unavailable or for hypothetical scenarios.",
            )
            st.caption(
                "You can copy this into the sidebar **Electric rate** or any homework "
                "calculation that needs electricity price."
            )

    # ------------------------------------------------------------------
    # Tab 2: MER / Total Energy (single + multi MSN support)
    # ------------------------------------------------------------------
    with tabs[1]:
        st.subheader("Total energy use from MER-style series")

        MSN_HELP = {
            "TETGRUS": "Total energy consumption per dollar of real GDP (thousand Btu / $2017, U.S.)",
            "TETPRUS": "Total primary energy production (quadrillion Btu, U.S.)",
            "TETCHUS": "Total energy consumption per capita (million Btu per person, U.S.)",
            "TEGDSUS": "Total energy consumption per real GDP (thousand Btu / $2017, U.S.)",
            "GDPDIUS": "GDP implicit price deflator (index, U.S.)",
            "GDPRVUS": "Real GDP (billion chained dollars, U.S.)",
            "TPOPPUS": "Resident population (thousands, U.S.)",
        }

        col_m1, col_m2 = st.columns(2)
        with col_m1:
            preset = st.selectbox(
                "Common MER series (optional)",
                options=["(manual entry)"] + list(MSN_HELP.keys()),
                index=1,
                key="mer_single_preset",
                format_func=lambda x: (
                    x if x == "(manual entry)" else f"{x} – {MSN_HELP.get(x, '')}"
                ),
            )
        with col_m2:
            st.caption(
                "You can start from a preset MSN or type any valid MSN directly, "
                "using MER documentation or class handouts."
            )

        default_msn = "" if preset == "(manual entry)" else preset
        msn = st.text_input(
            "MSN code (e.g., TETGRUS for total U.S. energy consumption per GDP)",
            value=default_msn or "TETGRUS",
            key="mer_single_msn",
            help="Use codes from the MER documentation or class handouts.",
        )

        col1, col2 = st.columns(2)
        with col1:
            start_year = st.number_input(
                "Start year", 1950, 2100, 2000, key="mer_single_start_year"
            )
        with col2:
            end_year = st.number_input(
                "End year", 1950, 2100, 2024, key="mer_single_end_year"
            )

        if st.button("Fetch MER series", key="fetch_mer_single"):
            if not eia_ok:
                st.error("Provide a valid EIA API key above to query live data.")
            else:
                df_mer = client.fetch_total_energy_series(
                    msn=msn.strip().upper(),
                    start_year=int(start_year),
                    end_year=int(end_year),
                    frequency="annual",
                )
                if df_mer is None or df_mer.empty:
                    st.warning("EIA MER query returned no data.")
                    if client.last_error:
                        st.code(f"EIA error: {client.last_error}")
                    if client.last_url:
                        st.caption(f"Requested URL: `{client.last_url}`")
                else:
                    st.success("MER / total energy time series loaded.")
                    st.dataframe(df_mer, width='stretch')

        st.markdown("---")
        st.markdown("##### Advanced: fetch multiple MER MSNs at once")

        st.caption(
            "Paste a comma-separated list of MSN codes (e.g. "
            "`TETGRUS,TETPRUS,TETCHUS,TEGDSUS`) from the MER documentation or "
            "class handouts. This is where you can pull coal, natural gas, etc., "
            "as long as you have their MSN codes."
        )

        msn_multi_str = st.text_input(
            "MSN codes (comma-separated)",
            value="TETGRUS,TETPRUS,TETCHUS,TEGDSUS",
            key="mer_multi_msns",
        )

        if st.button("Fetch all MSNs", key="fetch_mer_multi"):
            if not eia_ok:
                st.error("Provide a valid EIA API key above to query live data.")
            else:
                msn_list = [m.strip().upper() for m in msn_multi_str.split(",") if m.strip()]
                if not msn_list:
                    st.error("Please enter at least one MSN code.")
                else:
                    df_multi = client.fetch_total_energy_multi(
                        msns=msn_list,
                        start_year=int(start_year),
                        end_year=int(end_year),
                        frequency="annual",
                    )
                    if df_multi is None or df_multi.empty:
                        st.warning("EIA MER multi-series query returned no data.")
                        if client.last_error:
                            st.code(f"EIA error: {client.last_error}")
                        if client.last_url:
                            st.caption(f"Requested URL: `{client.last_url}`")
                    else:
                        st.success("MER multi-series data loaded.")
                        st.dataframe(df_multi, width='stretch')

        st.markdown("---")
        st.markdown("#### How to use these values in assignments")
        st.write(
            "- **A2**: Use MER total primary energy and U.S. population to compute "
            "per-capita primary power.\n"
            "- **A3**: Use two MER points (e.g., 2000 and 2020) to compute the "
            "growth rate and doubling time (see the A3 tab in the Energy Calculations page).\n"
        )

    st.markdown("---")
    st.subheader("Status & Troubleshooting")

    if client is None or not client.available():
        st.info(
            "Status: **classroom mode** (no EIA key). You can still do all assignments by "
            "using manual values from MER tables or provided problem data."
        )
    else:
        if client.last_error:
            st.warning(
                "Status: **EIA key configured but recent call failed**. See error below."
            )
            st.code(client.last_error)
            if client.last_url:
                st.caption(f"Last URL: `{client.last_url}`")
            st.write(
                "If you see `403 Forbidden`, test the same URL in a browser. "
                "If it still fails, log in at eia.gov/opendata and confirm that your key "
                "is active and allowed to access API v2."
            )
        else:
            st.success(
                "Status: **EIA key available**. If you still see 403 in the browser, "
                "it's an EIA-side issue, not your Streamlit code."
            )

    # ------------------------------------------------------------------
    # Tab 3: Fuel Use by Resource (coal, gas, petroleum, etc.)
    # ------------------------------------------------------------------
    with tabs[2]:
        st.subheader("Fuel use by resource (U.S., annual)")

        if client is None or not client.available():
            st.error("Provide a valid EIA API key above to query live data.")
        else:
            presets = client.fuel_presets()
            if not presets:
                st.error(
                    "fuel_presets() returned no mappings. Define fuel presets in `eia_client.py` "
                    "to use this tab."
                )
            else:
                fuel_label = st.selectbox(
                    "Choose a fuel/resource",
                    list(presets.keys()),
                    index=0,
                    key="eia_fuel_label",
                )

                col1, col2 = st.columns(2)
                with col1:
                    start_year_f = st.number_input(
                        "Start year", 1950, 2100, 2000, key="eia_fuel_start_year"
                    )
                with col2:
                    end_year_f = st.number_input(
                        "End year", 1950, 2100, 2024, key="eia_fuel_end_year"
                    )

                if st.button("Fetch fuel series", key="fetch_fuel_series"):
                    df_fuel = client.fetch_fuel_timeseries(
                        fuel_label=fuel_label,
                        start_year=int(start_year_f),
                        end_year=int(end_year_f),
                    )
                    if df_fuel is None or df_fuel.empty:
                        st.warning("EIA query for this fuel returned no data.")
                        if client.last_error:
                            st.code(f"EIA error: {client.last_error}")
                        if client.last_url:
                            st.caption(f"Requested URL: `{client.last_url}`")
                    else:
                        st.success(f"Loaded MER series for: {fuel_label}")
                        st.dataframe(df_fuel, width='stretch')

                        try:
                            df_plot = df_fuel.copy()
                            df_plot["period"] = df_plot["period"].astype(int)
                            df_plot = df_plot.sort_values("period")

                            units = presets[fuel_label].get("units", "")
                            latest = df_plot.iloc[-1]
                            st.metric(
                                f"Latest value ({int(latest['period'])})",
                                f"{latest['value']:.2f} {units}".strip(),
                            )

                            st.line_chart(
                                df_plot.set_index("period")["value"],
                                width='stretch',
                            )

                        except Exception as e:
                            st.error(f"Plotting error: {e}")

def page_conversions():
    st.header("Conversion Factors & Units")
    st.caption("Pick units to convert and see reference quick tips.")

    left, right = st.columns(2)
    with left:
        value = st.number_input("Value", value=1.0)
        from_unit = st.selectbox("From", sorted(UNITS))
        to_unit = st.selectbox("To", sorted(UNITS))
        result = convert_value(value, from_unit, to_unit)
        st.metric("Converted", f"{result:g} {to_unit}")
    with right:
        st.subheader("Quick tips")
        for tip in conversion_quicktips():
            st.markdown(f"- {tip}")


def page_policy():
    st.header("Policy & Incentives Finder")
    st.caption("Smart policies to support, plus credits/rebates you can claim.")

    st.subheader("Advocacy: What to support")
    for p in policy_advocacy():
        pill(p["name"], p["why"])

    st.subheader("Credits & Rebates (high level)")
    for c in incentive_blurbs():
        feature_card(c["name"], c["details"], small=True, key=f"inc_{abs(hash(c['name']))}")


def page_monthly_review():
    st.header("Monthly Energy Review")
    st.caption(
        "Digest of recent U.S. energy trends using the EIA **total-energy** (MER) API. "
        "Use the annual mode for A2/A3-style problems and the monthly dashboard for "
        "short-term trends where data are available."
    )

    # --- EIA key setup ---
    # Try to get a server-side key first (your key)
    server_key = st.secrets.get("EIA_API_KEY", None)

    if server_key:
        # In deployment: use your secret key, but don't expose it
        st.caption("Using developer configured API key.")
        api_key = server_key
    else:
        # Local dev / classroom mode: user can paste their own key if they have one
        api_key = st.text_input(
            "EIA API Key (optional, not stored)",
            value="",
            type="password",
            help=(
                "If you have your own EIA API key from eia.gov/opendata, paste it here. "
                "Leave blank to use built-in demo / fallback behavior."
            ),
        )
        api_key = api_key or None

    client = EIA(api_key) if api_key else None

    if client is None or not client.available():
        note(
            "Status: **classroom mode** (no EIA key). For A2/A3 you can still use MER "
            "PDF/Excel tables and type values into the Energy Calculations page."
        )
        return

    # --- Quick MSN helper for students ---
    st.markdown("### MSN cheat-sheet (what do these codes mean?)")
    MSN_HELP = {
        "TETGRUS": "Total energy consumption per dollar of real GDP (thousand Btu / $2017, U.S.)",
        "TETPRUS": "Total primary energy production (quadrillion Btu, U.S.)",
        "TETCHUS": "Total energy consumption per capita (million Btu per person, U.S.)",
        "TEGDSUS": "Total energy consumption per real GDP (thousand Btu / $2017, U.S.)",
        "GDPDIUS": "GDP implicit price deflator (index, U.S.)",
        "GDPRVUS": "Real GDP (billion chained dollars, U.S.)",
        "TPOPPUS": "Resident population (thousands, U.S.)",
    }

    cols_help = st.columns(len(MSN_HELP))
    for (code, desc), col in zip(MSN_HELP.items(), cols_help):
        with col:
            st.markdown(f"**{code}**")
            st.caption(desc)

    st.markdown("---")

    # --- Mode selection: annual vs monthly ---
    mode = st.radio(
        "Review mode",
        ["Annual overview (MER-style)", "Monthly dashboard (last N months)"],
        horizontal=True,
        key="mer_mode",
    )

    # ------------------------------------------------------
    #  Mode 1: Annual overview (MER-style)
    # ------------------------------------------------------
    if mode.startswith("Annual"):
        st.subheader("Annual overview – MER-style series")

        presets = client.fuel_presets()  # Uses your existing mapping

        if not presets:
            st.error(
                "fuel_presets() returned no mappings. Define fuel presets in `eia_client.py` "
                "to use this overview."
            )
            return

        fuel_labels = list(presets.keys())
        default_selection = fuel_labels[:4]

        selected_labels = st.multiselect(
            "Pick which series to include in the overview",
            options=fuel_labels,
            default=default_selection,
            help="These labels come from `EIA.fuel_presets()` and map to specific MER MSN codes.",
            key="mer_ann_labels",
        )

        if not selected_labels:
            st.info("Select at least one series to plot.")
            return

        msns = [presets[label]["msn"] for label in selected_labels]

        col1, col2 = st.columns(2)
        with col1:
            start_year = st.number_input(
                "Start year", 1950, 2100, 2000, key="mer_ann_start"
            )
        with col2:
            end_year = st.number_input(
                "End year", int(start_year), 2100, 2024, key="mer_ann_end"
            )

        if st.button("Load annual MER overview", key="mer_ann_load"):
            df = client.fetch_total_energy_multi(
                msns=msns,
                start_year=int(start_year),
                end_year=int(end_year),
                frequency="annual",
            )
            if df is None or df.empty:
                st.warning("Could not load annual MER data for this selection.")
                if client.last_error:
                    st.code(f"EIA error: {client.last_error}")
                if client.last_url:
                    st.caption(f"Requested URL: `{client.last_url}`")
                return

            # Attach human-readable labels
            msn_to_label = {info["msn"]: label for label, info in presets.items()}
            df["label"] = df["msn"].map(msn_to_label).fillna(df["msn"])

            st.markdown("#### Annual time series (long form)")
            st.dataframe(df, width='stretch')

            # Pivot wide for charting
            df_wide = (
                df.pivot(index="period", columns="label", values="value")
                .sort_index()
            )
            st.markdown("#### Trends over time")
            st.line_chart(df_wide, width='stretch')

            # Latest-year metrics
            try:
                df["period_num"] = df["period"].astype(int)
                latest_year = int(df["period_num"].max())
                df_latest = df[df["period_num"] == latest_year]

                st.markdown(f"#### Latest year snapshot – {latest_year}")

                cols = st.columns(len(df_latest))
                for (_, row), col in zip(df_latest.iterrows(), cols):
                    label = row["label"]
                    units = ""
                    for key, info in presets.items():
                        if info["msn"] == row["msn"]:
                            units = info.get("units", "")
                            break
                    with col:
                        st.metric(
                            label,
                            f"{row['value']:.2f} {units}".strip(),
                        )
            except Exception as e:
                st.error(f"Error summarizing latest values: {e}")

            st.markdown("---")
            st.markdown(
                "Use these annual values directly in assignments:\n"
                "- **A2**: Combine total energy, population and GDP MSNs to compute per-capita "
                "primary power and energy intensity.\n"
                "- **A3**: Choose two years from any series and plug into the Growth & Doubling "
                "Time tab on the Energy Calculations page."
            )

    # ------------------------------------------------------
    #  Mode 2: Monthly dashboard (last N months)
    # ------------------------------------------------------
    else:
        st.subheader("Monthly dashboard – recent trends")

        presets = client.fuel_presets()
        if not presets:
            st.error(
                "fuel_presets() returned no mappings. Define fuel presets in `eia_client.py` "
                "to use the monthly dashboard."
            )
            return

        fuel_labels = list(presets.keys())
        default_selection = fuel_labels[:3]

        selected_labels = st.multiselect(
            "Pick which series to track monthly",
            options=fuel_labels,
            default=default_selection,
            help="Typically: total energy + a couple of major fuels.",
            key="mer_monthly_labels",
        )

        if not selected_labels:
            st.info("Select at least one series.")
            return

        msns = [presets[label]["msn"] for label in selected_labels]

        # How far back to look
        months_back = st.slider(
            "Months to show",
            min_value=6,
            max_value=60,
            value=24,
            step=6,
            help="Window length for the monthly dashboard.",
            key="mer_months_back",
        )

        # Compute start/end year + month from 'today'
        today = dt.date.today()
        end_year = today.year
        end_month = today.month

        end_index = end_year * 12 + (end_month - 1)
        start_index = end_index - (months_back - 1)
        start_year = start_index // 12
        start_month = (start_index % 12) + 1

        if st.button("Load monthly dashboard", key="mer_monthly_load"):
            # 1) Try monthly
            df = client.fetch_total_energy_multi(
                msns=msns,
                start_year=start_year,
                end_year=end_year,
                frequency="monthly",
                start_month=start_month,
                end_month=end_month,
            )

            fallback_used = False

            # 2) If monthly returns nothing, fall back to annual
            if df is None or df.empty:
                df = client.fetch_total_energy_multi(
                    msns=msns,
                    start_year=start_year,
                    end_year=end_year,
                    frequency="annual",
                )
                if df is None or df.empty:
                    st.warning(
                        "Could not load monthly **or** annual MER data for this selection."
                    )
                    if client.last_error:
                        st.code(f"EIA error: {client.last_error}")
                    if client.last_url:
                        st.caption(f"Requested URL: `{client.last_url}`")
                    return
                else:
                    fallback_used = True
                    st.info(
                        "The selected MSNs appear to be annual-only in this dataset. "
                        "Showing **annual** values instead of monthly."
                    )

            msn_to_label = {info["msn"]: label for label, info in presets.items()}
            df["label"] = df["msn"].map(msn_to_label).fillna(df["msn"])

            # Parse period as datetime where possible
            period_str = df["period"].astype(str)
            sample = period_str.iloc[0]
            if len(sample) == 6:  # YYYYMM
                try:
                    df["period_dt"] = pd.to_datetime(period_str, format="%Y%m")
                except Exception:
                    df["period_dt"] = period_str
            elif len(sample) == 4:  # YYYY
                try:
                    df["period_dt"] = pd.to_datetime(period_str, format="%Y")
                except Exception:
                    df["period_dt"] = period_str
            else:
                df["period_dt"] = period_str

            st.markdown("#### Time series (long form)")
            st.dataframe(df.sort_values(["label", "period_dt"]), width='stretch')

            # Pivot to wide: index = period_dt, columns = label
            df_wide = (
                df.pivot(index="period_dt", columns="label", values="value")
                .sort_index()
            )
            st.markdown(
                "#### Recent trends"
                + (" (annual fallback)" if fallback_used else " (monthly)")
            )
            st.line_chart(df_wide, width='stretch')

            # Latest snapshot
            try:
                latest_ts = df["period_dt"].max()
                df_latest = df[df["period_dt"] == latest_ts]

                if isinstance(latest_ts, pd.Timestamp):
                    label_date = latest_ts.strftime("%Y-%m") if not fallback_used else latest_ts.strftime("%Y")
                else:
                    label_date = str(latest_ts)

                st.markdown(
                    "#### Latest "
                    + ("year" if fallback_used else "month")
                    + f" snapshot – {label_date}"
                )

                cols = st.columns(len(df_latest))
                for (_, row), col in zip(df_latest.iterrows(), cols):
                    fuel_label = row["label"]
                    units = ""
                    for key, info in presets.items():
                        if info["msn"] == row["msn"]:
                            units = info.get("units", "")
                            break
                    with col:
                        st.metric(
                            fuel_label,
                            f"{row['value']:.2f} {units}".strip(),
                        )
            except Exception as e:
                st.error(f"Error summarizing latest period: {e}")

        st.markdown("---")
        st.caption(
            "Monthly mode is limited by which MER MSNs have monthly data. "
            "If a series is annual-only, the dashboard automatically falls back "
            "to annual values over the same time window."
        )

def page_about():
    st.title("About This App")

    st.subheader("Acknowledgements")

    st.markdown(
        """
        This app was developed using concepts, assignments, and inspiration from
        **Professor Gregory Keoleian** and his course **Sustainable Energy Systems (EAS 574)**
        at the University of Michigan.

        Many of the calculation structures, scenario ideas, and transition themes are adapted from or inspired by
        that class. The focus on life cycle thinking, systems perspectives, and connecting technology choices to
        climate and societal outcomes comes directly from the EAS 574 curriculum.

        Thank you to Professor Keoleian and the Sustainable Energy Systems course for providing the foundation
        that made it possible to turn classroom material into an interactive tool for students and beginners
        exploring sustainable energy systems.
        """
    )

    st.markdown("---")

    st.markdown(
        """
        ### Why this exists

        This web-app was built by **Yvonne Amaria** to learn more about sustainable energy systems and to make it
        easier for beginners to **work through the real-world challenges** of becoming more sustainable.

        A lot of sustainability work today still depends on:
        - Manually digging through resources like **EIA** (U.S. Energy Information Administration) tables  
        - Running separate tools like **NREL PVWatts** in a browser  
        - Doing repetitive textbook calculations by hand over and over  

        The goal of this app is to **automate as much of that friction as possible**, so that students,
        early-career practitioners, and curious people can spend more time on:
        - Understanding *why* results look the way they do  
        - Comparing different transition options  
        - Thinking critically about policy, equity, and long-term impacts  

        It is also meant as a gentle critique of the sustainability community:  
        **we can and should build better tools**. Many of the painful steps people still do manually
        can be made automatic, transparent, and teachable.
        """
    )

    st.markdown("---")

    st.subheader("What this app can do")

    st.markdown(
        """
        Below is a quick tour of the main features. Most of them use a shared **scenario** defined in the sidebar:
        your location, building type, and annual energy use.

        #### 1. Energy Calculations (Student)

        - Designed around common homework-style tasks in sustainable energy / systems classes.  
        - Lets you enter as many or as few parameters as you have; missing inputs are handled gracefully.  
        - Shows formulas and units clearly so you can see *how* numbers were computed.  
        - Can auto-fill certain values (like fuel intensities) using EIA-style data, but also lets you override them.  
        - Includes built-in unit conversions so you do not have to chase “Btu vs kWh vs J” constantly.

        #### 2. Transition Tech: Electricity Generation

        - Compares options like **rooftop PV**, **ground-mount PV/carports**, **community solar**,  
          **utility green power / RECs**, and **onshore wind**.
        - Uses your scenario (state, load, rate, grid intensity) along with either:
          - **NREL PVWatts** (if you have an API key and location), or  
          - Classroom rule-of-thumb estimates as a fallback.
        - Calculates approximate:
          - Annual generation (kWh)  
          - Load coverage (%)  
          - Capex and annual bill savings  
          - Simple payback and CO₂ reductions  
        - Ranks options based on your stated goal (lower bills, maximize CO₂ reduction, or balanced).

        #### 3. Transition Tech: Transportation

        - Looks at **mode shift**, **EV adoption**, and **transit options** in a unified page.  
        - Lets you indicate whether you’re planning for an **individual, household, fleet, campus, or city**.  
        - Uses weights for cost, savings, CO₂ reduction, and payback to recommend transport actions, such as:
          - Replacing a gasoline car with a battery EV  
          - Shifting a portion of trips to walking, biking, and transit  
        - Includes qualitative guidance for improving **bus, train, and local transit** options.

        #### 4. Home Utilities & Household

        - Combines **Transition Tech: Utilities & Appliances** with a **Household Sustainability Guide**.  
        - Helps you think through:
          - Efficient appliances (e.g., heat pump water heaters, efficient fridges, induction cooktops)  
          - Plug loads, lighting, and simple control strategies  
          - What renters can do vs what owners can do  
        - Gives approximate payback and emissions impacts where appropriate, with classroom-level assumptions.

        #### 5. Carbon Sequestration

        - Introduces the purpose of **carbon sequestration**: reducing atmospheric CO₂ beyond simple emissions cuts.  
        - Provides simple formulas and calculators for:
          - Biological sequestration (trees, forests, soils)  
          - Point-source CCS (capture fraction × emissions)  
          - Direct Air Capture (DAC) with rough energy requirements per tonne  
          - Mineralization and solid storage concepts  
        - Focuses on helping students connect **math, units, and physical meaning** to real-world scale.

        #### 6. Conversions & Units

        - Quick reference and small calculators for:
          - Energy units (J, kWh, Btu, therm, etc.)  
          - Power units (kW, hp)  
          - Area units (acres, hectares, m²)  
          - Common prefixes (kilo, mega, giga, etc.)  
        - Designed to reduce unit anxiety during problem solving.

        #### 7. Fuel & Energy Data (EIA)

        - Uses EIA-style data access patterns to:
          - Pull fuel prices and intensities by **year** and **state** where available.  
          - Provide tables you can **download as CSV** for assignments or projects.  
        - The idea: no more hunting through long PDF appendices just to get one number.

        #### 8. AI, Policy & Sustainability Hub

        - Combines:
          - **AI & Sustainability**: how AI workloads affect energy use and emissions; where AI helps or hurts.  
          - **Social & Sustainability Education**: what individuals, companies, campuses, communities, and
            governments can realistically do.  
          - **Policy & Incentives**: ways to think about tax credits, rebates, and structural policy changes.  
        - Intended as a reading + reflection space that complements the “number-crunching” features.

        #### 9. Build Your Ideal Society (Game)

        - A gamified sandbox where you:
          - Set population, density, transit mode share, and land use  
          - Choose building efficiency measures, energy systems, and lifestyle factors  
        - The app generates:
          - Sustainability and resilience scores  
          - Very rough per-capita emissions numbers  
          - Feedback on where your society is strong vs weak  
        - Includes visuals and optional images for different “society vibes” (high risk → net-zero trailblazer).

        #### 10. Annual Energy Review

        - A compact way to view summarized national energy statistics.  
        - Designed for quickly pulling **context slides, background figures, and trends** for reports/posters.  
        - Often paired with the EIA data feature for deeper dives.
        """
    )

    st.markdown("---")

    st.subheader("How to use this app if you're a beginner")

    st.markdown(
        """
        You do **not** need to be an expert to use this. Here is a simple starting path:

        1. **Set up your scenario in the sidebar**

           - Pick your **state** and (optionally) city and ZIP code.  
           - Choose a **building type** (residential, commercial, campus, etc.).  
           - Estimate **annual electricity use (kWh)** from recent bills or course assumptions.  
           - Keep the default electric rate and discount rate unless your assignment tells you otherwise.

           This scenario automatically feeds into most of the calculators so you don’t have to re-enter the same
           information on every page.

        2. **If you’re doing homework**

           - Go to **Energy Calculations (Student)**.  
           - Look for the problem type that matches your assignment.  
           - Enter the inputs you know; leave the rest blank or use defaults.  
           - Use the result explanations and unit notes to **check your reasoning**, not just your final numbers.  
           - Use the **Conversions & Units** page when you’re unsure about unit changes.

        3. **If you’re sketching a project or retrofit idea**

           - Start with **Transition Tech: Electricity Generation** to see what PV / wind / green power might look like.  
           - Then open **Transition Tech: Transportation** to think through commuting, fleets, and transit options.  
           - Visit **Home Utilities & Household** for appliance-level or interior upgrades.  

           You can download CSV tables from several pages to include in your report or presentation.

        4. **If you’re writing an essay, memo, or poster**

           - Use **Carbon Sequestration** for basic formulas and conceptual explanations.  
           - Use **AI, Policy & Sustainability Hub** to structure arguments about:
             - what individuals and institutions can do, and  
             - where automation (like this tool) can lower barriers.  
           - Use **Annual Energy Review** and **Fuel & Energy Data (EIA)** to add quantitative context.

        5. **If you just want to explore**

           - Try **Build Your Ideal Society** and see how different choices affect scores and emissions.  
           - Use it as a way to connect **behavior, infrastructure, and policy** in a single mental model.

        Remember: this app is meant as a **learning companion**, not a professional design tool.
        Treat results as **first-pass, classroom-level estimates**, then refine with more detailed tools or data if needed.
        """
    )

    st.markdown("---")

    st.subheader("Data, automation, and limitations")

    st.markdown(
        """
        - Many numbers and formulas are simplified on purpose. They are tuned to be:
          - transparent enough to follow step-by-step, and  
          - realistic enough for coursework and early planning conversations.  
        - Where possible, the app uses structured data (like EIA-type datasets or PVWatts outputs) rather than
          hard-coding constants, to show how **automation can lower the barrier** to using serious data sources.  
        - Assumptions, default values, and limitations are explained on each feature page; they are part of the
          learning experience.

        If you find places where something could be clearer or more automated, that is part of the point:
        Please reach out to me **yvonneoa@umich.edu.** It shows **how much room there is to improve tools in the sustainability community**.
        """
    )

    # Optional small note if scenario is present
    scen: ScenarioInput | None = st.session_state.get("scenario")
    if scen is not None:
        site = scen.site
        st.markdown("---")
        st.caption(
            f"Current scenario in use: {site.building_type or 'unspecified'} in "
            f"{(site.city or '')} {site.state or ''} {site.zipcode or ''}, "
            f"{(site.annual_electricity_kwh or 0):,.0f} kWh/yr at "
            f"${scen.elec_rate_usd_per_kwh:.3f}/kWh."
        )


# ---------------------------------
# Helpers
# ---------------------------------

def _set_page(name: str):
    st.session_state.page = name

def _route():
    page = st.session_state.page
    scen = st.session_state.scenario
    if page == "home":
        page_home()
    elif page == "homework":
        page_homework_tools()
    elif page == "calc":
        page_energy_calculations()
    elif page == "transition_gen":
        page_transition_generation()
    elif page == "home_utilities":
        page_home_utilities(scen)
    elif page == "transition_transport":
        page_transition_transport(scen)   
    elif page == "pv_tools":
        page_pv_tools()
    elif page == "sequestration":
        page_sequestration()
    elif page == "eia":
        page_eia()
    elif page == "conversions":
        page_conversions()
    elif page == "knowledge":
        page_ai_education_policy(scen)
    elif page == "monthly_review":
        page_monthly_review()
    elif page == "ideal_society":
        page_ideal_society()
    elif page == "about":
        page_about()


# ---------------------------------
# Entry
# ---------------------------------

def main():
    st.set_page_config(page_title="Sustainable Energy Systems Solutions", layout="wide")
    _init_state()
    scen = sidebar_site()
    _route()


if __name__ == "__main__":
    main()

