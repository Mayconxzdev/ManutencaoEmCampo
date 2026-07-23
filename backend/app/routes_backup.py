from __future__ import annotations

import os
import sys
import importlib.util
from datetime import datetime
from types import ModuleType

from fastapi import APIRouter, HTTPException, Request

from app.config import BACKUPS_DIR, PROJECT_ROOT
from app.database import engine


router = APIRouter()


def _ensure_project_root_on_path() -> None:
    root = str(PROJECT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def _load_backup_restore_module() -> ModuleType:
    """Load backup helpers by file path to avoid ambiguous Windows namespace imports."""
    module_path = PROJECT_ROOT / "scripts" / "backup_restore.py"
    if not module_path.exists():
        raise RuntimeError(f"Script de backup não encontrado: {module_path}")
    spec = importlib.util.spec_from_file_location("mec_backup_restore", module_path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Não foi possível carregar o script de backup: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@router.post("/backup/create")
async def create_backup_endpoint():
    try:
        _ensure_project_root_on_path()
        backup_restore = _load_backup_restore_module()

        backup_path = backup_restore.do_backup()
        if backup_path:
            return {
                "status": "success",
                "message": "Backup criado com sucesso.",
                "filename": os.path.basename(str(backup_path)),
            }
        raise HTTPException(status_code=500, detail="Falha ao criar o backup. Verifique os logs.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/backup/list")
async def list_backups_endpoint():
    try:
        backup_files = sorted(
            BACKUPS_DIR.glob("backup_mec_*.zip"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return [
            {
                "filename": path.name,
                "size_bytes": path.stat().st_size,
                "created_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
            }
            for path in backup_files
        ]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/backup/restore-test")
async def restore_test_backup_endpoint(filename: str, request: Request):
    client_host = request.client.host if request.client else "unknown"
    if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="Restore-test permitido apenas localmente no computador hospedeiro.")
    try:
        _ensure_project_root_on_path()
        backup_restore = _load_backup_restore_module()

        zip_path = BACKUPS_DIR / os.path.basename(filename)
        if not zip_path.exists():
            raise HTTPException(status_code=404, detail="Arquivo de backup não encontrado.")
        return backup_restore.restore_test(zip_path)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/backup/restore")
async def restore_backup_endpoint(filename: str, request: Request):
    client_host = request.client.host if request.client else "unknown"
    if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="Restauração permitida apenas localmente no computador hospedeiro.")

    try:
        _ensure_project_root_on_path()
        backup_restore = _load_backup_restore_module()

        zip_path = BACKUPS_DIR / os.path.basename(filename)
        if not zip_path.exists():
            raise HTTPException(status_code=404, detail="Arquivo de backup não encontrado.")

        await engine.dispose()

        restored = backup_restore.do_restore(zip_path)
        if restored:
            return {"status": "success", "message": "Banco de dados e fotos restaurados com sucesso."}
        raise HTTPException(status_code=500, detail="Erro durante a restauração do backup. Os dados anteriores foram preservados.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
