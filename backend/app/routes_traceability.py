"""APIs de dossiê, histórico por ativo e não conformidade/CAPA."""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit_service import create_audit_log
from app.clock import utcnow_naive
from app.database import get_db
from app.dossier_service import queue_order_dossier, sync_asset_baseline, sync_job, sync_pending_jobs
from app.models import (
    Asset,
    DossierSyncJob,
    MaintenanceOrder,
    QualityNonconformity,
    WorkOrderEvent,
)


router = APIRouter(prefix="/v2", tags=["traceability"])


class DossierRequest(BaseModel):
    operator_name: Optional[str] = Field(default=None, max_length=100)
    selected_user_id: Optional[str] = Field(default=None, max_length=36)
    device_id: Optional[str] = Field(default=None, max_length=100)


class NonconformityCreate(BaseModel):
    asset_id: Optional[str] = None
    order_id: Optional[str] = None
    issue_id: Optional[str] = None
    title: str = Field(min_length=3, max_length=255)
    description: str = Field(min_length=3)
    requirement_reference: Optional[str] = Field(default=None, max_length=500)
    severity: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    detected_by_name: Optional[str] = Field(default=None, max_length=100)
    detected_by_operator_id: Optional[str] = Field(default=None, max_length=36)
    device_id: Optional[str] = Field(default=None, max_length=100)
    containment_action: Optional[str] = None
    root_cause: Optional[str] = None
    corrective_action: Optional[str] = None
    action_owner_name: Optional[str] = Field(default=None, max_length=100)
    due_date: Optional[date] = None


class NonconformityUpdate(BaseModel):
    status: Optional[str] = Field(default=None, pattern="^(open|contained|action_in_progress|effectiveness_pending|closed|reopened)$")
    containment_action: Optional[str] = None
    root_cause: Optional[str] = None
    corrective_action: Optional[str] = None
    action_owner_name: Optional[str] = Field(default=None, max_length=100)
    due_date: Optional[date] = None
    effectiveness_review: Optional[str] = None
    effectiveness_verified_by: Optional[str] = Field(default=None, max_length=100)
    reopen_reason: Optional[str] = None
    operator_name: Optional[str] = Field(default=None, max_length=100)
    selected_user_id: Optional[str] = Field(default=None, max_length=36)
    device_id: Optional[str] = Field(default=None, max_length=100)


def _serialize_job(job: DossierSyncJob) -> dict:
    return {
        "id": job.id,
        "order_id": job.order_id,
        "asset_id": job.asset_id,
        "status": job.status,
        "attempt_count": job.attempt_count,
        "requested_at": job.requested_at.isoformat() if job.requested_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "target_path": job.target_path,
        "manifest_sha256": job.manifest_hash,
        "last_error": job.last_error,
    }


def _serialize_nc(nc: QualityNonconformity) -> dict:
    return {
        "id": nc.id,
        "code": nc.code,
        "asset_id": nc.asset_id,
        "order_id": nc.order_id,
        "issue_id": nc.issue_id,
        "title": nc.title,
        "description": nc.description,
        "requirement_reference": nc.requirement_reference,
        "severity": nc.severity,
        "status": nc.status,
        "detected_at": nc.detected_at.isoformat() if nc.detected_at else None,
        "detected_by_name": nc.detected_by_name,
        "containment_action": nc.containment_action,
        "root_cause": nc.root_cause,
        "corrective_action": nc.corrective_action,
        "action_owner_name": nc.action_owner_name,
        "due_date": nc.due_date.isoformat() if nc.due_date else None,
        "completed_at": nc.completed_at.isoformat() if nc.completed_at else None,
        "effectiveness_review": nc.effectiveness_review,
        "effectiveness_verified_at": nc.effectiveness_verified_at.isoformat() if nc.effectiveness_verified_at else None,
        "effectiveness_verified_by": nc.effectiveness_verified_by,
        "closed_at": nc.closed_at.isoformat() if nc.closed_at else None,
        "closed_by": nc.closed_by,
        "reopened_at": nc.reopened_at.isoformat() if nc.reopened_at else None,
        "reopen_reason": nc.reopen_reason,
        "created_at": nc.created_at.isoformat() if nc.created_at else None,
        "updated_at": nc.updated_at.isoformat() if nc.updated_at else None,
    }


