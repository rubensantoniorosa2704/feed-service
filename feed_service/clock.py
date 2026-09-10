"""Timestamps em um formato só.

Tudo que entra no journal usa este formato: UTC, precisão de segundo, sufixo Z.
Isso importa porque published_at é comparado como texto (ORDER BY, max()).
Misturar precisão de microssegundo com segundo, ou hora local com UTC, quebra a
ordenação de um jeito silencioso.
"""
from datetime import datetime, timezone

_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime(_FORMAT)


def unix_to_iso(timestamp: int | float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime(_FORMAT)


def iso_to_datetime(value: str) -> datetime:
    return datetime.strptime(value, _FORMAT).replace(tzinfo=timezone.utc)
