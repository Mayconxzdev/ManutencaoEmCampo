import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status as http_status
from sqlalchemy import String, cast, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app import order_execution_service as execution_service
from app import schemas
from app.clock import utcnow_naive
from app.config import THUMBNAILS_DIR, UPLOADS_DIR as CONFIG_UPLOADS_DIR
from app.database import get_db
from app.models import (
    Asset,
    ChecklistTemplate,
    ChecklistTemplateVersion,
    MaintenanceEvidence,
    MaintenanceOrder,
)
from app.planning_service import create_order_items_from_checklist, next_friendly_number
from app.upload_service import evidence_absolute_path, validate_and_save_image


router = APIRouter()
UPLOADS_DIR = str(CONFIG_UPLOADS_DIR)


def _captured_at_or_now(value: Optional[str]):
    """Converte a data declarada pelo aparelho sem aceitar texto ambíguo."""
    if not value or not value.strip():
        return utcnow_naive()
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="captured_at deve estar no formato ISO 8601.") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


async def refresh_open_order_statuses(db: AsyncSession) -> None:
    result = await db.execute(
        select(MaintenanceOrder).where(
            MaintenanceOrder.status.in_(["scheduled", "today", "overdue", "in_progress"])
        )
    )
    changed = False
    for order in result.scalars().all():
        new_status = execution_service.effective_open_status(order)
        if new_status != order.status:
            order.status = new_status
            changed = True
    if changed:
        await db.flush()