@router.get("/assets/{asset_id}/traceability")
async def asset_traceability(asset_id: str, db: AsyncSession = Depends(get_db)):
    asset = (await db.execute(select(Asset).where(Asset.id == asset_id))).scalars().first()
    if not asset:
        raise HTTPException(status_code=404, detail="Ativo não encontrado.")
    orders = (
        await db.execute(
            select(MaintenanceOrder)
            .options(selectinload(MaintenanceOrder.evidences), selectinload(MaintenanceOrder.events))
            .where(MaintenanceOrder.asset_id == asset_id)
            .order_by(MaintenanceOrder.completed_at.desc(), MaintenanceOrder.planned_year.desc(), MaintenanceOrder.planned_month.desc())
        )
    ).scalars().all()
    jobs = (
        await db.execute(
            select(DossierSyncJob).where(DossierSyncJob.asset_id == asset_id).order_by(DossierSyncJob.requested_at.desc())
        )
    ).scalars().all()
    ncs = (
        await db.execute(
            select(QualityNonconformity).where(QualityNonconformity.asset_id == asset_id).order_by(QualityNonconformity.created_at.desc())
        )
    ).scalars().all()
    return {
        "asset": {"id": asset.id, "patrimonio": asset.patrimonio, "description": asset.description, "serial_number": asset.serial_number},
        "history": [
            {
                "order_id": order.id,
                "friendly_number": order.friendly_number,
                "competence": order.original_competence,
                "planned_date": order.planned_date.isoformat() if order.planned_date else None,
                "completed_at": order.completed_at.isoformat() if order.completed_at else None,
                "status": order.status,
                "execution_status": order.execution_status,
                "final_condition": order.final_condition,
                "checklist_version_id": order.checklist_version_id,
                "final_sha256": order.final_sha256,
                "final_pdf_sha256": getattr(order, "final_pdf_sha256", None),
                "final_pdf_path": order.final_pdf_path,
                "final_revision": order.final_revision,
                "checked_by_name": order.operator_name,
                "performed_by_name": getattr(order, "performed_by_snapshot", None) or getattr(order, "performed_by_name", None),
                "evidences": [
                    {"id": ev.id, "type": ev.evidence_type, "uploaded_at": ev.uploaded_at.isoformat() if ev.uploaded_at else None,
                     "uploader_name": ev.uploader_name, "device_id": ev.device_id, "sha256": ev.file_hash,
                     "dossier_status": ev.dossier_status, "dossier_path": ev.dossier_path}
                    for ev in order.evidences
                ],
                "events": [
                    {"id": event.id, "type": event.event_type, "at": event.created_at.isoformat() if event.created_at else None,
                     "operator_name": event.operator_name, "operator_id": event.operator_id}
                    for event in order.events
                ],
            }
            for order in orders
        ],
        "dossier_jobs": [_serialize_job(job) for job in jobs],
        "nonconformities": [_serialize_nc(nc) for nc in ncs],
    }


@router.post("/orders/{order_id}/dossier/sync")
async def sync_order_dossier(order_id: str, request: DossierRequest, db: AsyncSession = Depends(get_db)):
    job = await queue_order_dossier(
        db,
        order_id,
        requested_by=request.operator_name,
        requested_by_operator_id=request.selected_user_id,
        device_id=request.device_id,
    )
    await db.commit()
    return await sync_job(db, job)


