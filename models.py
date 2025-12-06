# models.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

@dataclass
class Site:
    country: str = "USA"
    state: Optional[str] = None
    county: Optional[str] = None
    city: Optional[str] = None
    zipcode: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    building_type: str = "residential"
    floor_area_m2: Optional[float] = None
    annual_electricity_kwh: Optional[float] = None
    annual_gas_therms: Optional[float] = None

@dataclass
class ScenarioInput:
    site: Site
    elec_rate_usd_per_kwh: float
    gas_rate_usd_per_therm: float
    demand_charge_usd_per_kw: float = 0.0
    discount_rate: float = 0.07
    analysis_years: int = 25
    grid_emissions_kgco2e_per_kwh: float = 0.38