@router.get("/checklists", response_model=List[schemas.ChecklistTemplate])
async def list_checklists(db: AsyncSession = Depends(get_db)):
    query = select(ChecklistTemplate).options(
        selectinload(ChecklistTemplate.versions).selectinload(ChecklistTemplateVersion.items)
    )
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/orders", response_model=List[schemas.MaintenanceOrder])
async def list_orders(
    status: Optional[str] = None,
    execution_status: Optional[str] = None,
    month: Optional[int] = None,
    year: Optional[int] = None,
    needs_review: Optional[bool] = None,
    q: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    await refresh_open_order_statuses(db)
    query = select(MaintenanceOrder).options(
        selectinload(MaintenanceOrder.asset).selectinload(Asset.sector),
        selectinload(MaintenanceOrder.items),
        selectinload(MaintenanceOrder.evidences),
        selectinload(MaintenanceOrder.materials),
    ).order_by(
        MaintenanceOrder.planned_year.desc(),
        MaintenanceOrder.planned_month.desc(),
        MaintenanceOrder.friendly_number,
    )

    if status:
        query = query.where(MaintenanceOrder.status == status)
    if execution_status:
        query = query.where(MaintenanceOrder.execution_status == execution_status)
    if month:
        query = query.where(MaintenanceOrder.planned_month == month)
    if year:
        query = query.where(MaintenanceOrder.planned_year == year)
    if needs_review is not None:
        query = query.where(MaintenanceOrder.needs_review == (1 if needs_review else 0))
    elif status == "overdue":
        query = query.where(MaintenanceOrder.needs_review == 0)

    if q:
        q_norm = q.replace("-", "").replace(" ", "").upper()
        query = query.join(Asset).where(
            or_(
                Asset.patrimonio.like(f"%{q}%"),
                Asset.patrimonio.like(f"%{q_norm}%"),
                Asset.description.like(f"%{q}%"),
                cast(MaintenanceOrder.friendly_number, String).like(f"%{q}%"),
            )
        )

    result = await db.execute(query)
    return result.scalars().all()


@router.post("/orders", response_model=schemas.MaintenanceOrder, status_code=http_status.HTTP_201_CREATED)
async def create_order(order: schemas.MaintenanceOrderCreate, db: AsyncSession = Depends(get_db)):
    db_order = MaintenanceOrder(
        friendly_number=await next_friendly_number(db),
        asset_id=order.asset_id,
        plan_id=order.plan_id,
        checklist_version_id=order.checklist_version_id,
        planned_date=order.planned_date,
        planned_year=order.planned_year or (order.planned_date.year if order.planned_date else None),
        planned_month=order.planned_month or (order.planned_date.month if order.planned_date else None),
        original_competence=order.original_competence or (
            f"{order.planned_year:04d}-{order.planned_month:02d}" if order.planned_year and order.planned_month else None
        ),
        scheduled_day_is_explicit=order.scheduled_day_is_explicit or bool(order.planned_date),
        original_date=order.planned_date,
        priority=order.priority,
        status=order.status,
        execution_status=order.execution_status,
        needs_review=order.needs_review,
        notes=order.notes,
        operator_name=order.operator_name,
        opaque_token=secrets.token_urlsafe(32),
    )
    db.add(db_order)
    await db.flush()

    await create_order_items_from_checklist(db, db_order)

    query = select(MaintenanceOrder).where(MaintenanceOrder.id == db_order.id).options(
        selectinload(MaintenanceOrder.asset).selectinload(Asset.sector),
        selectinload(MaintenanceOrder.items),
        selectinload(MaintenanceOrder.evidences),
    )
    res = await db.execute(query)
    return res.scalars().first()


@router.post("/orders/{order_id}/start")
async def start_order(order_id: str, operator_name: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    return await execution_service.start_order(db, order_id, operator_name or "Operador Padrão")


@router.post("/orders/{order_id}/begin-execution")
async def begin_order_execution(order_id: str, operator_name: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    return await execution_service.start_order(db, order_id, operator_name or "Operador Padrão")


@router.post("/orders/{order_id}/items/{item_id}")
async def answer_order_item(
    order_id: str,
    item_id: str,
    answer: schemas.MaintenanceOrderItemCreate,
    db: AsyncSession = Depends(get_db),
):
    return await execution_service.answer_item(
        db,
        order_id,
        item_id=item_id,
        result=answer.status,
        operator_name=answer.operator_name,
        notes=answer.notes,
        defect_found=answer.defect_found,
        corrected_in_place=answer.corrected_in_place,
        correction_description=answer.correction_description,
        needs_part=answer.needs_part,
        part_name=answer.part_name,
        can_operate=answer.can_operate,
        not_applicable_reason=answer.not_applicable_reason,
        audio_transcript=answer.audio_transcript,
        photo_category=answer.photo_category,
    )


@router.post("/orders/{order_id}/complete")
async def complete_order(
    order_id: str,
    final_condition: str,
    notes: Optional[str] = None,
    operator_name: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    return await execution_service.complete_order(
        db,
        order_id,
        operator_name=operator_name or "Operador Padrão",
        final_condition=final_condition,
        notes=notes,
        idempotency_key=idempotency_key,
    )


@router.post("/orders/interpret-photo")
async def interpret_photo_endpoint(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    from app.vision import process_sheet_photo

    try:
        os.makedirs(UPLOADS_DIR, exist_ok=True)
        contents = await file.read()
        rel_path, file_hash = validate_and_save_image(contents, file.filename, file.content_type, UPLOADS_DIR)

        db_evidence = MaintenanceEvidence(
            order_id=None,
            evidence_type="form_photo",
            file_path=rel_path,
            file_hash=file_hash,
            uploaded_at=utcnow_naive(),
            received_at=utcnow_naive(),
            source="cmp_scan",
            original_filename=file.filename,
            mime_type=file.content_type,
            file_size=len(contents),
            dossier_status="unassociated",
        )
        db.add(db_evidence)
        await db.flush()

        report = await process_sheet_photo(contents, file.filename, db)
        report["uploaded_file_path"] = rel_path
        report["file_hash"] = file_hash
        report["evidence_id"] = db_evidence.id

        if report.get("order_id"):
            db_evidence.order_id = report["order_id"]
            order_res = await db.execute(select(MaintenanceOrder).where(MaintenanceOrder.id == report["order_id"]))
            db_order = order_res.scalars().first()
            if db_order:
                db_evidence.asset_id = db_order.asset_id
            await db.flush()

        await db.commit()
        return report
    except HTTPException:
        raise
    except Exception as exc:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Erro ao processar imagem: {str(exc)}")


@router.post("/orders/associate-photo")
async def associate_photo(data: schemas.AssociatePhotoRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MaintenanceEvidence).where(MaintenanceEvidence.id == data.evidence_id))
    evidence = result.scalars().first()
    if not evidence:
        raise HTTPException(status_code=404, detail="Evidência temporária não encontrada.")

    order_result = await db.execute(select(MaintenanceOrder).where(MaintenanceOrder.id == data.order_id))
    order = order_result.scalars().first()
    if not order:
        raise HTTPException(status_code=404, detail="Ordem de manutenção não encontrada.")

    file_path = evidence_absolute_path(evidence.file_path, UPLOADS_DIR)
    if os.path.exists(file_path):
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        evidence.file_hash = hasher.hexdigest()

    evidence.order_id = data.order_id
    evidence.asset_id = order.asset_id

    await db.flush()
    await db.commit()
    return {
        "status": "success",
        "message": "Foto associada com sucesso.",
        "evidence_id": evidence.id,
        "file_hash": evidence.file_hash,
    }


@router.post("/orders/cleanup-photos")
async def cleanup_photos(db: AsyncSession = Depends(get_db)):
    # Evidências não associadas não são mais apagadas automaticamente. O
    # histórico permanece para associação/revisão humana posterior.
    result = await db.execute(
        select(MaintenanceEvidence).where(
            MaintenanceEvidence.order_id == None,  # noqa: E711
            MaintenanceEvidence.evidence_type == "form_photo",
        )
    )
    old_evidences = result.scalars().all()
    for evidence in old_evidences:
        evidence.dossier_status = "unassociated_review"
    await db.flush()
    return {"status": "preserved_for_review", "preserved_count": len(old_evidences), "deleted_count": 0}


@router.post("/orders/{order_id}/evidence")
async def upload_evidence(
    order_id: str,
    evidence_type: str,
    file: UploadFile = File(...),
    operator_name: Optional[str] = Form(None),
    selected_user_id: Optional[str] = Form(None),
    device_id: Optional[str] = Form(None),
    captured_at: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    order_result = await db.execute(select(MaintenanceOrder).where(MaintenanceOrder.id == order_id))
    order = order_result.scalars().first()
    if not order:
        raise HTTPException(status_code=404, detail="OM não encontrada.")
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    contents = await file.read()
    rel_path, file_hash = validate_and_save_image(contents, file.filename, file.content_type, UPLOADS_DIR)

    db_evidence = MaintenanceEvidence(
        order_id=order_id,
        asset_id=order.asset_id,
        evidence_type=evidence_type,
        file_path=rel_path,
        file_hash=file_hash,
        uploaded_at=utcnow_naive(),
        uploader_name=operator_name,
        uploader_operator_id=selected_user_id,
        device_id=device_id,
        captured_at=_captured_at_or_now(captured_at),
        received_at=utcnow_naive(),
        source="legacy_evidence_api",
        original_filename=file.filename,
        mime_type=file.content_type,
        file_size=len(contents),
        dossier_status="pending",
    )
    db.add(db_evidence)
    await db.flush()
    from app.dossier_service import queue_order_dossier
    dossier_job = await queue_order_dossier(
        db,
        order_id,
        requested_by=operator_name,
        requested_by_operator_id=selected_user_id,
        device_id=device_id,
    )
    await db.commit()
    from app.dossier_service import sync_job
    dossier_sync = await sync_job(db, dossier_job)
    return {"status": "success", "file_path": db_evidence.file_path, "id": db_evidence.id, "dossier_status": dossier_sync["status"], "dossier_sync": dossier_sync}
