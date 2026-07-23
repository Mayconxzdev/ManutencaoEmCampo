import hashlib
import json
import os
import secrets
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app import schemas
from app.audit_service import create_audit_log
from app.clock import utcnow_naive
from app.database import get_db
from app.models import (
    Asset,
    AssetDocument,
    AssetDocumentIndex,
    AssetMeter,
    AuditLog,
    MaintenanceIssue,
    MaintenancePlan,
    Sector,
)
from app.operator_service import resolve_selected_operator


router = APIRouter()


async def load_primary_asset_documents(db: AsyncSession, asset_ids: list[str]) -> dict[str, AssetDocument]:
    if not asset_ids:
        return {}
    result = await db.execute(
        select(AssetDocument)
        .where(
            AssetDocument.asset_id.in_(asset_ids),
            AssetDocument.category == "photo",
            AssetDocument.thumbnail_path.is_not(None),
            (AssetDocument.status.is_(None) | (AssetDocument.status == "active")),
        )
        .order_by(
            AssetDocument.asset_id,
            AssetDocument.is_primary_photo.desc(),
            AssetDocument.imported_at.desc(),
        )
    )
    docs: dict[str, AssetDocument] = {}
    for doc in result.scalars().all():
        docs.setdefault(doc.asset_id, doc)
    return docs


def serialize_asset(asset: Asset, primary_docs: Optional[dict[str, AssetDocument]] = None) -> dict:
    primary_doc = (primary_docs or {}).get(asset.id)
    return {
        "id": asset.id,
        "patrimonio": asset.patrimonio,
        "type": asset.type,
        "description": asset.description,
        "manufacturer": asset.manufacturer,
        "model": asset.model,
        "serial_number": asset.serial_number,
        "sector_id": asset.sector_id,
        "sector": asset.sector,
        "status": asset.status,
        "is_operable": bool(asset.is_operable),
        "last_maintenance_date": asset.last_maintenance_date,
        "next_maintenance_date": asset.next_maintenance_date,
        "notes": asset.notes,
        "manual": asset.manual,
        "ficha_tecnica": asset.ficha_tecnica,
        "foto": asset.foto,
        "caminho_documentos": asset.caminho_documentos,
        "has_patrimonio_conflict": bool(asset.has_patrimonio_conflict),
        "conflict_patrimonio_suggested": asset.conflict_patrimonio_suggested,
        "opaque_token": asset.opaque_token,
        "legacy_patrimonio": asset.legacy_patrimonio,
        "controlled_code": asset.controlled_code,
        "asset_class": asset.asset_class,
        "maintenance_strategy": asset.maintenance_strategy,
        "show_in_daily_list": bool(asset.show_in_daily_list),
        "thumbnail_url": f"/v2/files/{primary_doc.id}/thumbnail" if primary_doc else None,
        "primary_photo_id": primary_doc.id if primary_doc else None,
    }


@router.get("/sectors", response_model=List[schemas.Sector])
async def list_sectors(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Sector))
    return result.scalars().all()


@router.post("/sectors", response_model=schemas.Sector, status_code=status.HTTP_201_CREATED)
async def create_sector(sector: schemas.SectorCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(Sector).where(Sector.name == sector.name))
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail="Setor já cadastrado")

    db_sector = Sector(name=sector.name, description=sector.description)
    db.add(db_sector)
    await db.flush()
    return db_sector


