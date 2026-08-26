from __future__ import annotations

PANEL_EFFICIENCY = 0.20
USABLE_FRACTION = 0.75
PERFORMANCE_RATIO = 0.80
PEAK_IRRADIANCE_KW = 1.0
REF_ANNUAL_IRRADIATION = 2000.0


def bipv_score(annual_irradiation_kwh_m2: float) -> float:
    return min(100.0, max(0.0, (annual_irradiation_kwh_m2 / REF_ANNUAL_IRRADIATION) * 100.0))


def bipv_potential(area_m2: float, annual_irradiation_kwh_m2: float) -> dict:
    usable_area = area_m2 * USABLE_FRACTION
    kwp = usable_area * PANEL_EFFICIENCY * PEAK_IRRADIANCE_KW
    kwh = annual_irradiation_kwh_m2 * usable_area * PANEL_EFFICIENCY * PERFORMANCE_RATIO
    return {
        "usable_area_m2": usable_area,
        "pv_capacity_kwp": kwp,
        "annual_energy_kwh": kwh,
    }


def assumptions() -> dict:
    return {
        "panel_efficiency": PANEL_EFFICIENCY,
        "usable_fraction": USABLE_FRACTION,
        "performance_ratio": PERFORMANCE_RATIO,
    }
