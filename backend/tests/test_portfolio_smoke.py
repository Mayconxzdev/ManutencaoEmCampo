"""Checks kept intentionally small and reproducible for the public demo."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


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
        completed_order = connection.execute(
            "SELECT execution_status, status, final_pdf_path, final_pdf_sha256, performed_by_name "
            "FROM maintenance_orders WHERE friendly_number = 1004"
        ).fetchone()
        evidence_count = connection.execute(
            "SELECT COUNT(*) FROM maintenance_evidences WHERE order_id = "
            "(SELECT id FROM maintenance_orders WHERE friendly_number = 1004)"
        ).fetchone()[0]

    assert [asset[0] for asset in assets] == ["MEC-101", "MEC-102", "MEC-103", "MEC-104"]
    assert all("Dados fictícios" in asset[2] for asset in assets)
    assert {person[0] for person in people} == {"Camila Duarte", "Diego Farias", "Joana Lima", "Rafael Moreira"}
    assert completed_order is not None
    assert completed_order[0:2] == ("completed", "demo_completed")
    assert completed_order[3]
    assert completed_order[4] == "Diego Farias"
    assert Path(completed_order[2]).is_file()
    assert evidence_count == 1


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


def test_health_endpoint_does_not_disclose_local_database_path() -> None:
    """Health checks confirm readiness without revealing a workstation path."""
    from app.main import health_check

    response = asyncio.run(health_check())

    assert response["status"] == "ok"
    assert response["storage"] == "local-demo"
    assert "database" not in response
