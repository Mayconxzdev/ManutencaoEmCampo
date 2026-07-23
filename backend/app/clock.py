"""Relógio central do domínio, testável e com fuso configurável."""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from .config import APP_TIMEZONE


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_now() -> datetime:
    return datetime.now(ZoneInfo(APP_TIMEZONE))


def local_today() -> date:
    return local_now().date()


def utc_naive_to_local(value: datetime | None) -> datetime | None:
    """Converte o padrão histórico do banco (UTC sem sufixo) para São Paulo.

    O dado antigo não é regravado: isso evita deslocar ou corromper auditorias
    já existentes. A conversão acontece somente quando alguém lê/imprime.
    """
    if value is None:
        return None
    utc_value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return utc_value.astimezone(ZoneInfo(APP_TIMEZONE))


def format_local_datetime(value: datetime | None) -> str:
    local_value = utc_naive_to_local(value)
    return local_value.strftime("%d/%m/%Y às %H:%M") if local_value else "Não informado"
