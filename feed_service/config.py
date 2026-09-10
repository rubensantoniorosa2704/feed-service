"""Configuração via TOML."""
import tomllib
from pathlib import Path


def load_config(path: str | Path = "config.toml") -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Config not found: {path}\n"
            f"Copy config.example.toml to config.toml and edit it."
        )
    with path.open("rb") as f:
        return tomllib.load(f)


def resolve_profile_interval(profile: dict, defaults: dict) -> int:
    """Intervalo efetivo de um perfil: override do perfil ou o global."""
    return profile.get("interval_minutes") or defaults["interval_minutes"]
