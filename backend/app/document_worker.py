from __future__ import annotations

import asyncio
import json
import os
import socket
from pathlib import Path
from typing import Iterable

from sqlalchemy import select

from app.clock import utcnow_naive
from app.config import REPORTS_DIR, APP_VERSION
from app.database import SessionLocal
from app.models import FileOrganizationTask


ACTIVE_STATUSES = {"pending", "queued", "running", "in_progress"}


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def file_worker_enabled() -> bool:
    return _truthy(os.getenv("MEC_FILE_ORGANIZATION_WORKER_ENABLED"), default=True)


def configured_sources() -> list[str]:
    raw = os.getenv("MEC_FILE_ORGANIZATION_SOURCES") or os.getenv("MEC_DOCUMENT_WORKER_SOURCES") or ""
    return [item.strip().strip('"') for item in raw.split(";") if item.strip()]


def _task_sources(task: FileOrganizationTask) -> list[str]:
    if not task.source_paths_json:
        return []
    try:
        parsed = json.loads(task.source_paths_json)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed if str(item).strip()]


async def ensure_configured_file_task() -> FileOrganizationTask | None:
    sources = configured_sources()
    if not sources:
        return None
    normalized_sources = json.dumps(sources, ensure_ascii=False)
    async with SessionLocal() as db:
        active = await db.execute(
            select(FileOrganizationTask).where(
                FileOrganizationTask.task_type == "asset_file_organization",
                FileOrganizationTask.status.in_(list(ACTIVE_STATUSES)),
            )
        )
        for task in active.scalars().all():
            if _task_sources(task) == sources:
                return task
        now = utcnow_naive()
        task = FileOrganizationTask(
            task_type="asset_file_organization",
            status="queued",
            source_paths_json=normalized_sources,
            updated_at=now,
            message="Tarefa criada automaticamente pela configuração MEC_FILE_ORGANIZATION_SOURCES.",
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        return task


async def next_file_task() -> FileOrganizationTask | None:
    async with SessionLocal() as db:
        result = await db.execute(
            select(FileOrganizationTask)
            .where(
                FileOrganizationTask.task_type == "asset_file_organization",
                FileOrganizationTask.status.in_(list(ACTIVE_STATUSES)),
                FileOrganizationTask.cancel_requested_at == None,  # noqa: E711
                FileOrganizationTask.pause_requested_at == None,  # noqa: E711
            )
            .order_by(FileOrganizationTask.updated_at.asc().nullsfirst(), FileOrganizationTask.started_at.asc().nullsfirst())
        )
        task = result.scalars().first()
        if not task:
            return None
        task.worker_id = f"{socket.gethostname()}:{os.getpid()}"
        task.status = "queued"
        task.updated_at = utcnow_naive()
        await db.commit()
        await db.refresh(task)
        return task


def _paths(items: Iterable[str]) -> list[Path]:
    return [Path(item).expanduser().resolve() for item in items if item]


async def run_file_organization_worker_once() -> dict:
    if not file_worker_enabled():
        return {"enabled": False, "processed": 0, "message": "Worker documental desabilitado por configuração."}

    await ensure_configured_file_task()
    task = await next_file_task()
    if not task:
        return {"enabled": True, "processed": 0, "message": "Nenhuma tarefa documental pendente."}

    sources = _paths(_task_sources(task))
    if not sources:
        async with SessionLocal() as db:
            current = await db.get(FileOrganizationTask, task.id)
            if current:
                current.status = "failed"
                current.message = "Tarefa sem pasta de origem configurada."
                current.updated_at = utcnow_naive()
                current.completed_at = utcnow_naive()
                await db.commit()
        return {"enabled": True, "processed": 0, "task_id": task.id, "message": "Tarefa sem origem."}

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"file_organization_{APP_VERSION}_{task.id}.json"

    from scripts.import_asset_files_167 import import_sources

    summary = await import_sources(sources, dry_run=False, task_id=task.id, report_path=str(report_path))
    return {"enabled": True, "processed": 1, "task_id": task.id, "summary": summary}


def start_file_organization_worker_background() -> None:
    if not file_worker_enabled():
        print("[FILE WORKER] Desabilitado por MEC_FILE_ORGANIZATION_WORKER_ENABLED.")
        return

    async def _runner() -> None:
        try:
            result = await run_file_organization_worker_once()
            print(f"[FILE WORKER] {result.get('message') or 'Execução concluída.'}")
        except Exception as exc:
            print(f"[FILE WORKER ERROR] {exc}")

    asyncio.create_task(_runner())
