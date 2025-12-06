# resources.py
from __future__ import annotations

from typing import Dict

# Safe, legit starting points for quotes/incentives. Replace with locale-aware links later.

def quote_links(state: str) -> Dict[str, str]:
    base = {
        "EnergySage Solar Quotes": "https://www.energysage.com/solar/",
        "NABCEP – Consumer Education": "https://www.nabcep.org/consumers/",
        "NABCEP – PV Consumer Guide": "https://www.nabcep.org/resource/pv-consumer-guide/",
        "EPA eGRID (emissions factors)": "https://www.epa.gov/egrid",
        "NREL PVWatts Calculator": "https://pvwatts.nrel.gov/",
        "DSIRE Incentives & Policies": "https://www.dsireusa.org/",
        "OpenEI Utility Rates": "https://openei.org/apps/USURDB/",
    }
    # Optionally adjust by state (simple examples)
    if state.upper() == "MI":
        base.update({
            "Michigan Public Service Commission (energy & rates)": "https://www.michigan.gov/mpsc",
        })
    return base


