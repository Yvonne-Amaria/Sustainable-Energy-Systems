# conversions.py
from __future__ import annotations

from typing import Dict, List

# Base units (SI + common energy)
UNITS: Dict[str, float] = {
    "J": 1.0,
    "kJ": 1e3,
    "MJ": 1e6,
    "GJ": 1e9,
    "Wh": 3600.0,
    "kWh": 3.6e6,
    "MWh": 3.6e9,
    "GWh": 3.6e12,
    "Btu": 1055.05585262,
    "MMBtu": 1.05505585262e9,
    "cal": 4.184,
    "kcal": 4184.0,
    "hp": 745.699872,  # mechanical horsepower (W)
    "W": 1.0,
    "kW": 1e3,
    "MW": 1e6,
    "GW": 1e9,
    "acre": 4046.8564224,
    "hectare": 10000.0,
}

PREFIXES: Dict[str, float] = {"": 1.0, "k": 1e3, "M": 1e6, "G": 1e9}


def convert_value(value: float, from_unit: str, to_unit: str) -> float:
    if from_unit not in UNITS or to_unit not in UNITS:
        raise ValueError("Unit not supported")
    return value * (UNITS[from_unit] / UNITS[to_unit])


def conversion_quicktips() -> List[str]:
    return [
        "1 J = 0.239 cal",
        "1 kWh = 3.412 MMBtu / 1000",
        "1 MWh = 3.6 GJ",
        "1 hp ≈ 0.746 kW",
        "1 acre = 0.4047 hectare",
    ]
