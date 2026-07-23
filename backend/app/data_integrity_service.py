"""Diagnóstico operacional e integridade do Manutenção em Campo.

Objetivo: entregar ao operador/Codex um relatório auditável do estado real
sem alterar dados de negócio. Funciona principalmente em SQLite, mas evita
quebrar a aplicação se o banco for trocado no futuro.
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import APP_VERSION, BACKUP_EXTERNAL_DIR, BACKUPS_DIR, DATA_ROOT, DATABASE_PATH, LOGS_DIR, REPORTS_DIR, UPLOADS_DIR
from app.search_service import fts5_available
from app.transcription_service import capabilities as transcription_capabilities

CRITICAL_TABLES = [
    "assets",
    "maintenance_orders",
    "maintenance_plans",
    "operators",
    "checklist_templates",
    "checklist_template_versions",
]

OPTIONAL_TABLES = [
    "asset_documents",
    "asset_document_index",
    "file_review_items",
    "file_organization_tasks",
    "maintenance_order_items",
    "maintenance_evidences",
    "work_order_sequence",
    "global_search_fts",
    "system_validation_runs",
    "offline_sync_operations",
    "document_ocr_jobs",
    "system_backup_runs",
    "semantic_document_chunks",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path_info(path: Path) -> dict[str, Any]:
    try:
        exists = path.exists()
        return {
            "path": str(path),
            "exists": exists,
            "bytes": path.stat().st_size if exists and path.is_file() else None,
        }
    except OSError as exc:
        return {"path": str(path), "exists": False, "error": str(exc)}


def _truthy_env(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on", "sim"}


async def _table_exists(db: AsyncSession, table: str) -> bool:
    try:
        value = (await db.execute(
            text("SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name = :name"),
            {"name": table},
        )).scalar()
        return bool(value)
    except Exception:
        return False


async def _count_table(db: AsyncSession, table: str) -> int | None:
    if not await _table_exists(db, table):
        return None
    try:
        return int((await db.execute(text(f'SELECT count(*) FROM "{table}"'))).scalar() or 0)
    except Exception:
        return None


async def _safe_scalar(db: AsyncSession, sql: str, params: dict[str, Any] | None = None) -> Any:
    try:
        return (await db.execute(text(sql), params or {})).scalar()
    except Exception as exc:
        return {"error": str(exc)}


async def sqlite_integrity(db: AsyncSession) -> dict[str, Any]:
    """Executa PRAGMAs de integridade e FK. Em SQLite, integrity_check não substitui foreign_key_check."""
    result: dict[str, Any] = {"database_path": str(DATABASE_PATH)}
    try:
        integrity = (await db.execute(text("PRAGMA integrity_check"))).scalars().all()
        result["integrity_check"] = integrity
        result["integrity_ok"] = integrity == ["ok"]
    except Exception as exc:
        result["integrity_ok"] = False
        result["integrity_error"] = str(exc)

    try:
        fk_rows = (await db.execute(text("PRAGMA foreign_key_check"))).mappings().all()
        result["foreign_key_violations"] = [dict(row) for row in fk_rows]
        result["foreign_key_ok"] = len(fk_rows) == 0
    except Exception as exc:
        result["foreign_key_ok"] = False
        result["foreign_key_error"] = str(exc)
    return result


async def duplicate_checks(db: AsyncSession) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    if await _table_exists(db, "maintenance_orders"):
        rows = (await db.execute(text("""
            SELECT friendly_number, count(*) AS total
            FROM maintenance_orders
            WHERE friendly_number IS NOT NULL
            GROUP BY friendly_number
            HAVING count(*) > 1
            ORDER BY total DESC, friendly_number
            LIMIT 50
        """))).mappings().all()
        checks["duplicate_order_numbers"] = [dict(row) for row in rows]
    if await _table_exists(db, "assets"):
        rows = (await db.execute(text("""
            SELECT patrimonio, count(*) AS total
            FROM assets
            WHERE patrimonio IS NOT NULL AND trim(patrimonio) <> '' AND status <> 'inactive'
            GROUP BY patrimonio
            HAVING count(*) > 1
            ORDER BY total DESC, patrimonio
            LIMIT 50
        """))).mappings().all()
        checks["duplicate_active_patrimonios"] = [dict(row) for row in rows]
    return checks


async def search_index_status(db: AsyncSession) -> dict[str, Any]:
    available = await fts5_available(db)
    status: dict[str, Any] = {"fts5_available": available, "indexed_rows": 0, "needs_rebuild": True}
    if available and await _table_exists(db, "global_search_fts"):
        indexed = await _count_table(db, "global_search_fts") or 0
        assets = await _count_table(db, "assets") or 0
        orders = await _count_table(db, "maintenance_orders") or 0
        docs = (await _count_table(db, "asset_documents") or 0) + (await _count_table(db, "asset_document_index") or 0)
        minimum_expected = assets + docs
        status.update({
            "indexed_rows": indexed,
            "minimum_expected_rows": minimum_expected,
            "orders_in_database": orders,
            "needs_rebuild": indexed < minimum_expected,
        })
    return status


async def operational_counts(db: AsyncSession) -> dict[str, Any]:
    tables = CRITICAL_TABLES + OPTIONAL_TABLES
    return {table: await _count_table(db, table) for table in tables}


async def backup_status(db: AsyncSession) -> dict[str, Any]:
    external = {
        "configured": BACKUP_EXTERNAL_DIR is not None,
        "path": str(BACKUP_EXTERNAL_DIR) if BACKUP_EXTERNAL_DIR is not None else None,
        "exists": False,
        "writable": False,
    }
    if BACKUP_EXTERNAL_DIR is not None:
        try:
            path = Path(BACKUP_EXTERNAL_DIR)
            external["exists"] = path.exists() and path.is_dir()
            if external["exists"]:
                probe = path / ".mec_backup_write_test"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink(missing_ok=True)
                external["writable"] = True
        except OSError as exc:
            external["error"] = str(exc)

    latest_restore = None
    if await _table_exists(db, "system_backup_runs"):
        latest_restore = (await db.execute(text("""
            SELECT created_at, backup_path, backup_sha256, restore_test_ok, status
              FROM system_backup_runs
             WHERE kind IN ('restore_test', 'backup_restore_test', 'restore-test')
             ORDER BY created_at DESC
             LIMIT 1
        """))).mappings().first()
    return {
        "local_path": str(BACKUPS_DIR),
        "local_exists": BACKUPS_DIR.exists(),
        "external": external,
        "latest_restore_test": dict(latest_restore) if latest_restore else None,
    }


async def readiness_report(db: AsyncSession) -> dict[str, Any]:
    integrity = await sqlite_integrity(db)
    duplicates = await duplicate_checks(db)
    search_status = await search_index_status(db)
    counts = await operational_counts(db)
    backup = await backup_status(db)
    disk = shutil.disk_usage(DATA_ROOT if DATA_ROOT.exists() else Path.cwd())

    blockers: list[str] = []
    warnings: list[str] = []
    accepted_warnings: list[str] = []

    if not integrity.get("integrity_ok"):
        blockers.append("PRAGMA integrity_check não retornou ok.")
    if not integrity.get("foreign_key_ok"):
        blockers.append("Há violações ou falha no PRAGMA foreign_key_check.")
    if duplicates.get("duplicate_order_numbers"):
        blockers.append("Existem números de OM duplicados.")
    if duplicates.get("duplicate_active_patrimonios") and _truthy_env("MEC_ACCEPT_DUPLICATE_PATRIMONIOS"):
        accepted_warnings.append("Patrimônios ativos duplicados mantidos por decisão operacional registrada.")
    elif duplicates.get("duplicate_active_patrimonios"):
        warnings.append("Existem patrimônios ativos duplicados; pode ser legado, mas precisa conferência.")
    if search_status.get("needs_rebuild"):
        warnings.append("Índice de busca global precisa reconstrução ou está incompleto.")
    if counts.get("offline_sync_operations") is None:
        warnings.append("Migration de fila offline ainda não aplicada.")
    if counts.get("document_ocr_jobs") is None:
        warnings.append("Migration de OCR/revisão documental ainda não aplicada.")
    if disk.free < 2 * 1024 * 1024 * 1024:
        warnings.append("Espaço livre menor que 2 GB; risco para backup/rollback.")
    if backup["external"]["configured"]:
        if not backup["external"].get("exists") or not backup["external"].get("writable"):
            blockers.append("Backup externo configurado, mas inacessível ou sem escrita.")
        latest_restore = backup.get("latest_restore_test")
        if not latest_restore or not latest_restore.get("restore_test_ok"):
            warnings.append("Backup externo/local sem restore-test válido registrado.")

    for table in CRITICAL_TABLES:
        if counts.get(table) is None:
            blockers.append(f"Tabela crítica ausente: {table}.")

    optional = transcription_capabilities()
    if not optional.get("enabled"):
        warnings.append("Transcrição automática está desabilitada; áudios serão preservados sem texto.")
    if optional.get("enabled") and optional.get("backend") == "auto" and not any([
        optional.get("openai", {}).get("available"),
        optional.get("whisper_cpp", {}).get("available"),
        optional.get("vibe", {}).get("available"),
        optional.get("faster_whisper", {}).get("available"),
    ]):
        warnings.append("Transcrição está habilitada, mas nenhum backend real foi detectado.")

    score = 100
    score -= 25 * len(blockers)
    score -= 6 * len(warnings)
    score = max(0, min(100, score))
    status = "blocked" if blockers else ("attention" if warnings else "ready")

    return {
        "generated_at": _now_iso(),
        "version": APP_VERSION,
        "status": status,
        "score": score,
        "blockers": blockers,
        "warnings": warnings,
        "accepted_warnings": accepted_warnings,
        "paths": {
            "data_root": _path_info(DATA_ROOT),
            "database": _path_info(DATABASE_PATH),
            "uploads": _path_info(UPLOADS_DIR),
            "backups": _path_info(BACKUPS_DIR),
            "reports": _path_info(REPORTS_DIR),
            "logs": _path_info(LOGS_DIR),
        },
        "storage": {
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
        },
        "database": {
            "alembic_revision": await _safe_scalar(db, "SELECT version_num FROM alembic_version LIMIT 1") if await _table_exists(db, "alembic_version") else None,
            "integrity": integrity,
            "counts": counts,
            "duplicates": duplicates,
        },
        "search": search_status,
        "transcription": optional,
        "backup": backup,
    }


async def record_validation_run(db: AsyncSession, report: dict[str, Any], *, kind: str = "manual", executed_by: str | None = None) -> dict[str, Any]:
    if not await _table_exists(db, "system_validation_runs"):
        return {"saved": False, "reason": "Tabela system_validation_runs ainda não existe. Rode as migrations."}
    import uuid

    run_id = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO system_validation_runs(id, created_at, kind, status, score, executed_by, report_json)
        VALUES (:id, :created_at, :kind, :status, :score, :executed_by, :report_json)
    """), {
        "id": run_id,
        "created_at": _now_iso(),
        "kind": kind,
        "status": report.get("status"),
        "score": int(report.get("score") or 0),
        "executed_by": executed_by,
        "report_json": json.dumps(report, ensure_ascii=False),
    })
    await db.commit()
    return {"saved": True, "id": run_id}
