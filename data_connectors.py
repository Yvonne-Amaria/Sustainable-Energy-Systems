# data_connectors.py
from __future__ import annotations

from typing import Dict, Tuple
from models import Site

class DataConnectors:
    """External data access. Swap stubs with real APIs (store keys in st.secrets)."""

    @staticmethod
    def geocode(zipcode: str) -> Tuple[float, float]:
        # TODO: Replace with FCC/Nominatim/Google Maps.
        z = str(zipcode)
        if z == "48202":
            return (42.380, -83.078)
        return (42.3314, -83.0458)

    @staticmethod
    def utility_rate(site: Site) -> float:
        # TODO: OpenEI Utility Rates or EIA average retail.
        return 0.18 if site.state == "MI" else 0.16

    @staticmethod
    def grid_emissions(site: Site) -> float:
        # TODO: EPA eGRID lookup by ZIP (kgCO2e/kWh)
        return 0.38

    @staticmethod
    def solar_resource(lat: float, lon: float) -> Dict[str, float]:
        # TODO: NREL NSRDB / PVWatts climate inputs
        return {"GHI_kWhm2_day": 4.2, "Tamb_C": 12.0}
