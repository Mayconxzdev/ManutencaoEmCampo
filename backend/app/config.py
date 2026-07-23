"""Configuração central de caminhos e ambiente do Manutenção em Campo."""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _default_data_root() -> Path:
    """Dados demonstrativos sempre ficam ao lado do projeto público.

    A cópia de portfólio não conhece servidor, NAS, IP de rede ou diretório de
    uma empresa. Quem quiser integrar armazenamento externo deve informar uma
    variável de ambiente explícita em sua própria implantação.
    """
    return PROJECT_ROOT / "data"


DATA_ROOT = Path(os.getenv("MEC_DATA_DIR", _default_data_root())).expanduser().resolve()
DATABASE_DIR = DATA_ROOT / "database"
UPLOADS_DIR = DATA_ROOT / "uploads"
THUMBNAILS_DIR = DATA_ROOT / "thumbnails"
TEMP_DIR = DATA_ROOT / "temp"
BACKUPS_DIR = DATA_ROOT / "backups"
BACKUP_EXTERNAL_DIR = Path(os.getenv("MEC_BACKUP_EXTERNAL_DIR", "")).expanduser() if os.getenv("MEC_BACKUP_EXTERNAL_DIR") else None
# O banco continua local para manter transações atômicas. No modo demonstração,
# os dossiês também ficam locais e são recriáveis pelo script de seed.
NAS_REPOSITORY_DIR = Path(
    os.getenv("MEC_DOSSIER_DIR", DATA_ROOT / "dossies")
).expanduser()
LOGS_DIR = DATA_ROOT / "logs"
REPORTS_DIR = DATA_ROOT / "reports"
CONFIG_DIR = DATA_ROOT / "config"
DATABASE_PATH = Path(os.getenv("MEC_DATABASE_PATH", DATABASE_DIR / "manutencao_em_campo.db")).expanduser().resolve()
APP_TIMEZONE = os.getenv("MEC_TIMEZONE", "America/Sao_Paulo")
APP_VERSION = os.getenv("MEC_APP_VERSION", "1.0.0-demo")


def ensure_data_dirs() -> None:
    for directory in (
        DATA_ROOT,
        DATABASE_DIR,
        UPLOADS_DIR,
        THUMBNAILS_DIR,
        TEMP_DIR,
        BACKUPS_DIR,
        LOGS_DIR,
        REPORTS_DIR,
        CONFIG_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)
