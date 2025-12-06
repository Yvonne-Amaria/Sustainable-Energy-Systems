# tools.py
from __future__ import annotations

from typing import List, Tuple

# === PV & General ===

def pv_area_for_avg_power(p_avg_kw: float, eta: float, G_year_kwh_m2_day: float) -> float:
    return (p_avg_kw * 24.0) / (eta * G_year_kwh_m2_day)

def capacity_factor(monthly_kwh: float, ac_kw: float, days_in_month: int) -> float:
    return monthly_kwh / (ac_kw * 24.0 * days_in_month)

def panel_efficiency(p_w: float, area_m2: float, insolation_w_m2: float = 1000.0) -> float:
    return p_w / (insolation_w_m2 * area_m2)

# === Fuels ===

def carbon_intensity_from_fc_hhv(fc_mass_frac: float, HHV_MJ_per_kg: float) -> float:
    return (fc_mass_frac * (44.0 / 12.0)) / HHV_MJ_per_kg

def carbon_intensity_from_formula(nC: int, nH: int, HHV_MJ_per_kg: float) -> float:
    mC = nC * 12.0
    mH = nH * 1.0
    fc = mC / (mC + mH)
    return carbon_intensity_from_fc_hhv(fc, HHV_MJ_per_kg)

# === Wind ===

def wind_region_potential(area_km2: float, mw_per_km2: float, cf: float) -> float:
    capacity_mw = area_km2 * mw_per_km2
    annual_mwh = capacity_mw * 8760.0 * cf
    return annual_mwh / 1e6  # TWh

# === Biomass ===

def biomass_poplar_land_for_power(
    net_eff: float, cf: float, plant_mw: float, HHV_kJ_per_kg: float, yield_Mg_per_ha_yr: float
) -> float:
    annual_elec_MJ = plant_mw * 1e6 * 8760.0 * cf * 3.6
    biomass_MJ_needed = annual_elec_MJ / net_eff
    kg_needed = biomass_MJ_needed * 1e6 / HHV_kJ_per_kg
    ha = (kg_needed / 1000.0) / yield_Mg_per_ha_yr
    return ha

def trucks_per_day(kg_per_year: float, kg_per_truck: float) -> float:
    return kg_per_year / kg_per_truck / 365.0

# === EV / Tariffs ===

def ev_tou_cost(
    kwh_needed: float,
    start_hour: int,
    charger_kw: float,
    tariff_blocks: List[Tuple[Tuple[int, int], float]],
) -> float:
    hours_needed = kwh_needed / max(charger_kw, 1e-9)
    cost = 0.0
    h = start_hour
    remaining = hours_needed
    step_h = 0.25
    while remaining > 1e-9:
        matched = False
        for (span, price) in tariff_blocks:
            s, e = span
            if (h % 24) >= s and (h % 24) < e:
                use = min(step_h, remaining)
                cost += price * charger_kw * use
                remaining -= use
                h += step_h
                matched = True
                break
        if not matched:
            h += step_h
    return cost
