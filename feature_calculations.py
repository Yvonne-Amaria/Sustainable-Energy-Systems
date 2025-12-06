# feature_calculations.py

from __future__ import annotations

import io
import math
import pandas as pd
import streamlit as st

from tools import (
    pv_area_for_avg_power,
    capacity_factor,
    panel_efficiency,
    carbon_intensity_from_fc_hhv,
    carbon_intensity_from_formula,
    wind_region_potential,
    biomass_poplar_land_for_power,
    trucks_per_day,
)
from conversions import convert_value, UNITS
from eia_client import EIA


# ---------------- Helpers ----------------


def _optional(val: str | None):
    """Treat empty strings as None."""
    return None if val in ("", None) else val


def _section_header(title: str, explainer: str):
    st.subheader(title)
    st.caption(explainer)


def _safe_float(label: str, val: str):
    """Convert a string to float; if fail, show a message and return None."""
    if val is None or val == "":
        return None
    try:
        return float(val)
    except ValueError:
        st.error(f"{label}: please enter a number.")
        return None


def _safe_int(label: str, val: str):
    if val is None or val == "":
        return None
    try:
        return int(float(val))
    except ValueError:
        st.error(f"{label}: please enter an integer.")
        return None


def _crf(rate: float, years: int) -> float:
    """Capital recovery factor."""
    if rate <= 0:
        return 1.0 / years
    num = rate * (1.0 + rate) ** years
    den = (1.0 + rate) ** years - 1.0
    return num / den


# ---------------- Main page ----------------


