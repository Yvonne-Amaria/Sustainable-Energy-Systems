# nrel_client.py
from __future__ import annotations

import os
import requests
import streamlit as st


class NRELClient:
    """
    Minimal helper for calling the NREL PVWatts API.

    Docs: https://developer.nrel.gov/docs/solar/pvwatts/v8/
    """

    BASE_URL = "https://developer.nrel.gov/api/pvwatts/v8.json"

    def __init__(self, api_key: str | None = None):
        if api_key is None:
            # Try from secrets, then env var
            api_key = st.secrets.get("NREL_API_KEY", None) or os.getenv("NREL_API_KEY")
        self.api_key = api_key
        self.last_error: str | None = None

    def available(self) -> bool:
        return bool(self.api_key)

    def pvwatts_ac_annual(
        self,
        lat: float,
        lon: float,
        system_capacity_kw: float,
        tilt_deg: float,
        azimuth_deg: float = 180.0,
        array_type: int = 1,
        module_type: int = 1,
        losses_pct: float = 14.0,
    ) -> float | None:
        """
        Calls PVWatts and returns AC annual energy (kWh) if successful, else None.

        - lat, lon: site location
        - system_capacity_kw: DC system size in kW
        - tilt_deg: tilt angle in degrees
        - azimuth_deg: azimuth in degrees (180 = south)
        - array_type: 0 fixed open rack, 1 fixed roof, 2 1-axis tracking, etc.
        - module_type: 0 standard, 1 premium, 2 thin film
        - losses_pct: total system losses (%)
        """
        self.last_error = None

        if not self.available():
            self.last_error = "No NREL_API_KEY found in secrets or environment."
            return None

        params = {
            "format": "json",
            "api_key": self.api_key,
            "lat": lat,
            "lon": lon,
            "system_capacity": system_capacity_kw,
            "azimuth": azimuth_deg,
            "tilt": tilt_deg,
            "array_type": array_type,
            "module_type": module_type,
            "losses": losses_pct,
            # "timeframe": "monthly",   # optional; default is monthly so we can omit it
            # "dataset": "nsrdb",       # default dataset; you can uncomment if you want to force it
        }


        try:
            resp = requests.get(self.BASE_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            # If the API returns an error message, capture it
            errors = data.get("errors") or data.get("error")
            if errors:
                # errors can be a list or string
                if isinstance(errors, list):
                    self.last_error = "; ".join(errors)
                else:
                    self.last_error = str(errors)
                return None

            outputs = data.get("outputs", {})
            ac_annual = outputs.get("ac_annual")
            if ac_annual is None:
                self.last_error = "PVWatts response missing 'outputs.ac_annual'."
                return None

            return float(ac_annual)

        except Exception as e:
            self.last_error = f"Exception calling PVWatts: {e}"
            return None

    def pvwatts_full(
        self,
        lat: float,
        lon: float,
        system_capacity_kw: float,
        tilt_deg: float,
        azimuth_deg: float = 180.0,
        array_type: int = 1,
        module_type: int = 1,
        losses_pct: float = 14.0,
    ) -> dict | None:
        """
        Calls PVWatts and returns the full 'outputs' dict if successful, else None.

        This is used for a PVWatts-like results table (monthly AC/DC, solar radiation, etc.).
        """
        self.last_error = None

        if not self.available():
            self.last_error = "No NREL_API_KEY found in secrets or environment."
            return None

        params = {
            "format": "json",
            "api_key": self.api_key,
            "lat": lat,
            "lon": lon,
            "system_capacity": system_capacity_kw,
            "azimuth": azimuth_deg,
            "tilt": tilt_deg,
            "array_type": array_type,
            "module_type": module_type,
            "losses": losses_pct,
        }

        try:
            resp = requests.get(self.BASE_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            errors = data.get("errors") or data.get("error")
            if errors:
                if isinstance(errors, list):
                    self.last_error = "; ".join(errors)
                else:
                    self.last_error = str(errors)
                return None

            outputs = data.get("outputs")
            if not outputs:
                self.last_error = "PVWatts response missing 'outputs'."
                return None

            return outputs

        except Exception as e:
            self.last_error = f"Exception calling PVWatts: {e}"
            return None
