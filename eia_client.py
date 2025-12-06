# eia_client.py
from __future__ import annotations

import logging
import os
from typing import Optional, Dict, Any, List

import requests
import pandas as pd
import streamlit as st

log = logging.getLogger(__name__)


class EIA:
    """
    Minimal EIA API client for this app.

    v2 endpoints actually used:
      • electricity/retail-sales → state electricity retail price
      • total-energy             → MER-style total energy series

    Public attributes:
      • api_key
      • last_error
      • last_url

    Public helpers:
      • available()
      • fetch_retail_price(...)
      • fetch_state_price(...)          # alias
      • fetch_series(...)               # wrapper used by A1–A9 calc page
      • fetch_total_energy_series(...)  # MER helper on EIA page
    """

    base_v2: str = "https://api.eia.gov/v2"

    def __init__(self, api_key: Optional[str] = None):
        # Prefer explicit key, then Streamlit secrets, then env var
        if api_key is None:
            try:
                api_key = st.secrets.get("EIA_API_KEY", None)
            except Exception:
                api_key = None
            if api_key is None:
                api_key = os.getenv("EIA_API_KEY")

        self.api_key: Optional[str] = api_key
        self.last_error: Optional[str] = None
        self.last_url: Optional[str] = None

    # ------------------------------------------------------------------
    # Basic helpers
    # ------------------------------------------------------------------
    def available(self) -> bool:
        """Return True if we have an API key configured."""
        return bool(self.api_key)

    @staticmethod
    def _normalize_v2_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        EIA v2 responses look like:
            { "response": { "total": ..., "data": [...] }, "request": {...}, ... }

        Older examples / some docs show { "total": ..., "data": [...] } at top level.
        This helper normalizes to the inner object that actually has 'total' and 'data'.
        """
        if isinstance(payload, dict) and "response" in payload and isinstance(
            payload["response"], dict
        ):
            return payload["response"]
        return payload

    def _get_v2(self, path: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Internal helper to call a v2 endpoint.

        path: "electricity/retail-sales/data" (no leading slash)
        params: EIA v2 request parameters (GET query)
        """
        self.last_error = None
        self.last_url = None

        if not self.available():
            self.last_error = "No EIA_API_KEY configured (in secrets.toml or environment)."
            return None

        url = f"{self.base_v2}/{path.lstrip('/')}"
        params = dict(params or {})
        params["api_key"] = self.api_key
        self.last_url = url

        try:
            resp = requests.get(url, params=params, timeout=20)

            # Handle 403 explicitly for nicer UX
            if resp.status_code == 403:
                self.last_error = (
                    "EIA returned 403 Forbidden. This usually means your API key is "
                    "invalid, not activated for API v2, or has been revoked. "
                    "Copy the URL below into a browser; if it still fails, log in at "
                    "eia.gov/opendata and check the key status."
                )
                log.error("EIA 403 error. URL: %s", resp.url)
                return None

            resp.raise_for_status()
            raw = resp.json()
        except Exception as e:
            self.last_error = f"Exception calling EIA v2: {e}"
            log.error("EIA v2 error: %s\nURL: %s", e, url)
            return None

        data = self._normalize_v2_payload(raw)

        # EIA v2 often returns total=0 with 200 when filters don't match
        try:
            total = int(data.get("total", 0))
        except Exception:
            total = 0

        if total == 0 or not data.get("data"):
            self.last_error = "No records returned from EIA for this selection."
            return None

        return data

    # ------------------------------------------------------------------
    # High-level helpers actually used in the app
    # ------------------------------------------------------------------
    def fetch_retail_price(
        self,
        year: int,
        state: str = "MI",
        sector: str = "total",
    ) -> Optional[pd.DataFrame]:
        """
        Electricity retail price (cents/kWh) from v2/electricity/retail-sales.

        Returns:
            DataFrame with:
              • price_cents_per_kwh
              • price_usd_per_kwh
              • all original columns from EIA
            or None if no rows or an error.
        """
        # Map friendly sector names → EIA sectorid codes used by this dataset
        sector_map = {
            "total": "ALL",
            "all": "ALL",
            "ALL": "ALL",
            "residential": "RES",
            "RES": "RES",
            "commercial": "COM",
            "COM": "COM",
            "industrial": "IND",
            "IND": "IND",
            "transportation": "TRA",
            "TRA": "TRA",
            "other": "OTH",
            "OTH": "OTH",
        }
        sectorid = sector_map.get(sector, sector)

        params = {
            "frequency": "annual",
            # Match EIA examples exactly: data[0]=price
            "data[0]": "price",
            # Match their facet naming: sectorid + stateid
            "facets[stateid][]": state.upper(),
            "facets[sectorid][]": sectorid,
            "start": str(year),
            "end": str(year),
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
        }

        raw = self._get_v2("electricity/retail-sales/data", params)
        if raw is None:
            return None

        rows = raw.get("data", [])
        df = pd.DataFrame(rows)

        # Convert price string → floats and add USD/kWh
        if "price" in df.columns:
            df["price_cents_per_kwh"] = df["price"].astype(float)
            df["price_usd_per_kwh"] = df["price_cents_per_kwh"] / 100.0

        # Keep the actual request URL around for debugging, if provided by EIA
        # Some v2 responses echo requestUrl at top-level, some don't.
        df.attrs["request_url"] = raw.get("requestUrl") or self.last_url
        return df

    # def fetch_total_energy_series(
    #     self,
    #     msn: str = "TETGRUS",
    #     start_year: int = 2000,
    #     end_year: int = 2024,
    # ) -> Optional[pd.DataFrame]:
    #     """
    #     Helper for MER-style total energy series from v2/total-energy.

    #     Example MSN:
    #       • TETGRUS – Total energy consumption, U.S. (quadrillion Btu)

    #     Returns:
    #         DataFrame with 'period' and 'value' columns (plus whatever else EIA sends),
    #         or None if nothing is returned.
    #     """
    #     params = {
    #         "frequency": "annual",
    #         "data[0]": "value",
    #         "facets[msn][]": msn,
    #         "start": str(start_year),
    #         "end": str(end_year),
    #         "sort[0][column]": "period",
    #         "sort[0][direction]": "asc",
    #         "offset": "0",
    #         "length": "5000",
    #     }

    #     raw = self._get_v2("total-energy/data", params)
    #     if raw is None:
    #         return None
        
    #     rows = raw.get("data", [])
    #     df = pd.DataFrame(rows)
    #     if "value" in df.columns:
    #         df["value"] = pd.to_numeric(df["value"], errors="coerce")

    #     # rows = raw.get("data", [])
    #     # df = pd.DataFrame(rows)
    #     # if "value" in df.columns:
    #     #     df["value"] = df["value"].astype(float)
    #     df.attrs["request_url"] = raw.get("requestUrl") or self.last_url
    #     return df

    # ------------------------------------------------------------------
    # Backwards-compatible wrappers
    # ------------------------------------------------------------------
    def fetch_series(
        self,
        year: int,
        state: str,
        fuel: str,
        series: str,
        sector: str = "total",
        frequency: str = "annual",
    ) -> Optional[pd.DataFrame]:
        """
        Backwards-compatible wrapper used by the Energy Calculations page.

        Currently implemented:
          • fuel='electricity', series='price'
            → state retail price via fetch_retail_price(...)

        All other combos return None but will not crash.
        """
        fuel = fuel.lower()
        series = series.lower()

        if fuel == "electricity" and series == "price":
            # ignore 'frequency' for now; dataset is annual
            return self.fetch_retail_price(year=year, state=state, sector=sector)

        self.last_error = (
            "fetch_series is only implemented for fuel='electricity', series='price'. "
            f"Requested fuel='{fuel}', series='{series}', sector='{sector}', frequency='{frequency}'."
        )
        log.warning(self.last_error)
        return None

    def fetch_state_price(
        self,
        year: int,
        state: str = "MI",
        sector: str = "total",
    ) -> Optional[pd.DataFrame]:
        """Thin alias kept for backwards compatibility."""
        return self.fetch_retail_price(year=year, state=state, sector=sector)

    def fetch_total_energy_series(
        self,
        msn: str = "TETGRUS",
        start_year: int = 2000,
        end_year: int = 2024,
        frequency: str = "annual",
        start_month: int = 1,
        end_month: int = 12,
    ) -> Optional[pd.DataFrame]:
        """
        Helper for MER-style total energy series from v2/total-energy.

        Args
        ----
        msn : str
            EIA MSN code (e.g. 'TETGRUS', 'TETPRUS', etc.).
        start_year, end_year : int
            Year bounds for the query.
        frequency : {'annual', 'monthly'}
            Whether to pull annual or monthly data.
        start_month, end_month : int
            Only used when frequency='monthly'. Inclusive bounds (1–12).

        Returns
        -------
        DataFrame with at least ['period', 'value'] or None.
        - For annual: period is 'YYYY'
        - For monthly: period is 'YYYYMM'
        """
        freq = (frequency or "annual").lower()
        if freq not in ("annual", "monthly"):
            self.last_error = f"Unsupported frequency '{frequency}' (use 'annual' or 'monthly')."
            return None

        # Build start/end codes
        if freq == "annual":
            start_code = str(start_year)
            end_code = str(end_year)
        else:
            # Monthly: allow cross-year windows, e.g. 2023-10 → 2025-03
            start_code = f"{int(start_year):04d}{int(start_month):02d}"
            end_code = f"{int(end_year):04d}{int(end_month):02d}"

        params = {
            "frequency": freq,
            "data[0]": "value",
            "facets[msn][]": msn,
            "start": start_code,
            "end": end_code,
            "sort[0][column]": "period",
            "sort[0][direction]": "asc",
            "offset": "0",
            "length": "5000",
        }

        raw = self._get_v2("total-energy/data", params)
        if raw is None:
            return None

        rows = raw.get("data", [])
        if not rows:
            self.last_error = "No records returned from EIA for this MSN / time window."
            return None

        df = pd.DataFrame(rows)

        # Safely convert 'value' to numeric (handles 'Not Available', etc.)
        if "value" in df.columns:
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            df = df.dropna(subset=["value"])

        # Keep period as string so 'YYYYMM' works cleanly
        if "period" in df.columns:
            df["period"] = df["period"].astype(str)

        df.attrs["request_url"] = raw.get("requestUrl") or self.last_url
        return df

    def fetch_total_energy_multi(
        self,
        msns: list[str],
        start_year: int = 2000,
        end_year: int = 2024,
        frequency: str = "annual",
        start_month: int = 1,
        end_month: int = 12,
    ) -> Optional[pd.DataFrame]:
        """
        Fetch multiple MER MSNs at once (annual or monthly) and stack them.

        Returns
        -------
        Long DataFrame with columns:
          - 'msn'
          - 'period'
          - 'value'
        or None if nothing comes back.
        """
        if not msns:
            self.last_error = "No MSN codes provided."
            return None

        frames: list[pd.DataFrame] = []
        for msn in msns:
            df = self.fetch_total_energy_series(
                msn=msn,
                start_year=start_year,
                end_year=end_year,
                frequency=frequency,
                start_month=start_month,
                end_month=end_month,
            )
            if df is None or df.empty:
                # Skip MSNs that genuinely have no data; don't kill the whole request
                continue

            df = df.copy()
            df["msn"] = msn
            frames.append(df[["msn", "period", "value"]])

        if not frames:
            self.last_error = "No data returned from EIA for any of the requested MSNs."
            return None

        df_long = pd.concat(frames, ignore_index=True)

        # Ensure dtypes are friendly
        df_long["period"] = df_long["period"].astype(str)
        df_long["value"] = pd.to_numeric(df_long["value"], errors="coerce")
        df_long = df_long.dropna(subset=["value"])

        return df_long


    # def fetch_total_energy_series(
    #     self,
    #     msn: str = "TETGRUS",
    #     start_year: int = 2000,
    #     end_year: int = 2024,
    # ) -> Optional[pd.DataFrame]:
    #     """
    #     MER / total-energy series from v2/total-energy.

    #     msn examples:
    #       - TETGRUS: Total U.S. primary energy consumption (quad Btu)
    #       - TETPRUS: Total U.S. primary energy production (quad Btu)
    #       - TETCHUS: Energy per capita (million Btu per person)
    #       - TEGDSUS: Energy/GDP (thousand Btu per dollar)
    #     """
    #     params = {
    #         "frequency": "annual",
    #         "data[0]": "value",
    #         "facets[msn][]": msn,
    #         "start": str(start_year),
    #         "end": str(end_year),
    #         "sort[0][column]": "period",
    #         "sort[0][direction]": "asc",
    #         "offset": "0",
    #         "length": "5000",
    #     }

    #     raw = self._get_v2("total-energy/data", params)
    #     if raw is None:
    #         return None

    #     rows = raw.get("data", [])
    #     if not rows:
    #         self.last_error = "No MER records returned for this MSN / year range."
    #         return None

    #     df = pd.DataFrame(rows)

    #     if "value" in df.columns:
    #         # Handle "Not Available" and similar by coercing to NaN
    #         df["value"] = pd.to_numeric(df["value"], errors="coerce")
    #         df = df.dropna(subset=["value"])

    #     df.attrs["request_url"] = raw.get("requestUrl") or self.last_url
    #     return df

    # def fetch_total_energy_multi(
    #     self,
    #     msns: list[str],
    #     start_year: int,
    #     end_year: int,
    # ) -> Optional[pd.DataFrame]:
    #     """
    #     Fetch multiple MER / total-energy series at once.

    #     Parameters
    #     ----------
    #     msns : list of MSN codes (e.g. ['TETGRUS','TETPRUS',...])
    #     start_year, end_year : ints

    #     Returns
    #     -------
    #     DataFrame with columns ['msn', 'period', 'value'] (long form),
    #     or None if nothing could be fetched.

    #     Any 'Not Available' values are coerced to NaN and dropped.
    #     """
    #     if not msns:
    #         self.last_error = "fetch_total_energy_multi: no MSN codes provided."
    #         return None

    #     frames = []

    #     for msn in msns:
    #         params = {
    #             "frequency": "annual",
    #             "data[0]": "value",
    #             "facets[msn][]": msn,
    #             "start": str(start_year),
    #             "end": str(end_year),
    #             "sort[0][column]": "period",
    #             "sort[0][direction]": "asc",
    #             "offset": "0",
    #             "length": "5000",
    #         }

    #         raw = self._get_v2("total-energy/data", params)
    #         if raw is None or not raw.get("data"):
    #             # Skip this MSN but do not kill the whole call
    #             continue

    #         df = pd.DataFrame(raw["data"])
    #         if "value" in df.columns:
    #             df["value"] = pd.to_numeric(df["value"], errors="coerce")
    #             df = df.dropna(subset=["value"])

    #         if df.empty:
    #             continue

    #         df["msn"] = msn
    #         frames.append(df[["msn", "period", "value"]])

    #     if not frames:
    #         self.last_error = "fetch_total_energy_multi: no data returned for any MSN."
    #         return None

    #     df_long = pd.concat(frames, ignore_index=True)
    #     return df_long

    # -------------------------------
    # Fuel presets (MER-style, U.S.)
    # -------------------------------
    def fuel_presets(self):
        """
        Human-friendly mapping from fuel names to MER MSN codes and descriptions.
        Units are typically quadrillion Btu/year for 'total-energy' dataset.
        """
        return {
            "Total energy (all fuels)": {
                "msn": "TETGRUS",
                "description": "Total primary energy consumption, all fuels, U.S.",
                "units": "quad Btu/yr",
            },
            "Petroleum consumption": {
                "msn": "TETPRUS",
                "description": "Total petroleum consumption, U.S.",
                "units": "quad Btu/yr",
            },
            "Coal consumption": {
                "msn": "TETCOUS",
                "description": "Total coal consumption, U.S.",
                "units": "quad Btu/yr",
            },
            "Natural gas consumption": {
                "msn": "TETNGUS",
                "description": "Total natural gas consumption, U.S.",
                "units": "quad Btu/yr",
            },
            "Electricity net generation": {
                "msn": "TETENUS",
                "description": "Total electricity net generation, U.S.",
                "units": "quad Btu/yr (primary-equivalent or as defined in MER)",
            },
        }
    
    def fetch_fuel_timeseries(
        self,
        fuel_label: str,
        start_year: int = 2000,
        end_year: int = 2024,
    ) -> Optional[pd.DataFrame]:
        """
        Convenience wrapper: user picks a human-readable fuel label,
        we look up its MSN and call fetch_total_energy_series.
        """
        presets = self.fuel_presets()
        if fuel_label not in presets:
            self.last_error = f"Unknown fuel label: {fuel_label}"
            return None

        msn = presets[fuel_label]["msn"]
        return self.fetch_total_energy_series(
            msn=msn,
            start_year=start_year,
            end_year=end_year,
        )
