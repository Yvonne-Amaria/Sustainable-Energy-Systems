# guides.py
from __future__ import annotations

from typing import List, Dict

# Short, practical blurbs for the Household & Policy pages

def household_actions() -> List[Dict[str, str]]:
    return [
        {"title": "LEDs + Smart Thermostat", "summary": "Fast payback (1–3y), ~5–15% electric & heating savings."},
        {"title": "Air Sealing & Attic Insulation", "summary": "Cut heating/cooling load 10–25%; quieter, more comfortable."},
        {"title": "Heat Pump Water Heater", "summary": "~1,200 kWh/yr savings vs resistive; dehumidifies basements."},
        {"title": "Induction Cooktop", "summary": "Efficient, safer, great control; reduce indoor NO₂."},
        {"title": "Heat Pump HVAC (when replacing)", "summary": "Right-sized inverter HPs slash bills & emissions, esp. with good envelope."},
        {"title": "Rooftop Solar (if viable)", "summary": "Offset daytime loads; pair with TOU-aware scheduling."},
        {"title": "EV or PHEV Transition", "summary": "Low fuel cost per mile; charge off-peak; MAINT: tires & brakes."},
    ]


def policy_advocacy() -> List[Dict[str, str]]:
    return [
        {"name": "Performance-based efficiency programs", "why": "Pays for verifiable savings, not just measures."},
        {"name": "Modernized interconnection & virtual net metering", "why": "Unlocks rooftops and community solar participation."},
        {"name": "Time-of-use & smart rate pilots", "why": "Aligns customer behavior with grid needs & reduces peaks."},
        {"name": "Building performance standards", "why": "Phased targets encourage upgrades with flexibility."},
        {"name": "EV-ready codes & curbside charging", "why": "Future-proofs buildings and supports renters."},
    ]


def incentive_blurbs() -> List[Dict[str, str]]:
    return [
        {"name": "Residential Clean Energy Credit (30% ITC)", "details": "Solar PV, batteries, geothermal; includes labor; no cap through 2032."},
        {"name": "Energy Efficient Home Improvement Credit (25C)", "details": "Heat pumps, HPWH, panels, air sealing; annual caps apply."},
        {"name": "New/Used EV Credits (30D/25E)", "details": "Income/MSRP caps; dealer transfer available for point-of-sale."},
        {"name": "State & Utility Rebates", "details": "Add-on rebates for HPs, weatherization, EVSE; check local portals."},
    ]
