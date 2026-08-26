from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pvlib

SUN_DATES = {"summer": (6, 21), "equinox": (3, 21), "winter": (12, 21)}
YEAR = 2026
ALBEDO = 0.2
LINK_TURBIDITY = 3.0


def tz_for(lon: float) -> timezone:
    return timezone(timedelta(hours=round(lon / 15.0)))


def timestamp(season: str, hour: float, lon: float) -> datetime:
    month, day = SUN_DATES.get(season, SUN_DATES["equinox"])
    hour = max(0.0, min(24.0, float(hour)))
    hh = int(hour)
    mm = int(round((hour - hh) * 60))
    if mm >= 60:
        hh += 1
        mm -= 60
    return datetime(YEAR, month, day, hh, mm, tzinfo=tz_for(lon))


def _fin(x: float) -> float:
    v = float(x)
    return 0.0 if v != v else v


def _solpos_clearsky(times, lat, lon):
    solpos = pvlib.solarposition.get_solarposition(times, lat, lon)
    apparent_zenith = solpos["apparent_zenith"]
    airmass = pvlib.atmosphere.get_relative_airmass(apparent_zenith)
    pressure = pvlib.atmosphere.alt2pres(0.0)
    airmass_absolute = pvlib.atmosphere.get_absolute_airmass(airmass, pressure)
    cs = pvlib.clearsky.ineichen(apparent_zenith, airmass_absolute, LINK_TURBIDITY, altitude=0)
    return solpos, cs


def position_and_clearsky(lat: float, lon: float, season: str, hour: float) -> dict:
    times = pd.DatetimeIndex([timestamp(season, hour, lon)])
    solpos, cs = _solpos_clearsky(times, lat, lon)
    return {
        "elevation": float(solpos["elevation"].iloc[0]),
        "azimuth": _fin(solpos["azimuth"].iloc[0]),
        "zenith": _fin(solpos["zenith"].iloc[0]),
        "ghi": _fin(cs["ghi"].iloc[0]),
        "dni": _fin(cs["dni"].iloc[0]),
        "dhi": _fin(cs["dhi"].iloc[0]),
    }


def poa(surface_tilt, surface_azimuth, zenith, azimuth, ghi, dni, dhi) -> dict:
    return pvlib.irradiance.get_total_irradiance(
        surface_tilt,
        surface_azimuth,
        zenith,
        azimuth,
        dni=dni,
        ghi=ghi,
        dhi=dhi,
        albedo=ALBEDO,
    )


def annual_context(lat: float, lon: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    tz = tz_for(lon)
    times = pd.date_range(
        datetime(YEAR, 1, 1, tzinfo=tz),
        datetime(YEAR, 12, 31, 23, tzinfo=tz),
        freq="h",
    )
    return _solpos_clearsky(times, lat, lon)


def annual_poa(ctx: tuple[pd.DataFrame, pd.DataFrame], tilt: float, az: float) -> float:
    solpos, cs = ctx
    poa = pvlib.irradiance.get_total_irradiance(
        tilt,
        az,
        solpos["zenith"],
        solpos["azimuth"],
        dni=cs["dni"],
        ghi=cs["ghi"],
        dhi=cs["dhi"],
        albedo=ALBEDO,
    )
    return float(poa["poa_global"].fillna(0.0).sum() / 1000.0)
