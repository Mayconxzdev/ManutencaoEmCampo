"""Checks kept intentionally small and reproducible for the public demo."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent


def test_demo_seed_creates_only_synthetic_assets() -> None:
    """A fresh clone can create a local, non-corporate demonstration base."""
    data_dir = PROJECT_ROOT / "data"
    environment = os.environ | {"MEC_DATA_DIR": str(data_dir)}

    completed = subprocess.run(
        [sys.executable, "scripts/seed_demo.py", "--reset"],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    database = data_dir / "database" / "manutencao_em_campo.db"
    assert database.is_file()

    with sqlite3.connect(database) as connection:
        assets = connection.execute("SELECT patrimonio, description, notes FROM assets ORDER BY patrimonio").fetchall()
        people = connection.execute("SELECT name FROM operators ORDER BY name").fetchall()

    assert [asset[0] for asset in assets] == ["MEC-101", "MEC-102", "MEC-103", "MEC-104"]
    assert all("Dados fictícios" in asset[2] for asset in assets)
    assert {person[0] for person in people} == {"Camila Duarte", "Diego Farias", "Joana Lima", "Rafael Moreira"}


def test_reset_refuses_a_database_outside_public_demo_roots(tmp_path: Path) -> None:
    """The destructive flag cannot be redirected to an arbitrary local path."""
    outside_root = tmp_path / "outside"
    environment = os.environ | {"MEC_DATA_DIR": str(outside_root)}

    completed = subprocess.run(
        [sys.executable, "scripts/seed_demo.py", "--reset"],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "Recusa de segurança" in completed.stderr
