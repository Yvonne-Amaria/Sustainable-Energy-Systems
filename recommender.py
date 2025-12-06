# recommender.py
from __future__ import annotations

import numpy as np
import pandas as pd
import requests

from models import ScenarioInput
from data_connectors import DataConnectors

# PV helpers

def pv_energy_yield_kw(lat: float, lon: float, system_kwdc: float, kwh_per_kw_year: float | None = None) -> float:
    if kwh_per_kw_year is None:
        ghi = DataConnectors.solar_resource(lat, lon)["GHI_kWhm2_day"]
        kwh_per_kw_year = 300 * ghi  # rule-of-thumb
    return system_kwdc * kwh_per_kw_year

def pv_capex_usd(system_kwdc: float, cost_per_kw: float = 1800) -> float:
    return system_kwdc * cost_per_kw

def simple_payback(capex: float, annual_savings: float) -> float:
    return capex / annual_savings if annual_savings > 0 else float("inf")

def lcoe(capex: float, annual_om: float, annual_gen: float, discount: float, years: int) -> float:
    crf = (discount * (1 + discount) ** years) / (((1 + discount) ** years) - 1)
    aac = capex * crf + annual_om
    return float("inf") if annual_gen <= 0 else aac / annual_gen

class Recommender:
    """Rule-based + MCDA with practicality and carbon."""

    @staticmethod
    def score_options(scen: ScenarioInput) -> pd.DataFrame:
        rows: list[dict] = []

        annual_kwh = scen.site.annual_electricity_kwh or 10000
        pv_size_kw = max(1.0, round(annual_kwh / 1400, 1))

        # --- PV option ---
        lat, lon = (scen.site.lat or 42.3, scen.site.lon or -83.1)
        pv_gen = pv_energy_yield_kw(lat, lon, pv_size_kw)
        pv_capex = pv_capex_usd(pv_size_kw)
        pv_om = 0.015 * pv_capex
        rate = scen.elec_rate_usd_per_kwh
        annual_savings = min(pv_gen, annual_kwh) * rate
        payback = simple_payback(pv_capex, annual_savings)
        pv_lcoe = lcoe(pv_capex, pv_om, pv_gen, scen.discount_rate, scen.analysis_years)
        co2e_red = min(pv_gen, annual_kwh) * scen.grid_emissions_kgco2e_per_kwh

        rows.append({
            "Option": f"Solar PV ~{pv_size_kw} kWdc",
            "Category": "generation",
            "Capex_USD": pv_capex,
            "Annual_Gen_kWh": pv_gen,
            "Annual_Savings_USD": annual_savings,
            "Simple_Payback_yr": payback,
            "LCOE_USD_per_kWh": pv_lcoe,
            "CO2e_Reduction_tpy": co2e_red / 1000.0,
            "Practicality": 0.8,
        })

        # --- Efficiency option ---
        eff_capex = 0.05 * pv_capex
        eff_savings = 0.08 * annual_kwh * rate
        rows.append({
            "Option": "Efficiency: LED + HVAC tune-up",
            "Category": "efficiency",
            "Capex_USD": eff_capex,
            "Annual_Gen_kWh": 0.0,
            "Annual_Savings_USD": eff_savings,
            "Simple_Payback_yr": simple_payback(eff_capex, eff_savings),
            "LCOE_USD_per_kWh": np.nan,
            "CO2e_Reduction_tpy": (0.08 * annual_kwh * scen.grid_emissions_kgco2e_per_kwh) / 1000.0,
            "Practicality": 0.95,
        })

        # --- HPWH option (residential only) ---
        if scen.site.building_type == "residential":
            hpwh_capex = 2000.0
            hpwh_kwh_savings = 1200.0
            rows.append({
                "Option": "Heat Pump Water Heater",
                "Category": "utilities",
                "Capex_USD": hpwh_capex,
                "Annual_Gen_kWh": 0.0,
                "Annual_Savings_USD": hpwh_kwh_savings * rate,
                "Simple_Payback_yr": simple_payback(hpwh_capex, hpwh_kwh_savings * rate),
                "LCOE_USD_per_kWh": np.nan,
                "CO2e_Reduction_tpy": (hpwh_kwh_savings * scen.grid_emissions_kgco2e_per_kwh) / 1000.0,
                "Practicality": 0.9,
            })

        # --- NEW: Transport options (simple classroom heuristics) ---

        # Shared assumptions
        veh_vmt = 12000.0          # miles / year per vehicle
        mpg_gas = 25.0             # baseline fuel economy
        gas_price = 3.5            # $/gal
        ef_gas = 8.89              # kg CO₂ / gal (gasoline)
        kwh_per_mile_bev = 0.30    # kWh / mile
        elec_rate = scen.elec_rate_usd_per_kwh
        grid_ci = scen.grid_emissions_kgco2e_per_kwh  # kg CO₂ / kWh

        # Baseline gasoline vehicle
        gal_per_year = veh_vmt / mpg_gas
        cost_gas = gal_per_year * gas_price
        co2_gas_kg = gal_per_year * ef_gas

        # EV replacement
        kwh_ev = veh_vmt * kwh_per_mile_bev
        cost_ev = kwh_ev * elec_rate
        co2_ev_kg = kwh_ev * grid_ci

        ev_savings = max(0.0, cost_gas - cost_ev)
        ev_co2_saved_kg = max(0.0, co2_gas_kg - co2_ev_kg)
        ev_capex = 10000.0  # incremental cost of EV vs a similar ICE vehicle

        rows.append({
            "Option": "Transport: replace one gasoline car with a battery EV",
            "Category": "transport",
            "Capex_USD": ev_capex,
            "Annual_Gen_kWh": 0.0,
            "Annual_Savings_USD": ev_savings,
            "Simple_Payback_yr": simple_payback(ev_capex, ev_savings),
            "LCOE_USD_per_kWh": np.nan,
            "CO2e_Reduction_tpy": ev_co2_saved_kg / 1000.0,
            "Practicality": 0.7,
        })

        # Mode shift: 25% of trips moved to transit / walk / bike
        mode_shift_frac = 0.25
        vmt_shifted = veh_vmt * mode_shift_frac
        gal_saved = vmt_shifted / mpg_gas
        # Assume ~20% of gasoline cost comes back as fares / bike upkeep
        cost_saved_mode = gal_saved * gas_price * 0.8
        co2_saved_mode_kg = gal_saved * ef_gas
        mode_capex = 500.0  # bike purchase, transit passes, etc.

        rows.append({
            "Option": "Transport: shift ~25% of trips to transit / walking / biking",
            "Category": "transport",
            "Capex_USD": mode_capex,
            "Annual_Gen_kWh": 0.0,
            "Annual_Savings_USD": cost_saved_mode,
            "Simple_Payback_yr": simple_payback(mode_capex, cost_saved_mode),
            "LCOE_USD_per_kWh": np.nan,
            "CO2e_Reduction_tpy": co2_saved_mode_kg / 1000.0,
            "Practicality": 0.85,
        })

        # --- Build dataframe & MCDA ---
        df = pd.DataFrame(rows)

        def norm_min(x: pd.Series) -> pd.Series:
            x = x.astype(float)
            # smaller is better → min / x
            return x.min() / x.replace(0, np.nan)

        def norm_max(x: pd.Series) -> pd.Series:
            x = x.astype(float)
            return (x - x.min()) / (x.max() - x.min() + 1e-9)

        w = {
            "Simple_Payback_yr": 0.30,
            "Annual_Savings_USD": 0.25,
            "CO2e_Reduction_tpy": 0.25,
            "Practicality": 0.20,
        }

        df["score_payback"] = norm_min(df["Simple_Payback_yr"].fillna(df["Simple_Payback_yr"].max()))
        df["score_savings"] = norm_max(df["Annual_Savings_USD"].fillna(0))
        df["score_co2e"] = norm_max(df["CO2e_Reduction_tpy"].fillna(0))
        df["score_practicality"] = norm_max(df["Practicality"].fillna(0))

        df["MCDA_Score_0to1"] = (
            w["Simple_Payback_yr"] * df["score_payback"]
            + w["Annual_Savings_USD"] * df["score_savings"]
            + w["CO2e_Reduction_tpy"] * df["score_co2e"]
            + w["Practicality"] * df["score_practicality"]
        )

        return df.sort_values("MCDA_Score_0to1", ascending=False)