@router.post("/assets/{asset_id}/dossier/sync")
async def sync_asset_dossier(asset_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await sync_asset_baseline(db, asset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/orders/{order_id}/dossier")
async def order_dossier_status(order_id: str, db: AsyncSession = Depends(get_db)):
    jobs = (
        await db.execute(
            select(DossierSyncJob).where(DossierSyncJob.order_id == order_id).order_by(DossierSyncJob.requested_at.desc())
        )
    ).scalars().all()
    return {"order_id": order_id, "jobs": [_serialize_job(job) for job in jobs]}


@router.post("/dossiers/sync-pending")
async def process_pending_dossiers(limit: int = Query(default=20, ge=1, le=100), db: AsyncSession = Depends(get_db)):
    return {"results": await sync_pending_jobs(db, limit=limit)}


@router.get("/quality/nonconformities")
async def list_nonconformities(
    status: Optional[str] = None,
    asset_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(QualityNonconformity).order_by(QualityNonconformity.created_at.desc())
    if status:
        query = query.where(QualityNonconformity.status == status)
    if asset_id:
        query = query.where(QualityNonconformity.asset_id == asset_id)
    return [_serialize_nc(row) for row in (await db.execute(query)).scalars().all()]


@router.post("/quality/nonconformities", status_code=201)
async def create_nonconformity(payload: NonconformityCreate, db: AsyncSession = Depends(get_db)):
    if not payload.asset_id and not payload.order_id:
        raise HTTPException(status_code=422, detail="Informe ao menos o ativo ou a OM da não conformidade.")
    if payload.order_id:
        order = (await db.execute(select(MaintenanceOrder).where(MaintenanceOrder.id == payload.order_id))).scalars().first()
        if not order:
            raise HTTPException(status_code=404, detail="OM não encontrada.")
        if payload.asset_id and payload.asset_id != order.asset_id:
            raise HTTPException(status_code=422, detail="O ativo informado não corresponde à OM.")
        payload.asset_id = order.asset_id
    if payload.asset_id and not (await db.execute(select(Asset.id).where(Asset.id == payload.asset_id))).scalars().first():
        raise HTTPException(status_code=404, detail="Ativo não encontrado.")
    year = utcnow_naive().year
    sequence = int((await db.execute(select(func.count(QualityNonconformity.id)).where(QualityNonconformity.code.like(f"NC-{year}-%")))).scalar() or 0) + 1
    nc = QualityNonconformity(code=f"NC-{year}-{sequence:04d}", detected_at=utcnow_naive(), **payload.model_dump())
    db.add(nc)
    await db.flush()
    db.add(create_audit_log(
        action="nonconformity_created", entity_name="quality_nonconformity", entity_id=nc.id,
        operator_name=payload.detected_by_name, selected_user_id=payload.detected_by_operator_id,
        device_id=payload.device_id, origin="web", new_values={"code": nc.code, "status": nc.status, "severity": nc.severity},
    ))
    await db.commit()
    return _serialize_nc(nc)


@router.patch("/quality/nonconformities/{nonconformity_id}")
async def update_nonconformity(nonconformity_id: str, payload: NonconformityUpdate, db: AsyncSession = Depends(get_db)):
    nc = (await db.execute(select(QualityNonconformity).where(QualityNonconformity.id == nonconformity_id))).scalars().first()
    if not nc:
        raise HTTPException(status_code=404, detail="Não conformidade não encontrada.")
    old = _serialize_nc(nc)
    changes = payload.model_dump(exclude_unset=True)
    actor_name = changes.pop("operator_name", None)
    actor_id = changes.pop("selected_user_id", None)
    device_id = changes.pop("device_id", None)
    now = utcnow_naive()
    requested_status = changes.get("status")
    if requested_status == "closed":
        if not changes.get("effectiveness_review") and not nc.effectiveness_review:
            raise HTTPException(status_code=422, detail="Registre a verificação de eficácia antes de encerrar a não conformidade.")
        changes["closed_at"] = now
        changes["closed_by"] = actor_name
        changes["effectiveness_verified_at"] = nc.effectiveness_verified_at or now
        changes["effectiveness_verified_by"] = changes.get("effectiveness_verified_by") or actor_name
    elif requested_status == "reopened":
        if not changes.get("reopen_reason"):
            raise HTTPException(status_code=422, detail="Informe o motivo da reabertura.")
        changes["reopened_at"] = now
    elif requested_status == "effectiveness_pending":
        changes["completed_at"] = nc.completed_at or now
    for name, value in changes.items():
        setattr(nc, name, value)
    nc.updated_at = now
    db.add(create_audit_log(
        action="nonconformity_updated", entity_name="quality_nonconformity", entity_id=nc.id,
        operator_name=actor_name, selected_user_id=actor_id, device_id=device_id, origin="web",
        old_values=old, new_values=_serialize_nc(nc),
    ))
    await db.commit()
    return _serialize_nc(nc)