@router.get("/assets", response_model=List[schemas.Asset])
async def list_assets(
    type: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(Asset).options(selectinload(Asset.sector))
    if type:
        query = query.where(Asset.type == type)
    if status:
        query = query.where(Asset.status == status)

    if q:
        q_norm = q.replace("-", "").replace(" ", "").upper()
        query = query.where(
            or_(
                Asset.patrimonio.like(f"%{q}%"),
                Asset.patrimonio.like(f"%{q_norm}%"),
                Asset.description.like(f"%{q}%"),
                Asset.manufacturer.like(f"%{q}%"),
                Asset.model.like(f"%{q}%"),
            )
        )

    result = await db.execute(query)
    assets = result.scalars().all()
    primary_docs = await load_primary_asset_documents(db, [asset.id for asset in assets])
    return [serialize_asset(asset, primary_docs) for asset in assets]


@router.get("/assets/resolve-identifier")
async def resolve_asset_identifier(value: str, db: AsyncSession = Depends(get_db)):
    """Resolve QR/código antigo sem escolher errado quando há duplicidade.

    Etiquetas novas usam o token único. Esta rota existe para os QR e códigos
    já impressos que podem apontar para mais de um item da planilha.
    """
    raw = (value or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Informe o código ou patrimônio.")
    normalized = raw.replace("-", "").replace(" ", "").upper()
    result = await db.execute(
        select(Asset).options(selectinload(Asset.sector)).where(
            or_(
                Asset.opaque_token == raw,
                Asset.id == raw,
                Asset.patrimonio == raw,
                Asset.controlled_code == raw,
                Asset.legacy_patrimonio == raw,
                Asset.patrimonio == normalized,
                Asset.controlled_code == normalized,
                Asset.legacy_patrimonio == normalized,
            )
        )
    )
    assets = result.scalars().all()
    primary_docs = await load_primary_asset_documents(db, [asset.id for asset in assets])
    candidates = [serialize_asset(asset, primary_docs) for asset in assets]
    return {
        "status": "not_found" if not candidates else "unique" if len(candidates) == 1 else "ambiguous",
        "value": raw,
        "candidates": candidates,
    }


@router.get("/assets/{asset_id:uuid}", response_model=schemas.Asset)
async def get_asset(asset_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    query = select(Asset).where(Asset.id == str(asset_id)).options(selectinload(Asset.sector))
    result = await db.execute(query)
    db_asset = result.scalars().first()
    if not db_asset:
        raise HTTPException(status_code=404, detail="Ativo não encontrado")
    primary_docs = await load_primary_asset_documents(db, [db_asset.id])
    return serialize_asset(db_asset, primary_docs)


@router.get("/assets/{asset_id}/plans", response_model=List[schemas.MaintenancePlan])
async def get_asset_plans(asset_id: str, db: AsyncSession = Depends(get_db)):
    query = select(MaintenancePlan).where(MaintenancePlan.asset_id == asset_id)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/plans", response_model=List[schemas.MaintenancePlan])
async def list_all_plans(db: AsyncSession = Depends(get_db)):
    query = select(MaintenancePlan).where(MaintenancePlan.is_active == True)  # noqa: E712
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/assets/{asset_id}/plans", response_model=schemas.MaintenancePlan)
async def create_or_update_asset_plan(
    asset_id: str,
    plan_data: schemas.MaintenancePlanBase,
    selected_user_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    operator = await resolve_selected_operator(db, selected_user_id)
    query = select(MaintenancePlan).where(MaintenancePlan.asset_id == asset_id, MaintenancePlan.is_active == True)  # noqa: E712
    result = await db.execute(query)
    db_plan = result.scalars().first()

    if db_plan:
        old_values = {
            "name": db_plan.name,
            "periodicity": db_plan.periodicity,
            "checklist_template_version_id": db_plan.checklist_template_version_id,
            "recurrence_status": db_plan.recurrence_status,
        }
        db_plan.name = plan_data.name
        db_plan.periodicity = plan_data.periodicity
        db_plan.frequency_days = plan_data.frequency_days
        db_plan.frequency_months = plan_data.frequency_months
        db_plan.planned_month = plan_data.planned_month
        db_plan.next_due_date = plan_data.next_due_date
        db_plan.checklist_template_version_id = plan_data.checklist_template_version_id
        db_plan.estimated_duration_mins = plan_data.estimated_duration_mins
        db_plan.calculation_basis = plan_data.calculation_basis
        db_plan.plan_type = plan_data.plan_type
        db_plan.fixed_months = plan_data.fixed_months
        db_plan.generation_horizon_months = plan_data.generation_horizon_months
        db_plan.confidence = plan_data.confidence
        db_plan.source_document = plan_data.source_document
        db_plan.source_document_hash = plan_data.source_document_hash
        db_plan.source_document_page = plan_data.source_document_page
        db_plan.confirmed_by = plan_data.confirmed_by
        db_plan.confirmed_at = plan_data.confirmed_at
        db_plan.recurrence_status = plan_data.recurrence_status
        db_plan.recurrence_confirmed_by = plan_data.recurrence_confirmed_by
        db_plan.recurrence_confirmed_at = plan_data.recurrence_confirmed_at
        db_plan.safety_instructions = plan_data.safety_instructions
        db_plan.is_monthly_competency = plan_data.is_monthly_competency
        audit_action = "maintenance_plan_updated"
    else:
        db_plan = MaintenancePlan(
            asset_id=asset_id,
            name=plan_data.name,
            periodicity=plan_data.periodicity,
            frequency_days=plan_data.frequency_days,
            frequency_months=plan_data.frequency_months,
            planned_month=plan_data.planned_month,
            next_due_date=plan_data.next_due_date,
            checklist_template_version_id=plan_data.checklist_template_version_id,
            estimated_duration_mins=plan_data.estimated_duration_mins,
            calculation_basis=plan_data.calculation_basis,
            plan_type=plan_data.plan_type,
            fixed_months=plan_data.fixed_months,
            generation_horizon_months=plan_data.generation_horizon_months,
            confidence=plan_data.confidence,
            source_document=plan_data.source_document,
            source_document_hash=plan_data.source_document_hash,
            source_document_page=plan_data.source_document_page,
            confirmed_by=plan_data.confirmed_by,
            confirmed_at=plan_data.confirmed_at,
            recurrence_status=plan_data.recurrence_status,
            recurrence_confirmed_by=plan_data.recurrence_confirmed_by,
            recurrence_confirmed_at=plan_data.recurrence_confirmed_at,
            safety_instructions=plan_data.safety_instructions,
            is_monthly_competency=plan_data.is_monthly_competency,
            is_active=True,
        )
        db.add(db_plan)
        old_values = None
        audit_action = "maintenance_plan_created"

    await db.flush()
    db.add(create_audit_log(
        action=audit_action,
        entity_name="maintenance_plan",
        entity_id=db_plan.id,
        operator_name=operator.name if operator else plan_data.recurrence_confirmed_by,
        old_values=old_values,
        new_values={
            "asset_id": asset_id,
            "name": db_plan.name,
            "periodicity": db_plan.periodicity,
            "checklist_template_version_id": db_plan.checklist_template_version_id,
            "recurrence_status": db_plan.recurrence_status,
            "selected_user_id": selected_user_id,
        },
    ))
    await db.commit()
    return db_plan


@router.post("/assets", response_model=schemas.Asset, status_code=status.HTTP_201_CREATED)
async def create_asset(asset: schemas.AssetCreate, selected_user_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    operator = await resolve_selected_operator(db, selected_user_id)
    requested_controlled_code = (asset.controlled_code or asset.patrimonio).strip()
    existing_controlled_code = await db.execute(
        select(Asset.id).where(Asset.controlled_code == requested_controlled_code).limit(1)
    )
    # O patrimônio informado pela planilha pode se repetir. O sistema preserva
    # esse valor como legado e cria uma identificação operacional única para a
    # etiqueta QR, em vez de impedir o cadastro ou sobrescrever outro item.
    if existing_controlled_code.scalars().first():
        requested_controlled_code = f"{requested_controlled_code}-{uuid.uuid4().hex[:6].upper()}"
    db_asset = Asset(
        patrimonio=asset.patrimonio,
        type=asset.type,
        description=asset.description,
        manufacturer=asset.manufacturer,
        model=asset.model,
        serial_number=asset.serial_number,
        sector_id=asset.sector_id,
        status=asset.status,
        is_operable=asset.is_operable,
        notes=asset.notes,
        manual=asset.manual,
        ficha_tecnica=asset.ficha_tecnica,
        foto=asset.foto,
        caminho_documentos=asset.caminho_documentos,
        legacy_patrimonio=asset.legacy_patrimonio or asset.patrimonio,
        controlled_code=requested_controlled_code,
        asset_class=asset.asset_class or ("production_machine" if asset.type == "machine" else "maintainable_equipment"),
        maintenance_strategy=asset.maintenance_strategy or "preventive",
        show_in_daily_list=asset.show_in_daily_list,
        opaque_token=secrets.token_urlsafe(32),
    )
    db.add(db_asset)
    await db.flush()
    db.add(create_audit_log(
        action="asset_created",
        entity_name="asset",
        entity_id=db_asset.id,
        operator_name=operator.name if operator else "Configuração inicial do sistema",
        new_values={
            "patrimonio": db_asset.patrimonio,
            "type": db_asset.type,
            "description": db_asset.description,
            "selected_user_id": selected_user_id,
        },
    ))

    query = select(Asset).where(Asset.id == db_asset.id).options(selectinload(Asset.sector))
    result = await db.execute(query)
    return result.scalars().first()


@router.put("/assets/{asset_id:uuid}", response_model=schemas.Asset)
async def update_asset(asset_id: uuid.UUID, asset_data: schemas.AssetCreate, selected_user_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    operator = await resolve_selected_operator(db, selected_user_id)
    query = select(Asset).where(Asset.id == str(asset_id)).options(selectinload(Asset.sector))
    result = await db.execute(query)
    db_asset = result.scalars().first()
    if not db_asset:
        raise HTTPException(status_code=404, detail="Ativo não encontrado")
    old_values = {
        "patrimonio": db_asset.patrimonio,
        "type": db_asset.type,
        "description": db_asset.description,
        "status": db_asset.status,
        "is_operable": db_asset.is_operable,
    }
    db_asset.patrimonio = asset_data.patrimonio
    db_asset.type = asset_data.type
    db_asset.description = asset_data.description
    db_asset.manufacturer = asset_data.manufacturer
    db_asset.model = asset_data.model
    db_asset.serial_number = asset_data.serial_number
    db_asset.sector_id = asset_data.sector_id
    db_asset.status = asset_data.status
    db_asset.is_operable = asset_data.is_operable
    db_asset.notes = asset_data.notes
    db_asset.manual = asset_data.manual
    db_asset.ficha_tecnica = asset_data.ficha_tecnica
    db_asset.foto = asset_data.foto
    db_asset.caminho_documentos = asset_data.caminho_documentos
    db.add(create_audit_log(
        action="asset_updated",
        entity_name="asset",
        entity_id=db_asset.id,
        operator_name=operator.name if operator else None,
        old_values=old_values,
        new_values={
            "patrimonio": db_asset.patrimonio,
            "type": db_asset.type,
            "description": db_asset.description,
            "status": db_asset.status,
            "is_operable": db_asset.is_operable,
            "selected_user_id": selected_user_id,
        },
    ))

    await db.flush()
    await db.commit()
    return db_asset


@router.get("/assets/conflicts", response_model=List[schemas.Asset])
async def list_asset_conflicts(db: AsyncSession = Depends(get_db)):
    query = select(Asset).where(Asset.has_patrimonio_conflict == True).options(selectinload(Asset.sector))  # noqa: E712
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/assets/{asset_id:uuid}/resolve-conflict", response_model=schemas.Asset)
async def resolve_asset_conflict(asset_id: uuid.UUID, resolve_data: schemas.AssetConflictResolve, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Asset).where(Asset.id == str(asset_id)).options(selectinload(Asset.sector)))
    db_asset = result.scalars().first()
    if not db_asset:
        raise HTTPException(status_code=404, detail="Ativo não encontrado")

    if not db_asset.has_patrimonio_conflict:
        raise HTTPException(status_code=400, detail="Este ativo não possui conflitos de patrimônio pendentes")

    old_patrimonio = db_asset.patrimonio

    if resolve_data.resolution_type == "suggested":
        if not db_asset.conflict_patrimonio_suggested:
            raise HTTPException(status_code=400, detail="Não há código sugerido para este ativo")
        db_asset.patrimonio = db_asset.conflict_patrimonio_suggested
        db_asset.has_patrimonio_conflict = False
        db_asset.conflict_patrimonio_suggested = None
    elif resolve_data.resolution_type == "manual":
        if not resolve_data.new_patrimonio or not resolve_data.new_patrimonio.strip():
            raise HTTPException(status_code=400, detail="Novo patrimônio manual não fornecido")
        db_asset.patrimonio = resolve_data.new_patrimonio.strip()
        db_asset.has_patrimonio_conflict = False
        db_asset.conflict_patrimonio_suggested = None
    elif resolve_data.resolution_type == "keep":
        db_asset.has_patrimonio_conflict = False
        db_asset.conflict_patrimonio_suggested = None
    else:
        raise HTTPException(status_code=400, detail="Tipo de resolução inválido")

    db_audit = AuditLog(
        action="resolve_patrimonio_conflict",
        entity_name="Asset",
        entity_id=db_asset.id,
        old_values=json.dumps({"patrimonio": old_patrimonio, "has_patrimonio_conflict": True}),
        new_values=json.dumps({"patrimonio": db_asset.patrimonio, "has_patrimonio_conflict": False, "resolution_type": resolve_data.resolution_type}),
        origin="web",
        operator_name="Sistema (Resolução de Conflitos)",
    )
    db.add(db_audit)

    await db.flush()
    await db.commit()
    return db_asset


@router.post("/assets/{asset_id:uuid}/release", response_model=schemas.Asset)
async def release_asset(
    asset_id: uuid.UUID,
    release_data: schemas.AssetReleaseRequest,
    db: AsyncSession = Depends(get_db),
):
    query = select(Asset).where(Asset.id == str(asset_id))
    result = await db.execute(query)
    asset = result.scalars().first()
    if not asset:
        raise HTTPException(status_code=404, detail="Ativo não encontrado")

    issue_result = await db.execute(select(MaintenanceIssue).where(
        MaintenanceIssue.id == release_data.issue_id,
        MaintenanceIssue.asset_id == str(asset_id),
    ))
    issue = issue_result.scalars().first()
    if not issue:
        raise HTTPException(status_code=404, detail="Ocorrência não encontrada para este ativo")

    issue.status = "resolved"
    issue.resolved_at = utcnow_naive()
    issue.operator_name = release_data.operator_name
    issue.repair_description = release_data.repair_description
    issue.final_condition = release_data.final_condition
    issue.resolution_date = release_data.resolution_date
    issue.evidence_file_path = release_data.evidence_file_path

    open_issues_result = await db.execute(
        select(MaintenanceIssue).where(
            MaintenanceIssue.asset_id == str(asset_id),
            MaintenanceIssue.status == "open",
            MaintenanceIssue.is_operable_affected == True,  # noqa: E712
            MaintenanceIssue.id != release_data.issue_id,
        )
    )
    if not open_issues_result.scalars().first():
        asset.is_operable = True

    log = AuditLog(
        action="release_asset",
        entity_name="Asset",
        entity_id=str(asset_id),
        new_values=json.dumps({
            "is_operable": asset.is_operable,
            "resolved_issue_id": release_data.issue_id,
            "repair_description": release_data.repair_description,
            "final_condition": release_data.final_condition,
        }),
        operator_name=release_data.operator_name,
        origin="web",
    )
    db.add(log)

    await db.flush()
    await db.commit()

    query = select(Asset).where(Asset.id == str(asset_id)).options(selectinload(Asset.sector))
    result = await db.execute(query)
    return result.scalars().first()


@router.get("/assets/{asset_id}/meters")
async def get_asset_meters(asset_id: str, db: AsyncSession = Depends(get_db)):
    q = select(AssetMeter).where(AssetMeter.asset_id == asset_id)
    res = await db.execute(q)
    return res.scalars().all()


@router.post("/assets/{asset_id}/meters")
async def create_asset_meter(asset_id: str, meter: schemas.AssetMeterBase, db: AsyncSession = Depends(get_db)):
    db_meter = AssetMeter(
        asset_id=asset_id,
        meter_type=meter.meter_type,
        unit=meter.unit,
        current_reading=meter.current_reading,
        maintenance_interval=meter.maintenance_interval,
        next_maintenance_at=meter.current_reading + meter.maintenance_interval,
        notes=meter.notes,
    )
    db.add(db_meter)
    await db.flush()
    await db.commit()
    return db_meter


@router.post("/assets/{asset_id}/meters/{meter_id}/reading")
async def add_meter_reading(asset_id: str, meter_id: str, reading_data: schemas.AssetMeterReadingCreate, db: AsyncSession = Depends(get_db)):
    q = select(AssetMeter).where(AssetMeter.id == meter_id, AssetMeter.asset_id == asset_id)
    res = await db.execute(q)
    db_meter = res.scalars().first()
    if not db_meter:
        raise HTTPException(status_code=404, detail="Medidor não encontrado para este ativo")

    db_meter.current_reading = reading_data.reading
    db_meter.last_reading_at = utcnow_naive()
    if db_meter.current_reading >= db_meter.next_maintenance_at:
        db_meter.next_maintenance_at = db_meter.current_reading + db_meter.maintenance_interval

    await db.flush()
    await db.commit()
    return db_meter


@router.get("/assets/{asset_id}/documents")
async def get_asset_documents(asset_id: str, db: AsyncSession = Depends(get_db)):
    q = select(AssetDocumentIndex).where(AssetDocumentIndex.asset_id == asset_id)
    res = await db.execute(q)
    return res.scalars().all()


@router.post("/assets/{asset_id}/documents/link")
async def link_asset_document(asset_id: str, file_path: str, document_type: str, notes: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Arquivo local não encontrado")

    file_name = os.path.basename(file_path)
    file_ext = os.path.splitext(file_name)[1]
    file_size = os.path.getsize(file_path)

    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            sha256.update(chunk)
    file_hash = sha256.hexdigest()

    from app.document_text import extract_text

    extracted_text, extraction_method, needs_review, extraction_error = extract_text(file_path)
    final_notes = notes
    if extraction_error:
        final_notes = f"{notes or ''}\n[extração] {extraction_error}".strip()

    db_doc = AssetDocumentIndex(
        asset_id=asset_id,
        file_path=file_path,
        file_name=file_name,
        file_extension=file_ext,
        file_size=file_size,
        file_hash=file_hash,
        document_type=document_type,
        confidence="Alta" if not needs_review else "Revisar",
        extracted_text=extracted_text,
        extraction_method=extraction_method,
        needs_review=needs_review,
        notes=final_notes,
    )
    db.add(db_doc)
    await db.flush()
    await db.commit()
    return db_doc
