from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


@dataclass
class CityConfig:
    crs: str = "EPSG:4326"
    target_crs: str = "EPSG:32643"
    default_building_height: float = 10.0


@dataclass
class SolarConfig:
    latitude: float = 28.6139
    longitude: float = 77.2090
    timezone: str = "Asia/Kolkata"
    start_date: str = "2026-01-01"
    end_date: str = "2026-12-31"
    timestep_minutes: int = 60
    panel_efficiency: float = 0.20
    performance_ratio: float = 0.80
    albedo: float = 0.2
    clear_sky_model: str = "hottel"


@dataclass
class ShadowConfig:
    enabled: bool = True
    min_elevation_deg: float = 0.0


@dataclass
class OutputConfig:
    dir: str = "data/output"
    geojson_name: str = "potential.geojson"
    csv_name: str = "potential.csv"
    summary_name: str = "summary.json"


@dataclass
class Config:
    city: CityConfig = field(default_factory=CityConfig)
    solar: SolarConfig = field(default_factory=SolarConfig)
    shadow: ShadowConfig = field(default_factory=ShadowConfig)
    output: OutputConfig = field(default_factory=OutputConfig)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def _apply_env_overrides(cfg: Config) -> None:
    for section in ("city", "solar", "shadow", "output"):
        current = getattr(cfg, section)
        for f in current.__dataclass_fields__.values():
            env_key = f"BIPV_{section.upper()}_{f.name.upper()}"
            if env_key not in os.environ:
                continue
            raw = os.environ[env_key]
            value_type = type(getattr(current, f.name))
            try:
                if value_type is bool:
                    value = raw.lower() in ("1", "true", "yes", "on")
                else:
                    value = value_type(raw)
            except (ValueError, TypeError):
                continue
            setattr(current, f.name, value)


def load_config(path: str | Path | None = None) -> Config:
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    data = _load_yaml(path)
    cfg = Config()

    def update(section: str, dc: Any) -> Any:
        section_data = data.get(section) or {}
        valid_fields = {f.name for f in dc.__dataclass_fields__.values()}
        for key, value in section_data.items():
            if key in valid_fields:
                setattr(dc, key, value)
        return dc

    cfg.city = update("city", cfg.city)
    cfg.solar = update("solar", cfg.solar)
    cfg.shadow = update("shadow", cfg.shadow)
    cfg.output = update("output", cfg.output)
    _apply_env_overrides(cfg)
    return cfg