def page_energy_calculations():
    st.header("Energy Calculations (Student)")
    st.write(
        "Use this page as your **homework calculator hub**. "
        "All inputs are optional; we compute whatever is possible from what you provide, "
        "and clearly label when a parameter is missing."
    )

    # ---------- EIA helper (global) ----------
    st.markdown("### Optional: EIA Auto-Fill Helper")
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

    eia_client = EIA(api_key) if api_key else None

    with st.expander("Auto-fill from EIA (optional)", expanded=False):
        st.caption(
            "Preview **state electricity price** from EIA v2. "
            "If EIA is unavailable (e.g., 403 Forbidden), you can still type values manually."
        )
        col1, col2 = st.columns(2)
        with col1:
            eia_year = st.number_input("Year", 1990, 2100, 2024, key="eia_year_calc")
        with col2:
            eia_state = st.text_input("State (2-letter)", "MI", key="eia_state_calc").upper()

        if st.button("Fetch sample price", key="calc_eia"):
            if eia_client is None or not eia_client.available():
                st.error("Provide an EIA API key above to query live data.")
            else:
                df_eia = eia_client.fetch_series(
                    year=int(eia_year),
                    state=eia_state,
                    fuel="electricity",
                    series="price",
                    sector="total",
                    frequency="annual",
                )
                if df_eia is None:
                    st.warning("No data returned for this selection.")
                    if eia_client.last_error:
                        st.code(f"EIA error: {eia_client.last_error}")
                    if eia_client.last_url:
                        st.caption(f"Requested URL: `{eia_client.last_url}`")
                else:
                    st.success("Loaded. Copy any price you need.")
                    st.dataframe(df_eia, width="stretch")
                    if "price_usd_per_kwh" in df_eia.columns:
                        st.metric(
                            "Avg retail price",
                            f"{float(df_eia['price_usd_per_kwh'].iloc[0]):.3f} USD/kWh",
                        )


    st.markdown("---")

    tabs = st.tabs(
        [
            "A1 & A7 – Energy & PV",
            "A3 – Growth & Doubling Time",
            "A5 – Plant Economics (CRF & LCOE)",
            "A6 & A8 – Wind & Biomass",
            "A3 – Fuel Carbon Intensity",
            "A9 – Vehicles & Wedges",
            "Excel/CSV Tools",
            "Unit Conversions",
        ]
    )

    # -------------------------------------------------
    # Tab 0: A1 & A7 – Energy basics + PV & CF
    # -------------------------------------------------
    with tabs[0]:
        # ----- A1: basic energy relationships -----
        _section_header(
            "A1: Energy, Power, and Time",
            "Use these for classic P = E / t relationships. Provide any two, "
            "and the calculator will solve for the third.",
        )
        st.latex(r"P = \frac{E}{t}, \quad E = P t, \quad t = \frac{E}{P}")
        col_a1_left, col_a1_right = st.columns(2)

        with col_a1_left:
            solve_for = st.radio(
                "Solve for",
                ["Energy E", "Power P", "Time t"],
                horizontal=True,
                key="a1_solve_for",
            )

        with col_a1_right:
            if solve_for == "Energy E":
                P_str = st.text_input("Power P (kW)", value="", key="a1_P")
                t_str = st.text_input("Time t (hours)", value="", key="a1_t")
                P = _safe_float("Power P", P_str)
                t = _safe_float("Time t", t_str)
                if P is not None and t is not None:
                    E = P * t
                    st.metric("Energy E", f"{E:,.3f} kWh")
                else:
                    st.info("Energy E: parameter not provided (need P and t).")

            elif solve_for == "Power P":
                E_str = st.text_input("Energy E (kWh)", value="", key="a1_E")
                t_str = st.text_input("Time t (hours)", value="", key="a1_t2")
                E = _safe_float("Energy E", E_str)
                t = _safe_float("Time t", t_str)
                if E is not None and t is not None:
                    if t == 0:
                        st.error("Time t cannot be zero.")
                    else:
                        P = E / t
                        st.metric("Power P", f"{P:,.3f} kW")
                else:
                    st.info("Power P: parameter not provided (need E and t).")

            else:  # solve_for == "Time t"
                E_str = st.text_input("Energy E (kWh)", value="", key="a1_E2")
                P_str = st.text_input("Power P (kW)", value="", key="a1_P2")
                E = _safe_float("Energy E", E_str)
                P = _safe_float("Power P", P_str)
                if E is not None and P is not None:
                    if P == 0:
                        st.error("Power P cannot be zero.")
                    else:
                        t = E / P
                        st.metric("Time t", f"{t:,.3f} hours")
                else:
                    st.info("Time t: parameter not provided (need E and P).")

        st.markdown("---")

        # ----- A7: PV area, efficiency, capacity factor -----
        _section_header(
            "A7: PV Area & Efficiency",
            "Relates average power, solar resource, and module efficiency.",
        )
        st.latex(r"A = \frac{P_{\text{avg}} \cdot 24}{\eta \, G_{\text{year}}}")
        st.caption(
            r"Here $A$ is array area [m²], $P_{\text{avg}}$ is average power [kW], "
            r"$\eta$ is module efficiency, and $G_{\text{year}}$ is annual average insolation [kWh/m²-day]."
        )
        st.latex(r"\eta = \frac{P_{\text{out}}}{G \, A}")
        st.caption(
            r"Module efficiency from nameplate power $P_{\text{out}}$ and irradiance $G$ "
            r"(typically 1000 W/m² at STC)."
        )

        with st.expander("User inputs for PV (all optional)", expanded=True):
            pavg_mw_str = st.text_input("Average power target (MW)", value="", key="pv_pavg_mw")
            eta_str = st.text_input("PV conversion efficiency (0–1)", value="", key="pv_eta")
            G_year_str = st.text_input(
                "Yearly avg solar resource G_year [kWh/m²-day]",
                value="",
                key="pv_G_year",
            )
            p_w_str = st.text_input("Module nameplate (W)", value="", key="pv_p_w")
            area_m2_str = st.text_input("Module area (m²)", value="", key="pv_area_m2")

        pavg_mw = _safe_float("Average power target", pavg_mw_str)
        eta_val = _safe_float("PV efficiency", eta_str)
        G_year = _safe_float("G_year", G_year_str)

        if pavg_mw is not None and eta_val is not None and G_year is not None:
            try:
                area_result = pv_area_for_avg_power(pavg_mw * 1000.0, eta_val, G_year)
                st.metric("Required PV area", f"{area_result:,.0f} m²")
            except Exception as e:
                st.error(f"PV area calculation error: {e}")
        else:
            st.info("PV area: parameter not provided (need P_avg, η, G_year).")

        p_w = _safe_float("Module nameplate", p_w_str)
        panel_area = _safe_float("Module area", area_m2_str)
        if p_w is not None and panel_area is not None and panel_area != 0:
            try:
                eff = panel_efficiency(p_w, panel_area)
                st.metric("Module efficiency", f"{100 * eff:.2f}%")
            except Exception as e:
                st.error(f"Efficiency calculation error: {e}")
        else:
            st.info("Module efficiency: parameter not provided (need P_out and area).")

        _section_header(
            "A7: Monthly Capacity Factor",
            "Capacity factor from monthly AC energy.",
        )
        st.latex(r"\text{CF} = \frac{E_{\text{month}}}{P_{\text{AC}} \cdot 24 \cdot \text{days}}")

        with st.expander("User inputs for CF (optional)", expanded=True):
            e_month_str = st.text_input("Monthly AC energy (kWh)", value="", key="cf_E_month")
            pac_kw_str = st.text_input("AC nameplate (kW)", value="", key="cf_P_ac")
            days_str = st.text_input("Days in month", value="", key="cf_days")

        e_month = _safe_float("Monthly AC energy", e_month_str)
        pac_kw = _safe_float("AC nameplate", pac_kw_str)
        days_val = _safe_int("Days in month", days_str)

        if e_month is not None and pac_kw is not None and days_val is not None:
            try:
                cf_val = capacity_factor(e_month, pac_kw, days_val)
                st.metric("Capacity Factor", f"{100 * cf_val:.1f}%")
            except Exception as e:
                st.error(f"CF calculation error: {e}")
        else:
            st.info("Capacity Factor: parameter not provided (need E_month, P_AC, days).")

    # -------------------------------------------------
    # Tab 1: A3 – Growth & doubling time
    # -------------------------------------------------
    with tabs[1]:
        _section_header(
            "A3: Exponential Growth & Doubling Time",
            "Use this for MER-style growth problems or any time you have values at two points in time.",
        )
        st.latex(r"E(t) = E_0 \, e^{r t}")
        st.latex(r"r = \frac{1}{t} \ln\left(\frac{E(t)}{E_0}\right)")
        st.latex(r"t_{\text{double}} = \frac{\ln 2}{r}")

        col_g1, col_g2 = st.columns(2)
        with col_g1:
            E0_str = st.text_input("Initial value $E_0$ (e.g., primary energy in year 0)", key="growth_E0")
            Et_str = st.text_input("Final value $E(t)$ (same units as $E_0$)", key="growth_Et")
        with col_g2:
            t_years_str = st.text_input("Time between (years)", key="growth_t")

        E0 = _safe_float("E0", E0_str)
        Et = _safe_float("Et", Et_str)
        t_years = _safe_float("Time (years)", t_years_str)

        if E0 is not None and Et is not None and t_years is not None and t_years > 0 and E0 > 0:
            try:
                r = (math.log(Et / E0)) / t_years
                t_double = math.log(2.0) / r if r != 0 else float("inf")
                st.metric("Growth rate r", f"{100 * r:.3f}% per year")
                st.metric("Doubling time", f"{t_double:.2f} years")
            except Exception as e:
                st.error(f"Growth calculation error: {e}")
        else:
            st.info("Provide E0, Et, and time in years to compute r and doubling time.")

        st.markdown(
            "_For more complex growth problems with many data points, upload your table in the "
            "**Excel/CSV Tools** tab and use the growth preset there._"
        )

    # -------------------------------------------------
    # Tab 2: A5 – Plant economics (CRF & LCOE)
    # -------------------------------------------------
    with tabs[2]:
        _section_header(
            "A5: Capital Recovery Factor (CRF) & LCOE",
            "Use this for power plant economics (capital recovery, cost of electricity).",
        )
        st.latex(
            r"\text{CRF}(i, n) = \frac{i (1 + i)^n}{(1 + i)^n - 1}"
        )
        st.latex(
            r"\text{LCOE}_\text{capex} = \frac{\text{CRF} \cdot K}{8760 \cdot \text{CF}}"
        )
        st.caption(
            r"$K$ is the overnight capital cost [USD/kW], CF is capacity factor (0–1). "
            r"Add fuel and O&M terms if the assignment specifies them."
        )

        col_a5_1, col_a5_2 = st.columns(2)
        with col_a5_1:
            rate_str = st.text_input("Real discount rate i (e.g., 0.07)", "0.07", key="a5_rate")
            years_str = st.text_input("Plant lifetime n (years)", "30", key="a5_years")
            K_str = st.text_input("Capital cost K (USD/kW)", "3000", key="a5_K")
            CF_str = st.text_input("Capacity factor CF (0–1)", "0.85", key="a5_CF")
        with col_a5_2:
            fuel_om_str = st.text_input(
                "Fuel + O&M (optional, ¢/kWh)",
                value="0.0",
                key="a5_fuel_om",
            )
            st.caption(
                "If you have a combined fuel + O&M cost from the problem (e.g. 2.5 ¢/kWh), put it here."
            )

        rate = _safe_float("Discount rate", rate_str)
        years = _safe_int("Lifetime", years_str)
        K = _safe_float("Capital cost K", K_str)
        CF_a5 = _safe_float("Capacity factor CF", CF_str)
        fuel_om = _safe_float("Fuel + O&M (¢/kWh)", fuel_om_str)

        if rate is not None and years is not None and K is not None and CF_a5 is not None and CF_a5 > 0:
            crf_val = _crf(rate, years)
            cap_lcoe = crf_val * K / (8760.0 * CF_a5)  # USD/kWh
            st.metric("CRF", f"{crf_val:.4f}")
            st.metric("Capital component of LCOE", f"{cap_lcoe * 100:.2f} ¢/kWh")

            if fuel_om is not None:
                total_lcoe = cap_lcoe * 100 + fuel_om  # ¢/kWh
                st.metric("Total LCOE (approx)", f"{total_lcoe:.2f} ¢/kWh")
        else:
            st.info("Provide i, n, K, and CF to compute CRF and capital LCOE.")

    # -------------------------------------------------
    # Tab 3: A6 & A8 – Wind & Biomass
    # -------------------------------------------------
    with tabs[3]:
        _section_header(
            "A6: Wind region potential",
            "Estimate regional wind generation from land area, capacity density, and capacity factor.",
        )
        st.latex(r"\bar{P} = A \cdot D")
        st.latex(r"E_{\text{year}} = \bar{P} \cdot 8760 \cdot \text{CF}")
        col_w1, col_w2 = st.columns(2)
        with col_w1:
            area_km2 = st.number_input(
                "Region area (km²)",
                min_value=0.0,
                value=1500.0,
                step=50.0,
                key="wind_area",
            )
            density_mw_km2 = st.number_input(
                "Installed capacity density (MW/km²)",
                min_value=0.0,
                value=4.25,
                step=0.25,
                key="wind_density",
            )
        with col_w2:
            cf_wind = st.number_input(
                "Capacity factor (0–1)",
                min_value=0.0,
                max_value=1.0,
                value=0.40,
                step=0.01,
                key="wind_cf",
            )

        if area_km2 > 0 and density_mw_km2 > 0 and cf_wind > 0:
            try:
                twh = wind_region_potential(area_km2, density_mw_km2, cf_wind)
                st.metric("Annual generation", f"{twh:.2f} TWh/yr")
            except Exception as e:
                st.error(f"Wind potential error: {e}")
        else:
            st.info("Provide area, density, and CF to compute wind generation.")

        st.markdown("---")
        _section_header(
            "A8: Biomass land & trucks",
            "Estimate required plantation area and truck traffic for a biomass power plant.",
        )
        st.latex(r"E_{\text{elec,year}} = P_{\text{plant}} \cdot 8760 \cdot \text{CF}")
        st.latex(
            r"A_{\text{land}} = \frac{E_{\text{elec,year}} / \eta_{\text{net}}}{\text{HHV} \cdot Y}"
        )
        col_b1, col_b2 = st.columns(2)
        with col_b1:
            plant_mw = st.number_input(
                "Plant net output (MW)", 0.0, 2000.0, 135.0, key="bio_plant_mw"
            )
            cf_bio = st.number_input(
                "Capacity factor (0–1)", 0.0, 1.0, 0.83, key="bio_cf"
            )
            net_eff = st.number_input(
                "Net electrical efficiency (J_e / J_fuel)", 0.0, 1.0, 0.372, key="bio_eta"
            )
        with col_b2:
            HHV_kJkg = st.number_input(
                "Biomass HHV (kJ/kg)", 0.0, 40000.0, 20270.0, key="bio_HHV"
            )
            yield_Mg_ha_yr = st.number_input(
                "Avg annual dry yield (Mg/ha-yr)", 0.0, 100.0, 13.0, key="bio_yield"
            )

        if (
            plant_mw > 0
            and cf_bio > 0
            and net_eff > 0
            and HHV_kJkg > 0
            and yield_Mg_ha_yr > 0
        ):
            try:
                area_ha = biomass_poplar_land_for_power(
                    net_eff, cf_bio, plant_mw, HHV_kJkg, yield_Mg_ha_yr
                )
                st.metric("Required plantation area", f"{area_ha:,.0f} ha")

                # Very rough truck calculation
                kg_year = (plant_mw * 1e6 * 8760.0 * cf_bio * 3.6) / net_eff / HHV_kJkg
                trucks = trucks_per_day(kg_year, kg_per_truck=18000.0)
                st.metric("Truckloads per day", f"{trucks:.0f} trucks/day")
            except Exception as e:
                st.error(f"Biomass calculation error: {e}")
        else:
            st.info("Provide MW, CF, efficiency, HHV, and yield to compute area and trucks.")

    # -------------------------------------------------
    # Tab 4: A3 – Fuel Carbon Intensity
    # -------------------------------------------------
    with tabs[4]:
        _section_header(
            "A3: Fuel Carbon Intensity",
            "Compute CO₂ emission factor from mass fraction of carbon or from chemical formula.",
        )
        st.latex(r"\text{CI} = \frac{f_C \cdot 44/12}{\text{HHV}}")
        st.caption(
            r"$\text{CI}$ is in kg CO₂ per MJ of fuel, $f_C$ is carbon mass fraction, HHV is in MJ/kg."
        )
        st.latex(
            r"f_C = \frac{12 n_C}{12 n_C + 1 n_H} \quad \Rightarrow \quad "
            r"\text{CI} = \frac{f_C \cdot 44/12}{\text{HHV}}"
        )

        with st.expander("User inputs (optional)", expanded=True):
            fc_str = st.text_input("Carbon mass fraction f_C (0–1)", value="", key="ci_fc")
            hhv_str = st.text_input("HHV (MJ/kg)", value="", key="ci_hhv")
            nC_str = st.text_input("Carbon atoms n_C", value="", key="ci_nC")
            nH_str = st.text_input("Hydrogen atoms n_H", value="", key="ci_nH")
            hhv2_str = st.text_input(
                "HHV for formula method (MJ/kg)", value="", key="ci_hhv2"
            )

        fc = _safe_float("f_C", fc_str)
        hhv = _safe_float("HHV", hhv_str)
        if fc is not None and hhv is not None and hhv > 0:
            try:
                ci = carbon_intensity_from_fc_hhv(fc, hhv)
                st.metric("kg CO₂ per MJ (from f_C, HHV)", f"{ci:.4f}")
            except Exception as e:
                st.error(f"CI error (f_C,HHV): {e}")
        else:
            st.info("CI (f_C, HHV): parameter not provided or invalid.")

        nC = _safe_int("n_C", nC_str)
        nH = _safe_int("n_H", nH_str)
        hhv2 = _safe_float("HHV (formula method)", hhv2_str)
        if nC is not None and nH is not None and hhv2 is not None and hhv2 > 0:
            try:
                ci2 = carbon_intensity_from_formula(nC, nH, hhv2)
                st.metric("kg CO₂ per MJ (from formula, HHV)", f"{ci2:.4f}")
            except Exception as e:
                st.error(f"CI error (formula): {e}")
        else:
            st.info("CI (formula): parameter not provided or invalid.")

    # -------------------------------------------------
    # Tab 5: A9 – Vehicles & wedges
    # -------------------------------------------------
    with tabs[5]:
        _section_header(
            "A9: Vehicle Emissions & Wedge Scaling",
            "Estimate per-vehicle emissions and how many vehicles you'd need to change "
            "to create a ~1 GtCO₂/yr wedge.",
        )
        st.latex(r"E_{\text{veh}} = \text{VMT} \times \frac{1}{\text{mpg}} \times \text{EF}_{\text{fuel}}")
        st.caption(
            r"Here VMT is miles/year, mpg is fuel economy, and EF is an emission factor (e.g. "
            r"$8.89\ \text{kg CO₂/gal}$ for gasoline)."
        )

        col_v1, col_v2 = st.columns(2)
        with col_v1:
            vmt_str = st.text_input("Annual VMT (miles/year)", "12000", key="veh_vmt")
            mpg_base_str = st.text_input("Baseline vehicle fuel economy (mpg)", "25", key="veh_mpg_base")
            mpg_new_str = st.text_input(
                "New tech fuel economy (mpg, use a big number or EV equivalent)", "100", key="veh_mpg_new"
            )
        with col_v2:
            ef_str = st.text_input(
                "Fuel CO₂ emission factor (kg CO₂/gal)", "8.89", key="veh_ef"
            )
            target_gt_str = st.text_input(
                "Target reduction for wedge (Gt CO₂/yr)", "1.0", key="veh_target"
            )

        vmt = _safe_float("VMT", vmt_str)
        mpg_base = _safe_float("Baseline mpg", mpg_base_str)
        mpg_new = _safe_float("New tech mpg", mpg_new_str)
        ef = _safe_float("Emission factor", ef_str)
        target_gt = _safe_float("Target GtCO₂/yr", target_gt_str)

        if (
            vmt is not None
            and mpg_base is not None
            and mpg_new is not None
            and ef is not None
            and mpg_base > 0
            and mpg_new > 0
        ):
            try:
                E_base_kg = vmt / mpg_base * ef
                E_new_kg = vmt / mpg_new * ef
                delta_kg = E_base_kg - E_new_kg
                st.metric("Baseline vehicle emissions", f"{E_base_kg / 1000:.2f} tCO₂/yr")
                st.metric("New tech vehicle emissions", f"{E_new_kg / 1000:.2f} tCO₂/yr")
                st.metric("Savings per vehicle", f"{delta_kg / 1000:.2f} tCO₂/yr")

                if target_gt is not None and target_gt > 0 and delta_kg > 0:
                    target_kg = target_gt * 1e9 * 1000.0  # 1 Gt = 1e9 t; t→kg
                    N = target_kg / delta_kg
                    st.metric(
                        "Vehicles needed for wedge",
                        f"{N:,.0f} vehicles",
                    )
                else:
                    st.info("Provide a positive wedge target and savings per vehicle to estimate number of vehicles.")
            except Exception as e:
                st.error(f"Vehicle emissions calculation error: {e}")
        else:
            st.info("Provide VMT, baseline mpg, new mpg, and emission factor to compute per-vehicle emissions.")

    # -------------------------------------------------
    # Tab 6: Excel/CSV Tools – homework-style presets
    # -------------------------------------------------
    with tabs[6]:
        _section_header(
            "Excel/CSV Tools",
            "Upload a file, inspect it, and apply homework-style operations such as growth rate "
            "or capacity factor.",
        )

        uploaded = st.file_uploader("Upload .xlsx/.xls/.csv", type=["xlsx", "xls", "csv"])
        df = None
        if uploaded:
            if uploaded.name.lower().endswith(".csv"):
                df = pd.read_csv(uploaded)
            else:
                xf = pd.ExcelFile(uploaded)
                sheet = st.selectbox("Sheet", xf.sheet_names)
                header_row = st.number_input("Header row (1-based)", 1, 100, 1)
                usecols = st.text_input("Columns (e.g., A:D or names comma-separated)", "A:D")
                nrows = st.number_input("Rows to read (0 = all)", 0, 100000, 0)
                read_kwargs = dict(sheet_name=sheet, header=header_row - 1)
                if usecols:
                    read_kwargs["usecols"] = usecols
                if nrows > 0:
                    read_kwargs["nrows"] = nrows
                df = pd.read_excel(uploaded, **read_kwargs)

            st.markdown("**Preview (first 100 rows)**")
            st.dataframe(df.head(100), width="stretch")

            st.markdown("---")
            st.subheader("Operations")
            op = st.radio(
                "Choose operation",
                [
                    "A3: Growth rate from first & last row",
                    "A6/A7: Capacity factor from time series",
                    "Custom: scale a numeric column",
                ],
                key="csv_op",
            )

            if op == "A3: Growth rate from first & last row":
                time_col = st.selectbox("Time column (year or index)", df.columns, key="csv_time_col")
                value_col = st.selectbox(
                    "Value column (e.g., primary energy)", df.columns, key="csv_value_col"
                )
                df_sorted = df.sort_values(by=time_col)
                if df_sorted[value_col].notna().sum() >= 2:
                    E0 = df_sorted[value_col].iloc[0]
                    Et = df_sorted[value_col].iloc[-1]
                    # assume time_col is numeric years
                    try:
                        t0 = float(df_sorted[time_col].iloc[0])
                        tt = float(df_sorted[time_col].iloc[-1])
                        dt = tt - t0
                        if dt > 0 and E0 > 0:
                            r = (math.log(Et / E0)) / dt
                            t_double = math.log(2.0) / r if r != 0 else float("inf")
                            st.metric("Growth rate r", f"{100 * r:.3f}% per year")
                            st.metric("Doubling time", f"{t_double:.2f} years")
                        else:
                            st.warning("Check that time increases and E0 > 0.")
                    except Exception as e:
                        st.error(f"Could not interpret time column: {e}")
                else:
                    st.warning("Need at least two non-missing values for this operation.")

            elif op == "A6/A7: Capacity factor from time series":
                power_col = st.selectbox(
                    "Power column (e.g., MW or kW)", df.columns, key="csv_power_col"
                )
                rated_power_str = st.text_input(
                    "Rated power (same units as column)", "1.0", key="csv_rated_power"
                )
                rated_power = _safe_float("Rated power", rated_power_str)
                if rated_power is not None and rated_power > 0:
                    if pd.api.types.is_numeric_dtype(df[power_col]):
                        avg_p = df[power_col].mean()
                        cf_ts = avg_p / rated_power
                        st.metric("Average power", f"{avg_p:.3f} (same units as column)")
                        st.metric("Capacity factor", f"{100 * cf_ts:.2f}%")
                    else:
                        st.warning("Selected column is not numeric.")
                else:
                    st.info("Provide a positive rated power to compute CF.")

            else:  # Custom scaling
                num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
                if num_cols:
                    col = st.selectbox("Numeric column", num_cols, key="csv_scale_col")
                    factor = st.number_input("Multiply by", value=1.0, key="csv_scale_factor")
                    df_out = df.copy()
                    df_out[f"{col}_scaled"] = df_out[col] * factor
                    st.dataframe(df_out.head(100), width="stretch")

                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
                        df_out.to_excel(writer, sheet_name="Calculated", index=False)
                    st.download_button(
                        "Download Excel with scaled column",
                        data=buf.getvalue(),
                        file_name="calculated.xlsx",
                    )
                else:
                    st.info("No numeric columns detected. Adjust columns or header row.")
        else:
            st.info("Upload a .csv or Excel file to use these tools.")

    # -------------------------------------------------
    # Tab 7: Unit Conversions
    # -------------------------------------------------
    with tabs[7]:
        _section_header(
            "Unit Conversions",
            "Quickly convert between common units used in the assignments.",
        )

        c1, c2, c3 = st.columns(3)
        with c1:
            val = st.number_input("Value", value=1.0, key="conv_val_main")
        with c2:
            u_from = st.selectbox("From", sorted(UNITS), key="conv_from_main")
        with c3:
            u_to = st.selectbox("To", sorted(UNITS), key="conv_to_main")

        try:
            conv = convert_value(val, u_from, u_to)
            st.metric("Converted", f"{conv:g} {u_to}")
        except Exception as e:
            st.error(f"Conversion error: {e}")

        st.markdown(
            "_For a more detailed list of conversions and prefixes, use the dedicated **Conversion Factors & Units** page in the sidebar._"
        )
