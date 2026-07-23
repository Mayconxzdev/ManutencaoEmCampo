"""Dossiê imutável por ativo/ordem no repositório documental configurado.

O repositório de dossiês é uma cópia documental verificável, não o banco transacional. Cada
sincronização reescreve apenas o manifesto da OM e copia evidências pelo UUID,
mantendo o hash de cada arquivo. Falhas de rede ficam persistidas na fila, sem
descartar a evidência local.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit_service import create_audit_log
from app.clock import format_local_datetime, utcnow_naive
from app.config import NAS_REPOSITORY_DIR, UPLOADS_DIR
from app.models import (
    Asset,
    AssetDocument,
    DossierSyncJob,
    MaintenanceEvidence,
    MaintenanceOrder,
    MaintenanceOrderItem,
    WorkOrderEvent,
    WorkOrderSnapshot,
)
from app.upload_service import evidence_absolute_path


def _safe_segment(value: Optional[str], fallback: str) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", (value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text[:80] or fallback


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return hashlib.sha256(encoded).hexdigest()


async def _get_order(db: AsyncSession, order_id: str) -> MaintenanceOrder:
    result = await db.execute(
        select(MaintenanceOrder)
        .options(
            selectinload(MaintenanceOrder.asset),
            selectinload(MaintenanceOrder.asset).selectinload(Asset.documents),
            selectinload(MaintenanceOrder.items),
            selectinload(MaintenanceOrder.evidences),
            selectinload(MaintenanceOrder.events),
            selectinload(MaintenanceOrder.snapshot),
            selectinload(MaintenanceOrder.plan),
            selectinload(MaintenanceOrder.corrections),
        )
        .where(MaintenanceOrder.id == order_id)
    )
    order = result.scalars().first()
    if not order:
        raise ValueError("OM não encontrada para geração do dossiê.")
    return order


def _folder_name(order: MaintenanceOrder, *, completed: bool) -> str:
    status = "Concluída" if completed else "Em andamento"
    order_type = {
        "preventive": "Preventiva", "corrective": "Corretiva",
        "inspection": "Inspeção", "rework": "Retrabalho", "external": "Serviço externo",
    }.get(order.order_type or "", "Manutenção")
    if completed and order.completed_at:
        date_label = format_local_datetime(order.completed_at).split(" às ")[0].replace("/", "-")
    else:
        date_label = "Em andamento"
    return _safe_segment(f"{date_label} - OM {order.friendly_number or order.id[:8]} - {order_type} - {status}", "OM sem identificação")


def _asset_folder_name(asset: Asset) -> str:
    """Nome que uma pessoa encontra no Explorer sem conhecer UUIDs.

    Código, nome e setor são os identificadores usados fisicamente pela equipe.
    A unicidade continua protegida no manifesto, não no nome visível da pasta.
    """
    code = getattr(asset, "patrimonio", None) or getattr(asset, "controlled_code", None) or "SEM CÓDIGO"
    description = getattr(asset, "description", None) or getattr(asset, "type", None) or "Equipamento sem nome"
    sector = getattr(getattr(asset, "sector", None), "name", None)
    label = f"{code} - {description}" + (f" - {sector}" if sector else "")
    return _safe_segment(label, "Equipamento sem identificação")


def _order_directory(order: MaintenanceOrder) -> Path:
    asset = order.asset
    asset_dir = _asset_folder_name(asset)
    om_name = order.dossier_folder_name or _folder_name(order, completed=bool(order.completed_at))
    order.dossier_folder_name = om_name
    root = "00_TESTES_E_DEMONSTRACOES" if getattr(order, "record_kind", "official") == "demo_test" else "03_DOSSIES_ATIVOS"
    return NAS_REPOSITORY_DIR / root / asset_dir / om_name


def _asset_directory(asset: Asset) -> Path:
    return NAS_REPOSITORY_DIR / "03_DOSSIES_ATIVOS" / _asset_folder_name(asset)


def _event_payload(event: WorkOrderEvent) -> Any:
    try:
        return json.loads(event.payload) if event.payload else None
    except (TypeError, json.JSONDecodeError):
        return {"raw_payload": event.payload}


def _evidence_payload(evidence: MaintenanceEvidence) -> dict[str, Any]:
    return {
        "id": evidence.id,
        "type": evidence.evidence_type,
        "order_item_id": evidence.order_item_id,
        "sha256": evidence.file_hash,
        "stored_file": Path(evidence.dossier_path).name if evidence.dossier_path else None,
        "uploaded_at": _iso(evidence.uploaded_at),
        "captured_at": _iso(evidence.captured_at),
        "received_at": _iso(evidence.received_at),
        "uploader_name": evidence.uploader_name,
        "uploader_operator_id": evidence.uploader_operator_id,
        "device_id": evidence.device_id,
        "source": evidence.source,
        "original_filename": evidence.original_filename,
        "mime_type": evidence.mime_type,
        "file_size": evidence.file_size,
        "sync_status": evidence.dossier_status,
    }


def _asset_document_payload(document: AssetDocument) -> dict[str, Any]:
    return {
        "id": document.id,
        "name": document.name,
        "original_name": document.original_name,
        "category": document.category,
        "sha256": document.file_hash,
        "uploaded_at": _iso(document.uploaded_at),
        "uploaded_by": document.uploaded_by,
        "status": document.status,
        "stored_file": None,
    }


def _manifest(order: MaintenanceOrder, target: Path, generated_at: datetime) -> dict[str, Any]:
    asset = order.asset
    return {
        "schema": "mec-dossier/v1",
        "generated_at": _iso(generated_at),
        "repository_role": "official_traceability_copy",
        "asset": {
            "id": asset.id,
            "patrimonio": asset.patrimonio,
            "type": asset.type,
            "description": asset.description,
            "manufacturer": asset.manufacturer,
            "model": asset.model,
            "serial_number": asset.serial_number,
            "status": asset.status,
        },
        "work_order": {
            "id": order.id,
            "friendly_number": order.friendly_number,
            "type": order.order_type,
            "status": order.status,
            "record_kind": getattr(order, "record_kind", "official"),
            "record_kind_reason": getattr(order, "record_kind_reason", None),
            "execution_status": order.execution_status,
            "competence": order.original_competence,
            "planned_date": _iso(order.planned_date),
            "started_at": _iso(order.started_at),
            "completed_at": _iso(order.completed_at),
            "final_condition": order.final_condition,
            "final_sha256": order.final_sha256,
            "final_pdf_path": order.final_pdf_path,
            "final_pdf_sha256": getattr(order, "final_pdf_sha256", None),
            "checked_by": {"name": order.operator_name, "operator_id": order.operator_id},
            "performed_by": {"name": getattr(order, "performed_by_snapshot", None) or getattr(order, "performed_by_name", None), "operator_id": getattr(order, "performed_by_operator_id", None)},
            "performed_by_participants": json.loads(getattr(order, "performed_by_participants_json", None) or "[]"),
            "checklist_version_id": order.checklist_version_id,
            "plan_id": order.plan_id,
            "path": str(target),
        },
        "asset_documents": [_asset_document_payload(document) for document in sorted(asset.documents, key=lambda row: row.name or row.id) if document.status != "archived"],
        "checklist_answers": [
            {
                "id": item.id,
                "item_id": item.item_id,
                "status": item.status,
                "notes": item.notes,
                "answered_at": _iso(item.answered_at),
                "operator_name": item.operator_name,
                "operator_id": item.operator_id,
                "defect_found": item.defect_found,
                "corrected_in_place": item.corrected_in_place,
                "correction_description": item.correction_description,
                "needs_part": item.needs_part,
                "part_name": item.part_name,
                "can_operate": item.can_operate,
                "not_applicable_reason": item.not_applicable_reason,
            }
            for item in sorted(order.items, key=lambda row: row.id)
        ],
        "evidences": [_evidence_payload(evidence) for evidence in sorted(order.evidences, key=lambda row: row.uploaded_at or generated_at)],
        "events": [
            {
                "id": event.id,
                "type": event.event_type,
                "created_at": _iso(event.created_at),
                "operator_name": event.operator_name,
                "operator_id": event.operator_id,
                "payload": _event_payload(event),
            }
            for event in sorted(order.events, key=lambda row: row.created_at or generated_at)
        ],
        "creation_snapshot": json.loads(order.snapshot.snapshot_json) if order.snapshot and order.snapshot.snapshot_json else None,
        "corrections": [
            {"id": row.id, "field_name": row.field_name, "old_value": row.old_value, "new_value": row.new_value,
             "reason": row.reason, "operator_name": row.operator_name, "created_at": _iso(row.created_at),
             "revision": row.document_revision, "document_sha256": row.document_sha256,
             "stored_file": Path(row.document_path).name if row.document_path else None}
            for row in sorted(order.corrections, key=lambda row: (row.document_revision or 0, row.created_at or generated_at))
        ],
    }


async def queue_order_dossier(
    db: AsyncSession,
    order_id: str,
    *,
    requested_by: Optional[str] = None,
    requested_by_operator_id: Optional[str] = None,
    device_id: Optional[str] = None,
) -> DossierSyncJob:
    order = await _get_order(db, order_id)
    existing = await db.execute(
        select(DossierSyncJob)
        .where(DossierSyncJob.order_id == order_id, DossierSyncJob.status.in_(["pending", "running"]))
        .order_by(DossierSyncJob.requested_at.desc())
    )
    job = existing.scalars().first()
    if job:
        return job
    job = DossierSyncJob(
        order_id=order.id,
        asset_id=order.asset_id,
        status="pending",
        requested_by=requested_by,
        requested_by_operator_id=requested_by_operator_id,
        device_id=device_id,
        requested_at=utcnow_naive(),
    )
    db.add(job)
    await db.flush()
    return job


async def sync_asset_baseline(db: AsyncSession, asset_id: str) -> dict[str, Any]:
    """Garante uma pasta rastreável para todo ativo, mesmo sem OM histórica."""
    result = await db.execute(select(Asset).options(selectinload(Asset.documents)).where(Asset.id == asset_id))
    asset = result.scalars().first()
    if not asset:
        raise ValueError("Ativo não encontrado para criação do dossiê-base.")
    if not NAS_REPOSITORY_DIR.exists():
        raise RuntimeError(f"Repositório de dossiês indisponível: {NAS_REPOSITORY_DIR}")
    root = _asset_directory(asset)
    documents_dir = root / "00_Ativo" / "01_Documentos"
    documents_dir.mkdir(parents=True, exist_ok=True)
    document_rows: list[dict[str, Any]] = []
    for document in asset.documents:
        payload = _asset_document_payload(document)
        if document.status == "archived" or not document.internal_path:
            document_rows.append(payload)
            continue
        try:
            from app.asset_file_service import resolve_internal_path
            source = resolve_internal_path(document.internal_path)
            digest = _sha256(source)
            destination = documents_dir / f"{document.id}__{_safe_segment(Path(document.original_name or document.name).stem, document.id)}{source.suffix.lower() or '.bin'}"
            if not destination.exists() or _sha256(destination) != digest:
                shutil.copy2(source, destination)
            if _sha256(destination) != digest:
                raise RuntimeError("hash divergente no documento")
            payload["sha256"] = digest
            payload["stored_file"] = str(destination.relative_to(root))
        except Exception as exc:
            payload["sync_error"] = str(exc)
        document_rows.append(payload)
    generated_at = utcnow_naive()
    manifest_hash = _atomic_json(root / "00_Ativo" / "asset_manifest.json", {
        "schema": "mec-asset-dossier/v1",
        "generated_at": _iso(generated_at),
        "asset": {
            "id": asset.id, "patrimonio": asset.patrimonio, "type": asset.type,
            "description": asset.description, "manufacturer": asset.manufacturer,
            "model": asset.model, "serial_number": asset.serial_number, "status": asset.status,
        },
        "documents": document_rows,
    })
    _atomic_json(root / "00_Ativo" / "asset_manifest.sha256.json", {"manifest": "asset_manifest.json", "sha256": manifest_hash, "generated_at": _iso(generated_at)})
    return {"asset_id": asset.id, "target_path": str(root), "manifest_sha256": manifest_hash, "documents": len(document_rows)}


async def sync_job(db: AsyncSession, job: DossierSyncJob) -> dict[str, Any]:
    job.status = "running"
    job.attempt_count = (job.attempt_count or 0) + 1
    job.last_error = None
    await db.flush()
    try:
        if not NAS_REPOSITORY_DIR.exists():
            raise RuntimeError(f"Repositório de dossiês indisponível: {NAS_REPOSITORY_DIR}")
        order = await _get_order(db, job.order_id)
        target = _order_directory(order)
        # A primeira sincronização pode ocorrer ainda em andamento (por causa
        # de uma foto). Na conclusão, renomeamos a mesma pasta uma única vez
        # para que o Explorer mostre a data real e a competência planejada.
        if order.completed_at and "__EM_ANDAMENTO__" in (order.dossier_folder_name or ""):
            previous = target
            final_name = _folder_name(order, completed=True)
            final_target = previous.parent / final_name
            if previous.exists() and previous != final_target and not final_target.exists():
                previous.rename(final_target)
            order.dossier_folder_name = final_name
            target = final_target
        await sync_asset_baseline(db, order.asset_id)
        evidence_dir = target / "02 - Fotos e Evidências"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        for evidence in order.evidences:
            source = Path(evidence_absolute_path(evidence.file_path, str(UPLOADS_DIR)))
            if not source.exists():
                evidence.dossier_status = "missing_local_file"
                continue
            digest = _sha256(source)
            # Os arquivos novos usam o hash do arquivo armazenado. Para legado
            # com hash anterior divergente, preserva-se o registro e sinaliza-se.
            if evidence.file_hash and evidence.file_hash != digest:
                evidence.dossier_status = "legacy_hash_mismatch"
            else:
                evidence.file_hash = digest
                evidence.dossier_status = "synced"
            extension = source.suffix.lower() or ".bin"
            destination = evidence_dir / f"{evidence.id}{extension}"
            if not destination.exists() or _sha256(destination) != digest:
                shutil.copy2(source, destination)
            if _sha256(destination) != digest:
                raise RuntimeError(f"Hash divergente após cópia da evidência {evidence.id}")
            evidence.dossier_path = str(destination)
            evidence.dossier_synced_at = utcnow_naive()

        if order.final_pdf_path:
            final_pdf = Path(order.final_pdf_path)
            if final_pdf.exists() and final_pdf.is_file():
                final_dir = target / "01 - Checklist e PDF Final"
                final_dir.mkdir(parents=True, exist_ok=True)
                target_pdf = final_dir / final_pdf.name
                pdf_hash = _sha256(final_pdf)
                if not target_pdf.exists() or _sha256(target_pdf) != pdf_hash:
                    shutil.copy2(final_pdf, target_pdf)
                if _sha256(target_pdf) != pdf_hash:
                    raise RuntimeError(f"Hash divergente após cópia do PDF final da OM {order.id}")

        final_dir = target / "04 - Adendos de Correção"
        for correction in order.corrections:
            if not correction.document_path:
                continue
            source = Path(correction.document_path)
            if not source.exists() or not source.is_file():
                continue
            final_dir.mkdir(parents=True, exist_ok=True)
            destination = final_dir / source.name
            digest = _sha256(source)
            if not destination.exists() or _sha256(destination) != digest:
                shutil.copy2(source, destination)
            if _sha256(destination) != digest:
                raise RuntimeError(f"Hash divergente após cópia do adendo da OM {order.id}")

        # Um resumo em texto permite que alguém encontre o essencial no
        # Explorer do NAS, sem abrir JSON ou entender a estrutura técnica.
        if order.completed_at:
            started_event = next((event for event in sorted(order.events, key=lambda row: row.created_at or generated_at) if event.event_type == "started"), None)
            summary = "\n".join([
                f"EQUIPAMENTO: {order.asset.description} — {order.asset.patrimonio}",
                f"OM: {order.friendly_number or order.id}",
                f"TIPO DE REGISTRO: {'TESTE / DEMONSTRAÇÃO — NÃO CONTA COMO MANUTENÇÃO REAL' if getattr(order, 'record_kind', 'official') == 'demo_test' else 'MANUTENÇÃO OFICIAL'}",
                f"INICIADA POR: {started_event.operator_name if started_event else order.operator_name or 'Não informado'}",
                f"CONFERIDA E FINALIZADA POR: {order.operator_name or 'Não informado'}",
                f"MANUTENÇÃO EXECUTADA POR: {getattr(order, 'performed_by_snapshot', None) or getattr(order, 'performed_by_name', None) or 'Não informado'}",
                f"PARTICIPANTES: {', '.join(row.get('name', '') for row in json.loads(getattr(order, 'performed_by_participants_json', None) or '[]')) or 'Nenhum'}",
                f"CONCLUÍDA EM: {format_local_datetime(order.completed_at)}",
                f"COMPETÊNCIA PLANEJADA: {order.original_competence or 'Não informado'}",
                f"CONDIÇÃO FINAL: {order.final_condition or 'Não informado'}",
                f"EVIDÊNCIAS: {len(order.evidences)}",
                f"PDF FINAL: {Path(order.final_pdf_path).name if order.final_pdf_path else 'Não gerado'}",
                f"HASH DO RESUMO: {order.final_sha256 or 'Não informado'}",
                f"HASH DO PDF: {getattr(order, 'final_pdf_sha256', None) or 'Não informado'}",
                f"ADENDOS DE CORREÇÃO: {len(order.corrections)}",
                "",
            ])
            (target / "00_RESUMO_DA_MANUTENCAO.txt").write_text(summary, encoding="utf-8")

        generated_at = utcnow_naive()
        manifest = _manifest(order, target, generated_at)
        manifest_hash = _atomic_json(target / "manifest.json", manifest)
        _atomic_json(target / "manifest.sha256.json", {"manifest": "manifest.json", "sha256": manifest_hash, "generated_at": _iso(generated_at)})
        job.status = "synced"
        job.target_path = str(target)
        job.manifest_hash = manifest_hash
        job.completed_at = generated_at
        db.add(create_audit_log(
            action="dossier_synced",
            entity_name="maintenance_order",
            entity_id=order.id,
            operator_name=job.requested_by,
            selected_user_id=job.requested_by_operator_id,
            device_id=job.device_id,
            origin="nas_sync",
            new_values={"target_path": str(target), "manifest_sha256": manifest_hash, "job_id": job.id},
        ))
        await db.commit()
        return {"job_id": job.id, "status": job.status, "target_path": str(target), "manifest_sha256": manifest_hash}
    except Exception as exc:
        job.status = "failed"
        job.last_error = str(exc)
        await db.commit()
        return {"job_id": job.id, "status": "failed", "error": str(exc)}


async def sync_pending_jobs(db: AsyncSession, limit: int = 10) -> list[dict[str, Any]]:
    result = await db.execute(
        select(DossierSyncJob)
        .where(DossierSyncJob.status.in_(["pending", "failed"]))
        .order_by(DossierSyncJob.requested_at.asc())
        .limit(limit)
    )
    reports: list[dict[str, Any]] = []
    for job in result.scalars().all():
        reports.append(await sync_job(db, job))
    return reports


async def sync_order_in_background(order_id: str) -> None:
    """Faz a cópia pesada depois da resposta para o tablet.

    A OM e a fila já foram confirmadas no banco. Se o NAS não responder, a
    tentativa fica marcada e a rotina automática a reenvia sem ação manual.
    """
    from app.database import SessionLocal
    async with SessionLocal() as db:
        result = await db.execute(
            select(DossierSyncJob)
            .where(DossierSyncJob.order_id == order_id, DossierSyncJob.status.in_(["pending", "failed"]))
            .order_by(DossierSyncJob.requested_at.asc())
            .limit(1)
        )
        job = result.scalars().first()
        if job:
            await sync_job(db, job)
