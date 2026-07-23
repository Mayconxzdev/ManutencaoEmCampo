from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import sys
from pathlib import Path

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.config import APP_VERSION, DATA_ROOT, DATABASE_PATH
from app.database import get_db
from app.models import Asset, AssetDocument, MaintenanceOrder, Operator
from app.search_service import fts5_available
from app.transcription_service import capabilities as transcription_capabilities
from app.data_integrity_service import readiness_report, record_validation_run, sqlite_integrity

router = APIRouter(prefix="/v2/system", tags=["system"])


def _size(path: Path) -> int:
    try:
        return path.stat().st_size if path.exists() else 0
    except OSError:
        return 0


def _exists_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _ocr_available() -> bool:
    return (_exists_module("paddleocr") and _exists_module("paddle")) or _exists_module("rapidocr_onnxruntime")


@router.get("/diagnostics")
async def diagnostics(db: AsyncSession = Depends(get_db)):
    counts = {}
    for key, model in {
        "assets": Asset,
        "orders": MaintenanceOrder,
        "asset_files": AssetDocument,
        "operators": Operator,
    }.items():
        try:
            counts[key] = int((await db.execute(select(sa.func.count()).select_from(model))).scalar() or 0)
        except Exception as exc:
            counts[key] = {"error": str(exc)}

    disk = shutil.disk_usage(DATA_ROOT)
    optional_tools = {
        "pymupdf": _exists_module("fitz"),
        "pypdf": _exists_module("pypdf"),
        "paddleocr": _exists_module("paddleocr") and _exists_module("paddle"),
        "paddle": _exists_module("paddle"),
        "rapidocr_onnxruntime": _exists_module("rapidocr_onnxruntime"),
        "faster_whisper": _exists_module("faster_whisper"),
        "sentence_transformers": _exists_module("sentence_transformers"),
        "qdrant_client": _exists_module("qdrant_client"),
        "lancedb": _exists_module("lancedb"),
    }
    return {
        "app": {"name": "Manutenção em Campo", "version": APP_VERSION},
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "storage_mode": "local-demo",
        },
        "storage": {
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
            "database_bytes": _size(DATABASE_PATH),
        },
        "database": {
            "url_mode": "sqlite" if str(DATABASE_PATH) in os.getenv("DATABASE_URL", str(DATABASE_PATH)) else "custom",
            "sqlite_fts5": await fts5_available(db),
        },
        "counts": counts,
        "transcription": transcription_capabilities(),
        "optional_tools": optional_tools,
    }


@router.get("/capabilities")
async def capabilities(db: AsyncSession = Depends(get_db)):
    return {
        "search": {"sqlite_fts5": await fts5_available(db)},
        "transcription": transcription_capabilities(),
        "documents": {
            "text_pdf": _exists_module("fitz") or _exists_module("pypdf"),
            "ocr_advanced": _ocr_available(),
            "office_docx": _exists_module("docx"),
            "office_xlsx": _exists_module("openpyxl"),
        },
    }


@router.get("/compatibility")
async def compatibility_report():
    """Lista compatibilidades legadas que não devem ser usadas como fluxo principal."""
    return {
        "identity_mode": "traceability_only_no_rbac",
        "selected_user_id_required_for_new_flows": True,
        "legacy_operator_name_fallback": [
            {
                "surface": "routes_orders",
                "status": "legacy_compatibility",
                "note": "Rotas antigas /orders/* aceitam operator_name para compatibilidade, mas delegam ao serviço central.",
            },
            {
                "surface": "reports/history filters",
                "status": "read_only_display",
                "note": "Campos operator_name existentes são mantidos como snapshot histórico.",
            },
            {
                "surface": "quality/admin compatibility",
                "status": "diagnostic_only",
                "note": "Perfis e PIN não bloqueiam ações; existem apenas para diagnóstico/compatibilidade.",
            },
        ],
    }


@router.get("/integrity")
async def integrity(db: AsyncSession = Depends(get_db)):
    """Retorna PRAGMA integrity_check e foreign_key_check sem alterar dados."""
    return await sqlite_integrity(db)


@router.get("/readiness")
async def readiness(db: AsyncSession = Depends(get_db)):
    """Relatório executivo: bloqueios, alertas, score e evidências técnicas."""
    return await readiness_report(db)


@router.post("/validation-run")
async def validation_run(executed_by: str | None = None, kind: str = "manual", db: AsyncSession = Depends(get_db)):
    """Gera e salva um diagnóstico para histórico de auditoria."""
    report = await readiness_report(db)
    saved = await record_validation_run(db, report, kind=kind, executed_by=executed_by)
    return {"report": report, "persistence": saved}
