"""

Rotas operacionais v2 do Manutenção em Campo 1.9.2:

- Eventos de OM (linha do tempo imutável)

- Snapshots

- Confirmação de EPI

- Início e encerramento de execução

- Corretivas e retrabalhos

- Timeline por ativo

- Rodadas de manutenção

- Materiais e Compras

- Assistência técnica

- Paradas de máquina

- Notificações

- Biblioteca de checklists importados

"""



import uuid

import json

import hashlib
import io

from datetime import datetime, timedelta
from pathlib import Path

from typing import Optional, List

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, Header, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse

from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.future import select

from sqlalchemy.orm import selectinload

from app.database import get_db

from app.clock import utcnow_naive, local_today
from app.config import DATA_ROOT, REPORTS_DIR

import sqlalchemy as sa
from sqlalchemy import func
from app.models import (EpiCatalog, SafetyHazard, SafetyTask, EpiRule, EpiRuleItem, EpiRuleSource, EpiSuggestion,

    MaintenanceOrder, MaintenanceOrderItem, Asset, MaintenancePlan,

    ChecklistTemplateVersion, ChecklistItem,

    WorkOrderEvent, WorkOrderSnapshot, WorkOrderCorrection,

    EpiRequirement, EpiConfirmation,

    MaintenanceRound, RoundOrder,

    MaterialRequest, ExternalServiceRequest,

    NotificationRule, NotificationQueue,

    DowntimeRecord, ChecklistImportLog,

    ChecklistTemplate, AssetDocument, FileOrganizationTask, FileReviewItem,

)

from pydantic import BaseModel

from app.asset_file_service import (
    get_asset_file_or_404,
    resolve_internal_path,
    serialize_asset_file,
    store_asset_file,
    store_upload,
)
from app.file_limits import serialize_limits
from app.operator_service import resolve_actor_context, resolve_maintenance_executor, resolve_checklist_reviewer



router = APIRouter(prefix="/v2", tags=["1.9.2"])


def verify_quality_auth(_: Optional[str] = None) -> bool:
    """Compatibilidade: não há senha fixa, token mestre ou RBAC bloqueante."""
    return True



# ============================================================

# Helpers

# ============================================================



def _gen_id():

    return str(uuid.uuid4())


def _official_base_url(request: Request) -> str:
    lan_url_file = DATA_ROOT / "mec-backend-lan.url"
    try:
        configured = lan_url_file.read_text(encoding="utf-8").strip().rstrip("/")
        if configured.startswith("https://"):
            return configured
    except Exception:
        pass
    return str(request.base_url).rstrip("/")


def _pagination(total: int, page: int, page_size: int) -> dict:
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
    }


def _serialize_asset(asset: Asset, primary_docs: dict[str, AssetDocument] | None = None) -> dict:
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
        "sector": {"id": asset.sector.id, "name": asset.sector.name} if getattr(asset, "sector", None) else None,
        "status": asset.status,
        "is_operable": bool(asset.is_operable),
        "notes": asset.notes,
        "opaque_token": asset.opaque_token,
        "legacy_patrimonio": asset.legacy_patrimonio,
        "controlled_code": asset.controlled_code,
        "asset_class": asset.asset_class,
        "maintenance_strategy": asset.maintenance_strategy,
        "show_in_daily_list": bool(asset.show_in_daily_list),
        "manual": asset.manual,
        "ficha_tecnica": asset.ficha_tecnica,
        "foto": asset.foto,
        "caminho_documentos": asset.caminho_documentos,
        "thumbnail_url": f"/v2/files/{primary_doc.id}/thumbnail" if primary_doc and primary_doc.thumbnail_path else None,
        "primary_photo_id": primary_doc.id if primary_doc else None,
    }


def _normalize_patrimonio(value: str | None) -> str:
    return "".join(ch for ch in (value or "").upper() if ch.isalnum())


def _asset_deeplink(asset: Asset, request: Request) -> str:
    token = asset.opaque_token or asset.id
    base = str(request.base_url).rstrip("/")
    return f"{base}/ativos/{token}"


def _make_qr_png_bytes(value: str) -> bytes:
    import qrcode

    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=3)
    qr.add_data(value)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _make_asset_tag_pdf(asset: Asset, request: Request, *, sheet: bool = False) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader

    url = _asset_deeplink(asset, request)
    qr_reader = ImageReader(io.BytesIO(_make_qr_png_bytes(url)))
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=A4)
    width, height = A4
    positions = [(20 * mm, height - 70 * mm)]
    if sheet:
        positions = []
        for row in range(5):
            for col in range(2):
                positions.append((18 * mm + col * 95 * mm, height - (32 * mm + row * 52 * mm)))
    for x, y in positions:
        c.roundRect(x, y, 82 * mm, 42 * mm, 4 * mm)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(x + 5 * mm, y + 31 * mm, f"TAG {asset.controlled_code or asset.patrimonio}")
        c.setFont("Helvetica", 8)
        c.drawString(x + 5 * mm, y + 25 * mm, (asset.description or "")[:42])
        c.drawString(x + 5 * mm, y + 20 * mm, f"Tipo: {asset.type}")
        if asset.legacy_patrimonio and asset.legacy_patrimonio != asset.controlled_code:
            c.drawString(x + 5 * mm, y + 15 * mm, f"Código original: {asset.legacy_patrimonio}")
        c.drawImage(qr_reader, x + 53 * mm, y + 7 * mm, 22 * mm, 22 * mm)
        c.setFont("Helvetica", 6)
        c.drawString(x + 5 * mm, y + 7 * mm, url[:58])
    c.showPage()
    c.save()
    return out.getvalue()


@router.get("/assets/inactive")
async def list_inactive_assets(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    q: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Lista ativos cadastralmente inativos (status = 'inactive')."""
    query = select(Asset).options(selectinload(Asset.sector)).where(Asset.status == "inactive")
    if q:
        q_like = f"%{q}%"
        query = query.where(
            sa.or_(
                Asset.patrimonio.like(q_like),
                Asset.description.like(q_like),
                Asset.manufacturer.like(q_like),
                Asset.model.like(q_like),
            )
        )
    total = (await db.execute(select(sa.func.count()).select_from(query.subquery()))).scalar() or 0
    result = await db.execute(
        query.order_by(Asset.type, Asset.patrimonio)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    assets = result.scalars().all()
    asset_ids = [a.id for a in assets]
    primary_docs: dict[str, AssetDocument] = {}
    if asset_ids:
        docs_res = await db.execute(
            select(AssetDocument)
            .where(
                AssetDocument.asset_id.in_(asset_ids),
                AssetDocument.category == "photo",
                AssetDocument.is_primary_photo == True,  # noqa: E712
                sa.or_(AssetDocument.status == None, AssetDocument.status == "active"),  # noqa: E711
            )
        )
        primary_docs = {doc.asset_id: doc for doc in docs_res.scalars().all()}
    return {
        "items": [_serialize_asset(asset, primary_docs) for asset in assets],
        **_pagination(total, page, page_size),
    }


@router.get("/assets")
async def list_assets_paginated(
    type: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    sector_id: Optional[str] = None,
    is_operable: Optional[bool] = None,
    daily_only: bool = False,
    non_daily_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    query = select(Asset).options(selectinload(Asset.sector))
    if type:
        query = query.where(Asset.type == type)
    if status:
        query = query.where(Asset.status == status)
    else:
        query = query.where(Asset.status == "active")
    if sector_id:
        query = query.where(Asset.sector_id == sector_id)
    if is_operable is not None:
        query = query.where(Asset.is_operable == is_operable)
    if daily_only:
        query = query.where(Asset.show_in_daily_list == True)  # noqa: E712
    if non_daily_only:
        query = query.where(Asset.show_in_daily_list == False)  # noqa: E712
    if q:
        q_like = f"%{q}%"
        q_norm = q.replace("-", "").replace(" ", "").upper()
        query = query.where(
            sa.or_(
                Asset.patrimonio.like(q_like),
                Asset.patrimonio.like(f"%{q_norm}%"),
                Asset.description.like(q_like),
                Asset.manufacturer.like(q_like),
                Asset.model.like(q_like),
            )
        )

    total = (await db.execute(select(sa.func.count()).select_from(query.subquery()))).scalar() or 0
    result = await db.execute(
        query.order_by(Asset.type, Asset.patrimonio)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    assets = result.scalars().all()
    asset_ids = [asset.id for asset in assets]
    primary_docs: dict[str, AssetDocument] = {}
    if asset_ids:
        docs_res = await db.execute(
            select(AssetDocument)
            .where(
                AssetDocument.asset_id.in_(asset_ids),
                AssetDocument.category == "photo",
                AssetDocument.is_primary_photo == True,  # noqa: E712
                sa.or_(AssetDocument.status == None, AssetDocument.status == "active"),  # noqa: E711
            )
        )
        primary_docs = {doc.asset_id: doc for doc in docs_res.scalars().all()}
    return {
        "items": [_serialize_asset(asset, primary_docs) for asset in assets],
        **_pagination(total, page, page_size),
    }


class CreateAssetInspectionRequest(BaseModel):
    operator_name: Optional[str] = None
    selected_user_id: Optional[str] = None


@router.post("/assets/{asset_id}/execution-order")
async def create_asset_execution_order(
    asset_id: str,
    req: CreateAssetInspectionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Prepara uma nova execução rastreável para um ativo operacional.

    O tablet sempre pode iniciar a conferência de um ativo operacional. Quando
    já existe uma OM aberta, ela é reutilizada. Quando não existe, é criada
    uma nova execução com o checklist vinculado ao plano do ativo. Ela preserva
    checklist, pessoas, fotos e PDF sem cumprir ou deslocar preventivas já
    programadas para outra competência.
    """
    actor = await resolve_actor_context(db, selected_user_id=req.selected_user_id, operator_name=req.operator_name)
    asset_res = await db.execute(
        select(Asset)
        .where(Asset.id == asset_id, Asset.status == "active", Asset.show_in_daily_list == True)  # noqa: E712
        .options(selectinload(Asset.sector))
    )
    asset = asset_res.scalars().first()
    if not asset:
        raise HTTPException(status_code=404, detail="Máquina ou equipamento ativo de rotina não encontrado.")

    open_res = await db.execute(
        select(MaintenanceOrder)
        .where(
            MaintenanceOrder.asset_id == asset.id,
            MaintenanceOrder.status.in_(["scheduled", "today", "overdue", "in_progress"]),
        )
        .order_by(MaintenanceOrder.planned_date.asc(), MaintenanceOrder.friendly_number.asc())
        .limit(1)
    )
    open_order = open_res.scalars().first()
    if open_order:
        return {
            "order_id": open_order.id,
            "friendly_number": open_order.friendly_number,
            "created": False,
            "order_type": open_order.order_type,
            "message": "A OM aberta deste ativo foi selecionada.",
        }

    plan_res = await db.execute(
        select(MaintenancePlan)
        .where(
            MaintenancePlan.asset_id == asset.id,
            MaintenancePlan.is_active == True,  # noqa: E712
            MaintenancePlan.checklist_template_version_id.isnot(None),
        )
        .order_by(MaintenancePlan.recurrence_status.desc(), MaintenancePlan.name.asc())
        .limit(1)
    )
    plan = plan_res.scalars().first()
    checklist_version_id = plan.checklist_template_version_id if plan else None
    checklist_source = "checklist específico do equipamento"
    if not checklist_version_id:
        # Um ativo apresentado na lista operacional nunca deve receber um
        # checklist genérico em silêncio. Isso preserva a rastreabilidade: a
        # execução sempre aponta para o modelo próprio daquele equipamento.
        raise HTTPException(
            status_code=409,
            detail=(
                "Este ativo ainda não possui checklist específico configurado. "
                "Cadastre o modelo próprio antes de iniciar a execução."
            ),
        )

    from app.planning_service import create_order_items_from_checklist, next_friendly_number

    today = local_today()
    order = MaintenanceOrder(
        id=_gen_id(),
        friendly_number=await next_friendly_number(db),
        asset_id=asset.id,
        plan_id=plan.id if plan else None,
        checklist_version_id=checklist_version_id,
        planned_date=today,
        planned_year=None,
        planned_month=None,
        original_competence=None,
        scheduled_day_is_explicit=True,
        priority="medium",
        status="today",
        execution_status="not_started",
        needs_review=False,
        order_type="inspection",
        source_status="asset_checklist_execution",
        source_note=f"Nova execução iniciada pelo tablet usando o {checklist_source} vinculado ao ativo.",
        operator_name=actor.operator_name,
        operator_id=actor.selected_user_id,
        opaque_token=uuid.uuid4().hex,
    )
    db.add(order)
    await db.flush()
    await create_order_items_from_checklist(db, order)
    db.add(WorkOrderEvent(
        id=_gen_id(),
        order_id=order.id,
        event_type="created",
        operator_name=actor.operator_name,
        operator_id=actor.selected_user_id,
        payload=json.dumps({
            "source": "active_asset_list",
            "order_type": "inspection",
            "checklist_source": checklist_source,
            "asset_code": asset.patrimonio,
        }, ensure_ascii=False),
        created_at=utcnow_naive(),
    ))
    await db.commit()
    return {
        "order_id": order.id,
        "friendly_number": order.friendly_number,
        "created": True,
        "order_type": "inspection",
        "checklist_source": checklist_source,
        "message": "Nova execução criada para este ativo. A programação preventiva permanece inalterada.",
    }


@router.get("/assets/patrimonio-check")
async def check_asset_patrimonio(
    patrimonio: str = Query(..., min_length=1),
    exclude_asset_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    normalized = _normalize_patrimonio(patrimonio)
    if not normalized:
        raise HTTPException(status_code=400, detail="Patrimônio inválido.")

    normalized_column = sa.func.upper(
        sa.func.replace(
            sa.func.replace(
                sa.func.replace(
                    sa.func.replace(Asset.patrimonio, "-", ""),
                    " ",
                    "",
                ),
                ".",
                "",
            ),
            "/",
            "",
        )
    )
    query = (
        select(Asset)
        .options(selectinload(Asset.sector))
        .where(normalized_column == normalized)
    )
    if exclude_asset_id:
        query = query.where(Asset.id != exclude_asset_id)

    result = await db.execute(query.order_by(Asset.type, Asset.patrimonio))
    matches = result.scalars().all()
    return {
        "exists": bool(matches),
        "total": len(matches),
        "normalized_patrimonio": normalized,
        "items": [_serialize_asset(asset) for asset in matches],
    }


async def _get_asset_or_404(db: AsyncSession, asset_id: str) -> Asset:
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalars().first()
    if not asset:
        raise HTTPException(status_code=404, detail="Ativo não encontrado.")
    if not asset.opaque_token:
        asset.opaque_token = uuid.uuid4().hex
        await db.flush()
    return asset


@router.get("/assets/{asset_id}/tag.png")
async def get_asset_tag_png(asset_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    asset = await _get_asset_or_404(db, asset_id)
    png = _make_qr_png_bytes(_asset_deeplink(asset, request))
    await db.commit()
    return StreamingResponse(io.BytesIO(png), media_type="image/png", headers={"Content-Disposition": f'inline; filename="tag-{asset.patrimonio}.png"'})


@router.get("/assets/{asset_id}/tag.pdf")
async def get_asset_tag_pdf(asset_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    asset = await _get_asset_or_404(db, asset_id)
    pdf = _make_asset_tag_pdf(asset, request)
    await db.commit()
    return StreamingResponse(io.BytesIO(pdf), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="tag-{asset.patrimonio}.pdf"'})


@router.get("/assets/{asset_id}/labels.pdf")
async def get_asset_labels_pdf(asset_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    asset = await _get_asset_or_404(db, asset_id)
    pdf = _make_asset_tag_pdf(asset, request, sheet=True)
    await db.commit()
    return StreamingResponse(io.BytesIO(pdf), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="etiquetas-{asset.patrimonio}.pdf"'})


@router.get("/assets/{asset_id}/sheet.pdf")
async def get_asset_sheet_pdf(asset_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    asset = await _get_asset_or_404(db, asset_id)
    pdf = _make_asset_tag_pdf(asset, request)
    await db.commit()
    return StreamingResponse(io.BytesIO(pdf), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="ficha-{asset.patrimonio}.pdf"'})


@router.get("/orders/{order_id}/cmp.pdf")
async def get_order_cmp_pdf(
    order_id: str,
    request: Request,
    responsible: Optional[str] = None,
    execution_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Gera a folha CMP oficial em PDF, sem depender da impressão da SPA."""
    try:
        from app.pdf_generator import generate_cmp_form_pdf

        pdf = await generate_cmp_form_pdf(
            db,
            order_id,
            responsible=responsible,
            execution_date=execution_date,
            base_url=_official_base_url(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return StreamingResponse(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="cmp-{order_id}.pdf"'},
    )


@router.get("/assets/{asset_id}/files")
async def list_asset_files(
    asset_id: str,
    category: Optional[str] = None,
    include_archived: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    asset_res = await db.execute(select(Asset.id).where(Asset.id == asset_id))
    if not asset_res.scalars().first():
        raise HTTPException(status_code=404, detail="Ativo não encontrado.")

    query = select(AssetDocument).where(AssetDocument.asset_id == asset_id)
    if category:
        query = query.where(AssetDocument.category == category)
    if not include_archived:
        query = query.where(sa.or_(AssetDocument.status == None, AssetDocument.status == "active"))  # noqa: E711

    total = (await db.execute(select(sa.func.count()).select_from(query.subquery()))).scalar() or 0
    result = await db.execute(
        query.order_by(AssetDocument.is_primary_photo.desc(), AssetDocument.imported_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [serialize_asset_file(doc) for doc in result.scalars().all()]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
    }


@router.post("/assets/{asset_id}/files")
async def upload_asset_file(
    asset_id: str,
    category: Optional[str] = None,
    uploaded_by: Optional[str] = None,
    selected_user_id: Optional[str] = None,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    doc = await store_upload(
        db,
        asset_id=asset_id,
        upload=file,
        category=category,
        uploaded_by=uploaded_by,
        uploaded_by_operator_id=selected_user_id,
    )
    await db.commit()
    return serialize_asset_file(doc)


@router.post("/assets/{asset_id}/files/batch")
async def upload_asset_files_batch(
    asset_id: str,
    category: Optional[str] = None,
    uploaded_by: Optional[str] = None,
    selected_user_id: Optional[str] = None,
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    if not files:
        raise HTTPException(status_code=400, detail="Nenhum arquivo enviado.")
    items = []
    for upload in files:
        doc = await store_upload(
            db,
            asset_id=asset_id,
            upload=upload,
            category=category,
            uploaded_by=uploaded_by,
            uploaded_by_operator_id=selected_user_id,
        )
        items.append(serialize_asset_file(doc))
    await db.commit()
    return {
        "items": items,
        "total": len(items),
        "page": 1,
        "page_size": len(items),
        "total_pages": 1,
    }


@router.get("/files/{file_id}/content")
async def get_asset_file_content(file_id: str, download: bool = False, db: AsyncSession = Depends(get_db)):
    doc = await get_asset_file_or_404(db, file_id)
    if doc.status == "archived":
        raise HTTPException(status_code=404, detail="Arquivo arquivado.")
    path = resolve_internal_path(doc.internal_path or doc.file_path)
    disposition = "attachment" if download else "inline"
    return FileResponse(
        path,
        media_type=doc.mime_type or doc.file_type or "application/octet-stream",
        filename=doc.original_name or doc.name,
        content_disposition_type=disposition,
    )


@router.get("/files/{file_id}/thumbnail")
async def get_asset_file_thumbnail(file_id: str, db: AsyncSession = Depends(get_db)):
    doc = await get_asset_file_or_404(db, file_id)
    if doc.status == "archived" or not doc.thumbnail_path:
        raise HTTPException(status_code=404, detail="Miniatura não encontrada.")
    path = resolve_internal_path(doc.thumbnail_path)
    return FileResponse(path, media_type="image/jpeg")


@router.post("/files/{file_id}/set-primary")
async def set_primary_asset_photo(file_id: str, operator_name: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    doc = await get_asset_file_or_404(db, file_id)
    if (doc.category or "") != "photo":
        raise HTTPException(status_code=400, detail="Somente fotos podem ser definidas como foto principal.")
    await db.execute(
        sa.update(AssetDocument)
        .where(AssetDocument.asset_id == doc.asset_id)
        .values(is_primary_photo=False)
    )
    doc.is_primary_photo = True
    doc.status = "active"
    await db.commit()
    return serialize_asset_file(doc)


@router.post("/files/{file_id}/archive")
async def archive_asset_file(file_id: str, operator_name: str, db: AsyncSession = Depends(get_db)):
    doc = await get_asset_file_or_404(db, file_id)
    doc.status = "archived"
    doc.archived_at = utcnow_naive()
    doc.archived_by = operator_name
    doc.is_primary_photo = False
    await db.commit()
    return serialize_asset_file(doc)


@router.get("/file-limits")
async def get_file_limits():
    return serialize_limits()


@router.post("/files/{file_id}/restore")
async def restore_asset_file(file_id: str, operator_name: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    doc = await get_asset_file_or_404(db, file_id)
    doc.status = "active"
    doc.archived_at = None
    doc.archived_by = None
    if (doc.category or "") == "photo":
        primary_res = await db.execute(
            select(AssetDocument.id).where(
                AssetDocument.asset_id == doc.asset_id,
                AssetDocument.category == "photo",
                AssetDocument.is_primary_photo == True,  # noqa: E712
                sa.or_(AssetDocument.status == None, AssetDocument.status == "active"),  # noqa: E711
            )
        )
        if primary_res.scalars().first() is None:
            doc.is_primary_photo = True
    await db.commit()
    return serialize_asset_file(doc)


def _serialize_file_task(task: FileOrganizationTask) -> dict:
    return {
        "id": task.id,
        "task_type": task.task_type,
        "status": task.status,
        "source_paths": json.loads(task.source_paths_json) if task.source_paths_json else [],
        "total_files": task.total_files or 0,
        "analyzed_files": task.analyzed_files or 0,
        "imported_files": task.imported_files or 0,
        "duplicate_files": task.duplicate_files or 0,
        "review_files": task.review_files or 0,
        "error_files": task.error_files or 0,
        "message": task.message,
        "report_path": task.report_path,
        "last_file": task.last_file,
        "attempt": task.attempt or 1,
        "pause_requested_at": task.pause_requested_at.isoformat() if task.pause_requested_at else None,
        "cancel_requested_at": task.cancel_requested_at.isoformat() if task.cancel_requested_at else None,
        "checkpoint": json.loads(task.checkpoint_json) if task.checkpoint_json else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


class FileOrganizationTaskRequest(BaseModel):
    source_paths: List[str] = []
    status: str = "pending"


@router.post("/file-organization/tasks")
async def create_file_organization_task(req: FileOrganizationTaskRequest, db: AsyncSession = Depends(get_db)):
    now = utcnow_naive()
    task = FileOrganizationTask(
        id=_gen_id(),
        task_type="asset_file_organization",
        status=req.status,
        source_paths_json=json.dumps(req.source_paths, ensure_ascii=False),
        started_at=now if req.status in {"in_progress", "running"} else None,
        updated_at=now,
        message="Tarefa registrada. A organização roda em segundo plano pelo atualizador ou pelo importador incremental.",
    )
    db.add(task)
    await db.commit()
    return _serialize_file_task(task)


def _serialize_review_item(item: FileReviewItem) -> dict:
    return {
        "id": item.id,
        "task_id": item.task_id,
        "source_path": item.source_path,
        "file_name": item.file_name,
        "extension": item.extension,
        "mime_type": item.mime_type,
        "file_size": item.file_size,
        "file_hash": item.file_hash,
        "status": item.status,
        "reason_code": item.reason_code,
        "reason_message": item.reason_message,
        "possible_assets": json.loads(item.possible_assets_json) if item.possible_assets_json else [],
        "suggested_asset_id": item.suggested_asset_id,
        "selected_asset_id": item.selected_asset_id,
        "document_id": item.document_id,
        "resolved_by_operator_id": item.resolved_by_operator_id,
        "resolved_by_name": item.resolved_by_name,
        "resolved_at": item.resolved_at.isoformat() if item.resolved_at else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


@router.get("/file-organization/review-items")
async def list_file_review_items(
    status_filter: str = Query("pending", alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    query = select(FileReviewItem)
    if status_filter != "all":
        query = query.where(FileReviewItem.status == status_filter)
    total = (await db.execute(select(sa.func.count()).select_from(query.subquery()))).scalar() or 0
    result = await db.execute(
        query.order_by(FileReviewItem.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return {"items": [_serialize_review_item(item) for item in result.scalars().all()], **_pagination(total, page, page_size)}


class ResolveReviewItemRequest(BaseModel):
    asset_id: str
    operator_name: Optional[str] = None
    selected_user_id: Optional[str] = None


@router.post("/file-organization/review-items/{item_id}/resolve")
async def resolve_file_review_item(item_id: str, req: ResolveReviewItemRequest, db: AsyncSession = Depends(get_db)):
    item = await db.get(FileReviewItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item de conferência não encontrado.")
    if item.status == "resolved" and item.document_id:
        return _serialize_review_item(item)
    source_path = Path(item.source_path)
    doc = await store_asset_file(
        db,
        asset_id=req.asset_id,
        source_path=source_path,
        origin="review_resolved",
        uploaded_by=req.operator_name,
        uploaded_by_operator_id=req.selected_user_id,
        review_status="resolved",
    )
    item.status = "resolved"
    item.selected_asset_id = req.asset_id
    item.document_id = doc.id
    item.resolved_by_operator_id = req.selected_user_id
    item.resolved_by_name = req.operator_name
    item.resolved_at = utcnow_naive()
    item.updated_at = utcnow_naive()
    await db.commit()
    return _serialize_review_item(item)


@router.post("/file-organization/tasks/{task_id}/pause")
async def pause_file_organization_task(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await db.get(FileOrganizationTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa de organização não encontrada.")
    task.status = "pause_requested"
    task.pause_requested_at = utcnow_naive()
    task.updated_at = utcnow_naive()
    task.message = "Pausa solicitada. O worker interromperá no próximo checkpoint seguro."
    await db.commit()
    return _serialize_file_task(task)


@router.post("/file-organization/tasks/{task_id}/resume")
async def resume_file_organization_task(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await db.get(FileOrganizationTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa de organização não encontrada.")
    task.status = "queued"
    task.pause_requested_at = None
    task.cancel_requested_at = None
    task.attempt = (task.attempt or 1) + 1
    task.updated_at = utcnow_naive()
    task.message = "Retomada solicitada. O worker continuará a partir do checkpoint."
    await db.commit()
    return _serialize_file_task(task)


@router.post("/file-organization/tasks/{task_id}/cancel")
async def cancel_file_organization_task(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await db.get(FileOrganizationTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa de organização não encontrada.")
    task.status = "cancel_requested"
    task.cancel_requested_at = utcnow_naive()
    task.updated_at = utcnow_naive()
    task.message = "Cancelamento solicitado. O worker interromperá no próximo checkpoint seguro."
    await db.commit()
    return _serialize_file_task(task)


@router.get("/file-organization/tasks/latest")
async def get_latest_file_organization_task(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(FileOrganizationTask).order_by(FileOrganizationTask.updated_at.desc(), FileOrganizationTask.started_at.desc())
    )
    task = result.scalars().first()
    if not task:
        return {
            "id": None,
            "status": "not_started",
            "total_files": 0,
            "analyzed_files": 0,
            "imported_files": 0,
            "duplicate_files": 0,
            "review_files": 0,
            "error_files": 0,
            "message": "Nenhuma tarefa de organização registrada.",
        }
    return _serialize_file_task(task)


@router.get("/file-organization/tasks/{task_id}")
async def get_file_organization_task(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FileOrganizationTask).where(FileOrganizationTask.id == task_id))
    task = result.scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa de organização não encontrada.")
    return _serialize_file_task(task)


@router.post("/planning/generate-monthly")
async def generate_monthly_planning(horizon_months: int = Query(12, ge=1, le=24), db: AsyncSession = Depends(get_db)):
    from app.planning_service import generate_future_maintenance_orders

    summary = await generate_future_maintenance_orders(db, horizon_months=horizon_months)
    await db.commit()
    return summary



async def _get_order(order_id: str, db: AsyncSession) -> MaintenanceOrder:

    result = await db.execute(

        select(MaintenanceOrder)

        .options(

            selectinload(MaintenanceOrder.asset),

            selectinload(MaintenanceOrder.items),

            selectinload(MaintenanceOrder.evidences),

        )

        .where(MaintenanceOrder.id == order_id)

    )

    order = result.scalars().first()

    if not order:

        raise HTTPException(status_code=404, detail="OM não encontrada")

    return order



async def _add_event(
    order_id: str,
    event_type: str,
    operator: Optional[str],
    payload: dict,
    db: AsyncSession,
    operator_id: Optional[str] = None,
):

    """Adiciona evento imutável à linha do tempo da OM."""

    ev = WorkOrderEvent(

        id=_gen_id(),

        order_id=order_id,

        event_type=event_type,

        operator_name=operator,

        operator_id=operator_id,

        payload=json.dumps(payload, ensure_ascii=False, default=str),

        created_at=utcnow_naive(),

    )

    db.add(ev)



async def _ensure_snapshot(order: MaintenanceOrder, db: AsyncSession):

    """Cria snapshot imutável se ainda não existir para esta OM."""

    existing = await db.execute(

        select(WorkOrderSnapshot).where(WorkOrderSnapshot.order_id == order.id)

    )

    if existing.scalars().first():

        return



    # Montar snapshot completo

    snap_data = {

        "order_id": order.id,

        "friendly_number": order.friendly_number,

        "asset_id": order.asset_id,

        "plan_id": order.plan_id,

        "order_type": order.order_type,

        "occurrence_number": order.occurrence_number,

        "competence": order.original_competence,

        "checklist_version_id": order.checklist_version_id,

        "snapshot_at": utcnow_naive().isoformat(),

    }



    # Incluir dados do ativo

    if order.asset:

        snap_data["asset"] = {

            "patrimonio": order.asset.patrimonio,

            "description": order.asset.description,

            "type": order.asset.type,

            "manufacturer": order.asset.manufacturer,

            "model": order.asset.model,

            "serial_number": order.asset.serial_number,

            "sector_id": order.asset.sector_id,

        }



    # Incluir itens do checklist

    if order.checklist_version_id:

        items_res = await db.execute(

            select(ChecklistItem).where(ChecklistItem.version_id == order.checklist_version_id)

        )

        items = items_res.scalars().all()

        snap_data["checklist_items"] = [

            {"id": i.id, "item_number": i.item_number, "description": i.description,

             "item_type": i.item_type, "is_mandatory": i.is_mandatory, "is_critical": i.is_critical}

            for i in items

        ]



    # Incluir EPIs do plano

    if order.plan_id:

        epi_res = await db.execute(

            select(EpiRequirement).where(EpiRequirement.plan_id == order.plan_id)

        )

        epis = epi_res.scalars().all()

        snap_data["epi_requirements"] = [
            {"item_name": e.item_name, "is_mandatory": e.is_mandatory}
            for e in epis
        ]



    snap = WorkOrderSnapshot(

        id=_gen_id(),

        order_id=order.id,

        snapshot_json=json.dumps(snap_data, ensure_ascii=False, default=str),

        created_at=utcnow_naive(),

    )

    db.add(snap)





# ============================================================

# 1. Linha do tempo da OM

# ============================================================



@router.get("/orders/{order_id}")
async def get_order_detail(order_id: str, db: AsyncSession = Depends(get_db)):
    """Retorna detalhes completos de uma ordem de manutenção para a interface do operador."""
    from app import order_execution_service
    return await order_execution_service.get_order_detail(db, order_id)



@router.get("/orders/{order_id}/events")

async def get_order_events(order_id: str, db: AsyncSession = Depends(get_db)):

    """Retorna a linha do tempo completa e imutável de uma OM."""

    result = await db.execute(

        select(WorkOrderEvent)

        .where(WorkOrderEvent.order_id == order_id)

        .order_by(WorkOrderEvent.created_at)

    )

    events = result.scalars().all()

    return [

        {

            "id": e.id,

            "event_type": e.event_type,

            "operator_name": e.operator_name,

            "operator_id": e.operator_id,

            "payload": json.loads(e.payload) if e.payload else {},

            "created_at": e.created_at.isoformat() if e.created_at else None,

        }

        for e in events

    ]

    return files


# ============================================================

# 2. Snapshot imutável

# ============================================================



@router.get("/orders/{order_id}/snapshot")

async def get_order_snapshot(order_id: str, db: AsyncSession = Depends(get_db)):

    """Retorna a fotografia lógica imutável da OM."""

    result = await db.execute(

        select(WorkOrderSnapshot).where(WorkOrderSnapshot.order_id == order_id)

    )

    snap = result.scalars().first()

    if not snap:

        raise HTTPException(status_code=404, detail="Snapshot não encontrado. A OM ainda não foi iniciada.")

    return json.loads(snap.snapshot_json)





# ============================================================

# 3. Confirmação de EPI

# ============================================================






class EpiConfirmRequest(BaseModel):
    operator_name: Optional[str] = None
    selected_user_id: Optional[str] = None
    confirmed: bool = True
    missing_items: Optional[List[str]] = None
    updated_items: Optional[List[str]] = None
    save_as_default: bool = False


@router.post("/orders/{order_id}/epi-confirm")
async def confirm_epi(order_id: str, req: EpiConfirmRequest, db: AsyncSession = Depends(get_db)):
    """
    Confirma (ou bloqueia) o EPI antes de iniciar a manutenção.
    Uma única confirmação cobre todos os EPIs da lista.
    """
    from app import order_execution_service
    actor = await resolve_actor_context(db, selected_user_id=req.selected_user_id, operator_name=req.operator_name)
    return await order_execution_service.confirm_epi(
        db=db,
        order_id=order_id,
        operator_name=actor.operator_name,
        operator_id=actor.selected_user_id,
        confirmed=req.confirmed,
        missing_items=req.missing_items,
        updated_items=req.updated_items,
        save_as_default=req.save_as_default
    )


class StartOrderRequest(BaseModel):
    operator_name: Optional[str] = None
    selected_user_id: Optional[str] = None
    device_id: Optional[str] = None
    record_kind: str = "official"


@router.post("/orders/{order_id}/start")
async def start_order_execution(order_id: str, req: StartOrderRequest, db: AsyncSession = Depends(get_db)):
    """
    Inicia a execução real de uma OM.
    Cria snapshot imutável, registra data/hora/operador, muda execution_status para 'in_progress'.
    As orientações de EPI são exibidas antes da execução e a confirmação é
    registrada quando feita, mas não bloqueia a operação por decisão da empresa.
    """
    from app import order_execution_service
    actor = await resolve_actor_context(db, selected_user_id=req.selected_user_id, operator_name=req.operator_name)
    return await order_execution_service.start_order(
        db=db,
        order_id=order_id,
        operator_name=actor.operator_name,
        operator_id=actor.selected_user_id,
        device_id=req.device_id,
        record_kind=req.record_kind,
    )


class ReservationRequest(BaseModel):
    operator_name: Optional[str] = None
    selected_user_id: Optional[str] = None
    device_id: Optional[str] = None
    force: bool = False
    reason: Optional[str] = None


@router.get("/orders/{order_id}/reservation/status")
async def get_order_reservation_status(order_id: str, db: AsyncSession = Depends(get_db)):
    from app import order_execution_service
    return await order_execution_service.reservation_status(db=db, order_id=order_id)


@router.post("/orders/{order_id}/reservation/acquire")
async def acquire_order_reservation(order_id: str, req: ReservationRequest, db: AsyncSession = Depends(get_db)):
    from app import order_execution_service
    actor = await resolve_actor_context(db, selected_user_id=req.selected_user_id, operator_name=req.operator_name)
    return await order_execution_service.acquire_order_reservation(
        db=db,
        order_id=order_id,
        operator_name=actor.operator_name,
        operator_id=actor.selected_user_id,
        device_id=req.device_id,
    )


@router.post("/orders/{order_id}/reservation/renew")
async def renew_order_reservation(order_id: str, req: ReservationRequest, db: AsyncSession = Depends(get_db)):
    from app import order_execution_service
    actor = await resolve_actor_context(db, selected_user_id=req.selected_user_id, operator_name=req.operator_name)
    return await order_execution_service.renew_order_reservation(
        db=db,
        order_id=order_id,
        operator_name=actor.operator_name,
        operator_id=actor.selected_user_id,
        device_id=req.device_id,
    )


@router.post("/orders/{order_id}/reservation/heartbeat")
async def heartbeat_order_reservation(order_id: str, req: ReservationRequest, db: AsyncSession = Depends(get_db)):
    return await renew_order_reservation(order_id, req, db)


@router.post("/orders/{order_id}/reservation/takeover")
async def takeover_order_reservation(order_id: str, req: ReservationRequest, db: AsyncSession = Depends(get_db)):
    from app import order_execution_service
    actor = await resolve_actor_context(db, selected_user_id=req.selected_user_id, operator_name=req.operator_name)
    return await order_execution_service.takeover_order_reservation(
        db=db,
        order_id=order_id,
        operator_name=actor.operator_name,
        operator_id=actor.selected_user_id,
        device_id=req.device_id,
        reason=req.reason,
    )


@router.post("/orders/{order_id}/reservation/release")
async def release_order_reservation(order_id: str, req: ReservationRequest, db: AsyncSession = Depends(get_db)):
    from app import order_execution_service
    actor = await resolve_actor_context(db, selected_user_id=req.selected_user_id, operator_name=req.operator_name)
    return await order_execution_service.release_order_reservation(
        db=db,
        order_id=order_id,
        operator_name=actor.operator_name,
        operator_id=actor.selected_user_id,
        device_id=req.device_id,
        force=req.force,
        reason=req.reason,
    )

class QuickItemResponse(BaseModel):
    item_id: str
    result: str  # 'ok', 'attention', 'not_applicable'
    operator_name: Optional[str] = None
    selected_user_id: Optional[str] = None
    device_id: Optional[str] = None
    defect_found: Optional[str] = None
    corrected_in_place: Optional[bool] = None
    correction_description: Optional[str] = None
    needs_part: Optional[bool] = None
    part_name: Optional[str] = None
    can_operate: Optional[bool] = None
    not_applicable_reason: Optional[str] = None
    notes: Optional[str] = None


@router.post("/orders/{order_id}/answer-item")

async def answer_checklist_item(order_id: str, req: QuickItemResponse, db: AsyncSession = Depends(get_db)):
    """Responde e autossalva um item pelo serviço central de execução."""
    from app import order_execution_service
    actor = await resolve_actor_context(db, selected_user_id=req.selected_user_id, operator_name=req.operator_name)
    return await order_execution_service.answer_item(
        db=db,
        order_id=order_id,
        item_id=req.item_id,
        result=req.result,
        operator_name=actor.operator_name,
        operator_id=actor.selected_user_id,
        notes=req.notes,
        defect_found=req.defect_found,
        corrected_in_place=req.corrected_in_place,
        correction_description=req.correction_description,
        needs_part=req.needs_part,
        part_name=req.part_name,
        can_operate=req.can_operate,
        not_applicable_reason=req.not_applicable_reason,
        device_id=req.device_id,
    )


@router.post("/orders/{order_id}/items/{item_id}/audio")
async def attach_order_item_audio(
    order_id: str,
    item_id: str,
    file: UploadFile = File(...),
    operator_name: Optional[str] = Form(None),
    selected_user_id: Optional[str] = Form(None),
    manual_transcript: Optional[str] = Form(None),
    device_id: Optional[str] = Form(None),
    duration_sec: Optional[float] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Anexa áudio a um item da OM e, quando configurado, transcreve oficialmente."""
    from app import order_execution_service

    contents = await file.read()
    actor = await resolve_actor_context(db, selected_user_id=selected_user_id, operator_name=operator_name)
    return await order_execution_service.attach_item_audio(
        db=db,
        order_id=order_id,
        item_id=item_id,
        contents=contents,
        filename=file.filename or "audio.webm",
        content_type=file.content_type,
        operator_name=actor.operator_name,
        operator_id=actor.selected_user_id,
        manual_transcript=manual_transcript,
        device_id=device_id,
        duration_sec=duration_sec,
    )


@router.post("/orders/{order_id}/items/{item_id}/photo")
async def attach_order_item_photo(
    order_id: str,
    item_id: str,
    file: UploadFile = File(...),
    operator_name: Optional[str] = Form(None),
    selected_user_id: Optional[str] = Form(None),
    device_id: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Anexa foto real a um item da OM e registra evidência auditável."""
    from app import order_execution_service

    contents = await file.read()
    actor = await resolve_actor_context(db, selected_user_id=selected_user_id, operator_name=operator_name)
    return await order_execution_service.attach_item_photo(
        db=db,
        order_id=order_id,
        item_id=item_id,
        contents=contents,
        filename=file.filename or "foto.jpg",
        content_type=file.content_type,
        operator_name=actor.operator_name,
        operator_id=actor.selected_user_id,
        device_id=device_id,
    )





# ============================================================

# 6. Conclusão da OM (com snapshot final + PDF + SHA-256)

# ============================================================



class CompleteOrderRequest(BaseModel):
    operator_name: Optional[str] = None
    selected_user_id: Optional[str] = None
    final_condition: str = "released"
    notes: Optional[str] = None
    idempotency_key: Optional[str] = None
    device_id: Optional[str] = None
    performed_by_operator_id: Optional[str] = None
    performed_by_participant_ids: List[str] = []


class ExecutionReviewRequest(BaseModel):
    """Decisão sobre um rascunho que ficou aberto no tablet.

    Não apaga nenhuma resposta. Se era teste, a OM é cancelada com o motivo;
    se é uma execução real, ela continua disponível para ser finalizada.
    """
    decision: str
    notes: Optional[str] = None
    selected_user_id: Optional[str] = None
    operator_name: Optional[str] = None


class CmpScanReviewRequest(BaseModel):
    status: str = "draft_saved"
    selected_user_id: Optional[str] = None
    operator_name: Optional[str] = None
    corrections: Optional[dict] = None
    notes: Optional[str] = None


@router.post("/cmp/scans")
async def create_cmp_scan_endpoint(
    files: List[UploadFile] = File(...),
    order_id: Optional[str] = Form(None),
    operator_name: Optional[str] = Form(None),
    selected_user_id: Optional[str] = Form(None),
    device_id: Optional[str] = Form(None),
    expected_responsible: Optional[str] = Form(None),
    expected_execution_date: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Salva foto/PDF de CMP preenchido para conferência humana."""
    from app.cmp_scan_service import create_cmp_scan

    actor = await resolve_actor_context(db, selected_user_id=selected_user_id, operator_name=operator_name)
    record = await create_cmp_scan(
        uploads=files,
        order_id=order_id,
        operator_name=actor.operator_name,
        selected_user_id=actor.selected_user_id,
        device_id=device_id,
        expected_responsible=expected_responsible,
        expected_execution_date=expected_execution_date,
        db=db,
    )
    return {
        "message": "Imagem salva para conferência manual.",
        "item": record,
    }


@router.get("/cmp/scans")
async def list_cmp_scans_endpoint(
    order_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
):
    from app.cmp_scan_service import list_cmp_scans

    return list_cmp_scans(order_id=order_id, status=status, limit=limit)


@router.get("/cmp/scans/{scan_id}")
async def get_cmp_scan_endpoint(scan_id: str):
    from app.cmp_scan_service import get_cmp_scan

    return get_cmp_scan(scan_id)


@router.get("/cmp/scans/{scan_id}/files/{file_index}")
async def get_cmp_scan_file_endpoint(scan_id: str, file_index: int):
    from app.cmp_scan_service import get_cmp_scan, resolve_cmp_scan_file

    scan = get_cmp_scan(scan_id)
    files_meta = scan.get("files") or []
    if file_index < 0 or file_index >= len(files_meta):
        raise HTTPException(status_code=404, detail="Arquivo do CMP não encontrado.")
    file_meta = files_meta[file_index]
    path = resolve_cmp_scan_file(scan_id, file_index)
    return FileResponse(path, media_type=file_meta.get("mime_type") or "application/octet-stream")


@router.post("/cmp/scans/{scan_id}/review")
async def review_cmp_scan_endpoint(scan_id: str, req: CmpScanReviewRequest, db: AsyncSession = Depends(get_db)):
    from app.cmp_scan_service import update_cmp_scan_review

    actor = await resolve_actor_context(db, selected_user_id=req.selected_user_id, operator_name=req.operator_name)
    return update_cmp_scan_review(
        scan_id,
        status=req.status,
        selected_user_id=actor.selected_user_id,
        operator_name=actor.operator_name,
        corrections=req.corrections,
        notes=req.notes,
    )

@router.post("/orders/{order_id}/complete")
async def complete_order(order_id: str, req: CompleteOrderRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """
    Encerra uma OM:
    """
    from app import order_execution_service
    actor = await resolve_actor_context(db, selected_user_id=req.selected_user_id, operator_name=req.operator_name)
    performer = None
    if req.performed_by_operator_id:
        performer = await resolve_maintenance_executor(db, req.performed_by_operator_id)
    elif actor.selected_user_id:
        # O aplicativo oficial sempre envia o executante. Mantemos apenas a
        # compatibilidade de integrações antigas sem identidade selecionada.
        raise HTTPException(status_code=400, detail="Selecione quem realizou a manutenção antes de finalizar.")
    participant_ids = list(dict.fromkeys(person_id for person_id in req.performed_by_participant_ids if person_id and person_id != req.performed_by_operator_id))
    participants = []
    for participant_id in participant_ids:
        participant = await resolve_maintenance_executor(db, participant_id)
        participants.append({"id": participant.id, "name": participant.name})
    response = await order_execution_service.complete_order(
        db=db,
        order_id=order_id,
        operator_name=actor.operator_name,
        operator_id=actor.selected_user_id,
        final_condition=req.final_condition,
        notes=req.notes,
        idempotency_key=req.idempotency_key,
        device_id=req.device_id,
        performed_by_name=performer.name if performer else actor.operator_name,
        performed_by_operator_id=performer.id if performer else actor.selected_user_id,
        performed_by_participants=participants,
    )
    from app.dossier_service import sync_order_in_background
    background_tasks.add_task(sync_order_in_background, order_id)
    return response


@router.get("/execution/drafts")
async def list_execution_drafts(
    alert_from_days: int = Query(2, ge=0, le=30),
    db: AsyncSession = Depends(get_db),
):
    """Lista todos os rascunhos, inclusive os iniciados hoje.

    A rota fica fora de /orders/{id}; assim nunca é confundida com um ID de OM.
    """
    result = await db.execute(
        select(MaintenanceOrder)
        .options(selectinload(MaintenanceOrder.asset).selectinload(Asset.sector), selectinload(MaintenanceOrder.items))
        .where(MaintenanceOrder.execution_status == "in_progress")
        .order_by(MaintenanceOrder.started_at.asc())
    )
    now = utcnow_naive()
    rows = []
    for order in result.scalars().all():
        age_days = max(0, (now - order.started_at).days) if order.started_at else 0
        rows.append({
            "id": order.id, "friendly_number": order.friendly_number, "asset_id": order.asset_id,
            "asset_code": getattr(order.asset, "patrimonio", None) or getattr(order.asset, "controlled_code", None),
            "asset_description": getattr(order.asset, "description", None),
            "asset_sector": getattr(getattr(order.asset, "sector", None), "name", None),
            "started_at": order.started_at.isoformat() if order.started_at else None,
            "age_days": age_days, "requires_attention": age_days >= alert_from_days,
            "answered_items": sum(1 for item in order.items if item.status and item.status != "unanswered"),
            "total_items": len(order.items), "started_by": order.operator_name,
        })
    return {"items": rows, "count": len(rows), "attention_count": sum(1 for row in rows if row["requires_attention"])}


@router.get("/orders/execution-pending")
async def list_execution_pending(
    min_age_days: int = Query(2, ge=0, le=30),
    db: AsyncSession = Depends(get_db),
):
    """Fila simples de execuções abertas que Camila/Rafael precisam revisar."""
    cutoff = utcnow_naive() - timedelta(days=min_age_days)
    result = await db.execute(
        select(MaintenanceOrder)
        .options(selectinload(MaintenanceOrder.asset), selectinload(MaintenanceOrder.items))
        .where(MaintenanceOrder.execution_status == "in_progress", MaintenanceOrder.started_at.is_not(None), MaintenanceOrder.started_at <= cutoff)
        .order_by(MaintenanceOrder.started_at.asc())
    )
    now = utcnow_naive()
    rows = []
    for order in result.scalars().all():
        age_days = max(0, (now - order.started_at).days) if order.started_at else 0
        rows.append({
            "id": order.id,
            "friendly_number": order.friendly_number,
            "asset_id": order.asset_id,
            "asset_code": getattr(order.asset, "patrimonio", None) or getattr(order.asset, "controlled_code", None),
            "asset_description": getattr(order.asset, "description", None),
            "asset_sector": getattr(getattr(order.asset, "sector", None), "name", None),
            "started_at": order.started_at.isoformat() if order.started_at else None,
            "age_days": age_days,
            "answered_items": sum(1 for item in order.items if item.status and item.status != "unanswered"),
            "total_items": len(order.items),
            "started_by": order.operator_name,
            "review_decision": order.review_decision,
        })
    return {"items": rows, "min_age_days": min_age_days, "count": len(rows)}


@router.post("/orders/{order_id}/execution-review")
async def review_execution_pending(order_id: str, req: ExecutionReviewRequest, db: AsyncSession = Depends(get_db)):
    if req.decision not in {"continue", "test_draft", "not_performed"}:
        raise HTTPException(status_code=400, detail="Escolha continuar, rascunho de teste ou não realizada.")
    reviewer = await resolve_checklist_reviewer(db, req.selected_user_id or "")
    order = await _get_order(order_id, db)
    if order.execution_status != "in_progress":
        raise HTTPException(status_code=409, detail="Esta manutenção não está mais em andamento.")
    order.review_decision = req.decision
    order.review_operator = reviewer.name
    order.review_at = utcnow_naive()
    order.review_notes = (req.notes or "").strip() or None
    order.needs_review = req.decision == "continue"
    if req.decision in {"test_draft", "not_performed"}:
        order.execution_status = "cancelled"
        order.status = "cancelled"
        order.record_kind = "demo_test" if req.decision == "test_draft" else "not_performed"
        order.record_kind_reason = order.review_notes or ("Teste/demonstração do aplicativo" if req.decision == "test_draft" else "Checklist iniciado, mas manutenção não realizada")
        order.record_kind_classified_at = order.review_at
        order.record_kind_classified_by = reviewer.name
        order.reservation_operator = None
        order.reservation_device_id = None
        order.reservation_started_at = None
        order.reservation_expires_at = None
    await _add_event(order.id, "execution_reviewed", reviewer.name, {
        "decision": req.decision, "notes": order.review_notes,
        "reviewed_at": order.review_at.isoformat(),
        "preserved_answers": sum(1 for item in order.items if item.status and item.status != "unanswered"),
    }, db, operator_id=reviewer.id)
    await db.commit()
    label = {"continue": "mantida para continuidade", "test_draft": "marcada como teste", "not_performed": "marcada como não realizada"}[req.decision]
    return {"order_id": order.id, "decision": req.decision, "status": order.status, "message": f"Manutenção {label}. Nenhum registro foi apagado."}


@router.get("/orders/{order_id}/final-pdf")
async def get_final_order_pdf(order_id: str, db: AsyncSession = Depends(get_db)):
    """Entrega somente o PDF imutável gerado no fechamento, sem cache antigo."""
    order = (await db.execute(select(MaintenanceOrder).where(MaintenanceOrder.id == order_id))).scalars().first()
    if not order:
        raise HTTPException(status_code=404, detail="OM não encontrada.")
    if order.execution_status != "completed" or not order.final_pdf_path:
        raise HTTPException(status_code=404, detail="O PDF final ainda não foi gerado; conclua a manutenção primeiro.")
    path = Path(order.final_pdf_path)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="O arquivo final da manutenção não está disponível localmente.")
    response = FileResponse(path, media_type="application/pdf", filename=path.name)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["ETag"] = f'"{order.final_pdf_sha256 or order.final_sha256 or order.id}"'
    return response

class OrderCorrectionRequest(BaseModel):
    field_name: str
    old_value: Optional[str] = None
    new_value: str
    reason: str
    operator_name: Optional[str] = None
    selected_user_id: Optional[str] = None


@router.post("/orders/{order_id}/correct")

async def correct_completed_order(order_id: str, req: OrderCorrectionRequest, db: AsyncSession = Depends(get_db)):

    """

    Cria registro auditado de correção posterior a uma OM concluída.

    Não altera silenciosamente — preserva o valor anterior.

    """

    order = await _get_order(order_id, db)
    reviewer = await resolve_checklist_reviewer(db, req.selected_user_id or "")
    if order.execution_status != "completed":
        raise HTTPException(status_code=409, detail="Só é possível adicionar correção depois da conclusão da manutenção.")



    correction = WorkOrderCorrection(

        id=_gen_id(),

        order_id=order_id,

        field_name=req.field_name,

        old_value=req.old_value,

        new_value=req.new_value,

        reason=req.reason,

        operator_name=reviewer.name,

        operator_id=reviewer.id,

        created_at=utcnow_naive(),

    )

    db.add(correction)



    # Atualizar a revisão e incrementar o número de revisões

    order.final_revision = (order.final_revision or 1) + 1



    await db.flush()
    correction.document_revision = order.final_revision
    try:
        from app.pdf_generator import generate_correction_addendum_pdf
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"OM_{order.friendly_number:04d}_ADENDO_v{order.final_revision}.pdf"
        path = REPORTS_DIR / filename
        pdf = generate_correction_addendum_pdf(order, correction)
        path.write_bytes(pdf.getvalue())
        correction.document_path = str(path)
        correction.document_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Não foi possível gerar o adendo de correção: {exc}") from exc

    await _add_event(order_id, "corrected", reviewer.name, {

        "field": req.field_name,

        "old_value": req.old_value,

        "new_value": req.new_value,

        "reason": req.reason,

        "revision": order.final_revision,
        "addendum_path": correction.document_path,
        "addendum_sha256": correction.document_sha256,

    }, db, operator_id=reviewer.id)



    await db.commit()
    from app.dossier_service import queue_order_dossier, sync_job
    job = await queue_order_dossier(db, order_id, requested_by=reviewer.name, requested_by_operator_id=reviewer.id)
    await db.commit()
    dossier_sync = await sync_job(db, job)



    return {

        "correction_id": correction.id,

        "field_name": req.field_name,

        "new_revision": order.final_revision,

        "addendum_pdf_path": correction.document_path,
        "addendum_sha256": correction.document_sha256,
        "dossier_sync": dossier_sync,

        "message": f"Correção registrada. OM agora na revisão {order.final_revision}.",

    }


@router.get("/orders/{order_id}/corrections")
async def list_order_corrections(order_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(WorkOrderCorrection)
        .where(WorkOrderCorrection.order_id == order_id)
        .order_by(WorkOrderCorrection.document_revision.asc(), WorkOrderCorrection.created_at.asc())
    )
    return {"items": [{
        "id": row.id, "field_name": row.field_name, "old_value": row.old_value,
        "new_value": row.new_value, "reason": row.reason, "operator_name": row.operator_name,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "revision": row.document_revision, "document_sha256": row.document_sha256,
        "has_document": bool(row.document_path),
    } for row in result.scalars().all()]}


@router.get("/orders/{order_id}/corrections/{correction_id}/pdf")
async def get_correction_addendum_pdf(order_id: str, correction_id: str, db: AsyncSession = Depends(get_db)):
    correction = (await db.execute(select(WorkOrderCorrection).where(WorkOrderCorrection.id == correction_id, WorkOrderCorrection.order_id == order_id))).scalars().first()
    if not correction or not correction.document_path:
        raise HTTPException(status_code=404, detail="Adendo de correção não encontrado.")
    path = Path(correction.document_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Arquivo do adendo não está disponível localmente.")
    response = FileResponse(path, media_type="application/pdf", filename=path.name)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response





# ============================================================

# 8. Criar corretiva a partir de preventiva

# ============================================================



class CreateCorrectiveRequest(BaseModel):

    description: str

    operator_name: Optional[str] = None

    selected_user_id: Optional[str] = None

    priority: str = "medium"

    is_machine_stopped: bool = False



@router.post("/orders/{order_id}/create-corrective")

async def create_corrective_from_preventive(order_id: str, req: CreateCorrectiveRequest, db: AsyncSession = Depends(get_db)):

    """

    Cria uma nova OM corretiva relacionada à OM preventiva.

    A preventiva permanece intacta com seu número e histórico.

    A corretiva recebe um novo número global.

    """

    parent_order = await _get_order(order_id, db)
    actor = await resolve_actor_context(db, selected_user_id=req.selected_user_id, operator_name=req.operator_name)



    from app.planning_service import next_friendly_number

    next_num = await next_friendly_number(db)



    now = utcnow_naive()

    today = local_today()



    new_order = MaintenanceOrder(

        id=_gen_id(),

        friendly_number=next_num,

        asset_id=parent_order.asset_id,

        plan_id=None,

        checklist_version_id=parent_order.checklist_version_id,

        planned_date=today,

        planned_year=None,

        planned_month=None,

        original_competence=None,

        scheduled_day_is_explicit=True,

        priority=req.priority,

        status="today",

        execution_status="not_started",

        operator_name=actor.operator_name,

        operator_id=actor.selected_user_id,

        notes=req.description,

        # Campos de inteligência operacional.

        order_type="corrective",

        parent_work_order_id=parent_order.id,

        relation_type="corrective_from_preventive",

        machine_stopped=req.is_machine_stopped,

        machine_stopped_at=now if req.is_machine_stopped else None,

    )

    db.add(new_order)

    await db.flush()



    # Registrar evento na preventiva pai

    await _add_event(order_id, "corrective_created", actor.operator_name, {

        "corrective_order_id": new_order.id,

        "corrective_number": next_num,

    }, db, operator_id=actor.selected_user_id)



    # Registrar evento na corretiva nova

    await _add_event(new_order.id, "created", actor.operator_name, {

        "from_order_id": order_id,

        "from_number": parent_order.friendly_number,

        "relation": "corrective_from_preventive",

        "description": req.description,

    }, db, operator_id=actor.selected_user_id)



    # Se máquina parada, registrar parada

    if req.is_machine_stopped:

        downtime = DowntimeRecord(

            id=_gen_id(),

            asset_id=parent_order.asset_id,

            order_id=new_order.id,

            started_at=now,

            reason=req.description,

        )

        db.add(downtime)

        parent_order.asset.is_operable = False



    await db.flush()

    await db.commit()



    return {

        "corrective_order_id": new_order.id,

        "corrective_number": next_num,

        "parent_order_id": order_id,

        "parent_number": parent_order.friendly_number,

        "message": f"Corretiva OM {next_num} criada. Vinculada à preventiva OM {parent_order.friendly_number}.",

    }





# ============================================================

# 9. Criar retrabalho

# ============================================================



class CreateReworkRequest(BaseModel):

    description: str

    operator_name: Optional[str] = None

    selected_user_id: Optional[str] = None

    priority: str = "medium"



@router.post("/orders/{order_id}/create-rework")

async def create_rework(order_id: str, req: CreateReworkRequest, db: AsyncSession = Depends(get_db)):

    """

    Cria uma nova OM de retrabalho.

    A OM original permanece imutável com seu número e histórico.

    O retrabalho recebe um novo número global.

    """

    parent_order = await _get_order(order_id, db)
    actor = await resolve_actor_context(db, selected_user_id=req.selected_user_id, operator_name=req.operator_name)



    from app.planning_service import next_friendly_number

    next_num = await next_friendly_number(db)



    today = local_today()

    now = utcnow_naive()



    new_order = MaintenanceOrder(

        id=_gen_id(),

        friendly_number=next_num,

        asset_id=parent_order.asset_id,

        plan_id=None,

        checklist_version_id=parent_order.checklist_version_id,

        planned_date=today,

        planned_year=None,

        planned_month=None,

        original_competence=None,

        scheduled_day_is_explicit=True,

        priority=req.priority,

        status="today",

        execution_status="not_started",

        operator_name=actor.operator_name,

        operator_id=actor.selected_user_id,

        notes=req.description,

        order_type="rework",

        parent_work_order_id=parent_order.id,

        relation_type="rework",

    )

    db.add(new_order)

    await db.flush()



    await _add_event(order_id, "rework_created", actor.operator_name, {

        "rework_order_id": new_order.id,

        "rework_number": next_num,

    }, db, operator_id=actor.selected_user_id)



    await _add_event(new_order.id, "created", actor.operator_name, {

        "from_order_id": order_id,

        "from_number": parent_order.friendly_number,

        "relation": "rework",

        "description": req.description,

    }, db, operator_id=actor.selected_user_id)



    await db.flush()

    await db.commit()



    return {

        "rework_order_id": new_order.id,

        "rework_number": next_num,

        "parent_order_id": order_id,

        "parent_number": parent_order.friendly_number,

        "message": f"Retrabalho OM {next_num} criado. Vinculado à OM {parent_order.friendly_number}.",

    }





# ============================================================

# 10. Timeline por ativo

# ============================================================



@router.get("/assets/{asset_id}/timeline")

async def get_asset_timeline(

    asset_id: str,

    order_type: Optional[str] = None,

    period_start: Optional[str] = None,

    period_end: Optional[str] = None,

    db: AsyncSession = Depends(get_db)

):

    """

    Retorna o histórico completo de OMs por ativo (linha do tempo).

    Nunca mostra apenas a última execução.

    """

    query = select(MaintenanceOrder).where(MaintenanceOrder.asset_id == asset_id)



    if order_type:

        query = query.where(MaintenanceOrder.order_type == order_type)



    query = query.order_by(MaintenanceOrder.planned_year.desc(), MaintenanceOrder.planned_month.desc())



    result = await db.execute(query.options(selectinload(MaintenanceOrder.events)))

    orders = result.scalars().all()



    months = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",

              "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]



    def competence_label(o):

        if o.original_competence:

            parts = o.original_competence.split('-')

            if len(parts) == 2:

                try:

                    m = int(parts[1])

                    y = parts[0]

                    return f"{months[m-1].capitalize()}/{y}"

                except Exception:

                    pass

        return None



    return {

        "asset_id": asset_id,

        "total": len(orders),

        "orders": [

            {

                "id": o.id,

                "friendly_number": o.friendly_number,

                "order_type": o.order_type or "preventive",

                "status": o.status,

                "execution_status": o.execution_status,

                "competence": competence_label(o),

                "original_competence": o.original_competence,

                "planned_year": o.planned_year,

                "planned_month": o.planned_month,

                "started_at": o.started_at.isoformat() if o.started_at else None,

                "completed_at": o.completed_at.isoformat() if o.completed_at else None,

                "operator_name": o.operator_name,

                "final_condition": o.final_condition,

                "parent_work_order_id": o.parent_work_order_id,

                "relation_type": o.relation_type,

                "occurrence_number": o.occurrence_number,

                "epi_confirmed": o.epi_confirmed,

                "machine_stopped": o.machine_stopped,

                "events_count": len(o.events) if o.events else 0,

            }

            for o in orders

        ]

    }





# ============================================================

# 11. Rodadas de manutenção

# ============================================================



class CreateRoundRequest(BaseModel):

    name: str

    plan_reference: Optional[str] = None

    competence: Optional[str] = None  # YYYY-MM

    order_ids: List[str] = []

    created_by: Optional[str] = None

    notes: Optional[str] = None



@router.post("/rounds")

async def create_round(req: CreateRoundRequest, db: AsyncSession = Depends(get_db)):

    """

    Cria uma rodada de manutenção que agrupa múltiplas OMs individuais.

    Cada ativo mantém sua OM própria com histórico independente.

    """

    now = utcnow_naive()



    round_id = _gen_id()

    new_round = MaintenanceRound(

        id=round_id,

        name=req.name,

        plan_reference=req.plan_reference,

        competence=req.competence,

        status="in_progress",

        created_by=req.created_by,

        created_at=now,

        notes=req.notes,

    )

    db.add(new_round)

    await db.flush()



    # Vincular OMs à rodada

    for seq, order_id in enumerate(req.order_ids, 1):

        link = RoundOrder(

            id=_gen_id(),

            round_id=round_id,

            order_id=order_id,

            sequence=seq,

        )

        db.add(link)

        # Atualizar round_id na OM

        order_res = await db.execute(select(MaintenanceOrder).where(MaintenanceOrder.id == order_id))

        o = order_res.scalars().first()

        if o:

            o.round_id = round_id



    await db.flush()

    await db.commit()



    return {

        "round_id": round_id,

        "id": round_id,

        "name": req.name,

        "orders_linked": len(req.order_ids),

        "total_orders": len(req.order_ids),

        "message": f"Rodada criada com {len(req.order_ids)} OMs.",

    }



@router.get("/rounds/{round_id}")

async def get_round(round_id: str, db: AsyncSession = Depends(get_db)):

    """Retorna detalhes de uma rodada de manutenção com progresso."""

    result = await db.execute(

        select(MaintenanceRound)

        .options(selectinload(MaintenanceRound.round_orders))

        .where(MaintenanceRound.id == round_id)

    )

    rnd = result.scalars().first()

    if not rnd:

        raise HTTPException(status_code=404, detail="Rodada não encontrada")



    orders_data = []

    completed_count = 0

    for ro in rnd.round_orders:

        order_res = await db.execute(

            select(MaintenanceOrder)

            .options(selectinload(MaintenanceOrder.asset))

            .where(MaintenanceOrder.id == ro.order_id)

        )

        o = order_res.scalars().first()

        if o:

            if o.execution_status == 'completed':

                completed_count += 1

            orders_data.append({

                "sequence": ro.sequence,

                "order_id": o.id,

                "friendly_number": o.friendly_number,

                "asset_id": o.asset_id,

                "asset_patrimonio": o.asset.patrimonio if o.asset else None,

                "asset_description": o.asset.description if o.asset else None,

                "status": o.status,

                "execution_status": o.execution_status,

            })



    return {

        "id": rnd.id,

        "name": rnd.name,

        "plan_reference": rnd.plan_reference,

        "competence": rnd.competence,

        "status": rnd.status,

        "created_by": rnd.created_by,

        "created_at": rnd.created_at.isoformat() if rnd.created_at else None,

        "total_orders": len(orders_data),

        "completed_orders": completed_count,

        "progress_pct": int(completed_count / len(orders_data) * 100) if orders_data else 0,

        "orders": sorted(orders_data, key=lambda x: x.get("sequence") or 0),

    }



@router.get("/rounds")

async def list_rounds(db: AsyncSession = Depends(get_db)):

    """Lista todas as rodadas de manutenção."""

    result = await db.execute(

        select(MaintenanceRound).order_by(MaintenanceRound.created_at.desc())

    )

    rounds = result.scalars().all()

    out = []
    for r in rounds:
        count_res = await db.execute(sa.text("SELECT COUNT(*) FROM round_orders WHERE round_id = :rid"), {"rid": r.id})
        total_orders = count_res.scalar_one()
        out.append({
            "id": r.id,
            "name": r.name,
            "status": r.status,
            "competence": r.competence,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "total_orders": total_orders,
        })
    return out





# ============================================================

# 12. Solicitações de material/Compras

# ============================================================



class MaterialRequestCreate(BaseModel):

    order_id: Optional[str] = None

    asset_id: Optional[str] = None

    item_name: str

    quantity: Optional[float] = None

    unit: Optional[str] = None

    priority: str = "medium"

    requested_by: Optional[str] = None

    selected_user_id: Optional[str] = None

    defect_description: Optional[str] = None

    notes: Optional[str] = None



@router.post("/material-requests")

async def create_material_request(req: MaterialRequestCreate, db: AsyncSession = Depends(get_db)):

    """

    Cria solicitação de material/peça para Compras.

    Reaproveita dados da OM automaticamente (ativo, patrimônio, setor, prioridade).

    """

    actor = await resolve_actor_context(db, selected_user_id=req.selected_user_id, operator_name=req.requested_by)

    mr = MaterialRequest(

        id=_gen_id(),

        order_id=req.order_id,

        asset_id=req.asset_id,

        item_name=req.item_name,

        quantity=req.quantity,

        unit=req.unit,

        priority=req.priority,

        status="requested",

        requested_by=actor.operator_name,

        requested_at=utcnow_naive(),

        defect_description=req.defect_description,

        notes=req.notes,

    )

    db.add(mr)



    # Registrar evento na OM se houver vínculo

    if req.order_id:

        await _add_event(req.order_id, "part_requested", actor.operator_name, {

            "item_name": req.item_name,

            "quantity": req.quantity,

            "unit": req.unit,

        }, db, operator_id=actor.selected_user_id)



    await db.flush()

    await db.commit()



    return {"id": mr.id, "item_name": mr.item_name, "status": "requested", "message": "Solicitação criada."}



@router.get("/material-requests")

async def list_material_requests(order_id: Optional[str] = None, asset_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):

    query = select(MaterialRequest).order_by(MaterialRequest.requested_at.desc())

    if order_id:

        query = query.where(MaterialRequest.order_id == order_id)

    if asset_id:

        query = query.where(MaterialRequest.asset_id == asset_id)

    result = await db.execute(query)

    items = result.scalars().all()

    return [{"id": m.id, "item_name": m.item_name, "status": m.status, "priority": m.priority, "order_id": m.order_id, "requested_at": m.requested_at.isoformat() if m.requested_at else None} for m in items]



@router.patch("/material-requests/{mr_id}/status")

async def update_material_request_status(mr_id: str, status_val: str, db: AsyncSession = Depends(get_db)):

    result = await db.execute(select(MaterialRequest).where(MaterialRequest.id == mr_id))

    mr = result.scalars().first()

    if not mr:

        raise HTTPException(status_code=404, detail="Solicitação não encontrada")

    mr.status = status_val

    await db.flush()

    await db.commit()

    return {"id": mr_id, "status": status_val}





# ============================================================

# 13. Paradas de máquina

# ============================================================



class StartDowntimeRequest(BaseModel):

    asset_id: str

    order_id: Optional[str] = None

    reason: str

    operator_name: Optional[str] = None

    selected_user_id: Optional[str] = None



class EndDowntimeRequest(BaseModel):

    released_by: Optional[str] = None

    selected_user_id: Optional[str] = None

    condition_after: str = "released"

    notes: Optional[str] = None



@router.post("/downtime/start")

async def start_downtime(req: StartDowntimeRequest, db: AsyncSession = Depends(get_db)):

    """Registra início de parada de máquina."""

    now = utcnow_naive()
    actor = await resolve_actor_context(db, selected_user_id=req.selected_user_id, operator_name=req.operator_name)

    dr = DowntimeRecord(

        id=_gen_id(),

        asset_id=req.asset_id,

        order_id=req.order_id,

        started_at=now,

        reason=req.reason,

    )

    db.add(dr)



    # Marcar ativo como parado

    asset_res = await db.execute(select(Asset).where(Asset.id == req.asset_id))

    asset = asset_res.scalars().first()

    if asset:

        asset.is_operable = False

        asset.status = "parada"



    if req.order_id:

        order_res = await db.execute(select(MaintenanceOrder).where(MaintenanceOrder.id == req.order_id))

        o = order_res.scalars().first()

        if o:

            o.machine_stopped = True

            o.machine_stopped_at = now

        await _add_event(req.order_id, "machine_stopped", actor.operator_name, {"reason": req.reason}, db, operator_id=actor.selected_user_id)



    await db.flush()

    await db.commit()



    return {"downtime_id": dr.id, "started_at": now.isoformat(), "message": "Parada registrada."}



@router.post("/downtime/{downtime_id}/end")

async def end_downtime(downtime_id: str, req: EndDowntimeRequest, db: AsyncSession = Depends(get_db)):

    """Registra fim de parada de máquina. O histórico de parada é preservado."""

    result = await db.execute(select(DowntimeRecord).where(DowntimeRecord.id == downtime_id))

    dr = result.scalars().first()

    if not dr:

        raise HTTPException(status_code=404, detail="Registro de parada não encontrado")



    now = utcnow_naive()
    actor = await resolve_actor_context(db, selected_user_id=req.selected_user_id, operator_name=req.released_by)

    dr.ended_at = now

    dr.released_by = actor.operator_name

    dr.condition_after = req.condition_after

    dr.notes = req.notes



    if dr.started_at:

        dr.duration_mins = int((now - dr.started_at).total_seconds() / 60)



    # Liberar ativo

    asset_res = await db.execute(select(Asset).where(Asset.id == dr.asset_id))

    asset = asset_res.scalars().first()

    if asset:

        asset.is_operable = True

        asset.status = "active"



    # Registrar liberação na OM se houver

    if dr.order_id:

        order_res = await db.execute(select(MaintenanceOrder).where(MaintenanceOrder.id == dr.order_id))

        o = order_res.scalars().first()

        if o:

            o.machine_released_at = now

        await _add_event(dr.order_id, "machine_released", actor.operator_name, {

            "condition": req.condition_after,

            "duration_mins": dr.duration_mins,

        }, db, operator_id=actor.selected_user_id)



    await db.flush()

    await db.commit()



    return {

        "downtime_id": downtime_id,

        "ended_at": now.isoformat(),

        "duration_mins": dr.duration_mins,

        "condition_after": req.condition_after,

        "message": "Máquina liberada. Histórico de parada preservado.",

    }



@router.get("/downtime")

async def list_downtime(asset_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):

    """Lista paradas de máquina. Paradas encerradas são sempre preservadas."""

    query = select(DowntimeRecord).order_by(DowntimeRecord.started_at.desc())

    if asset_id:

        query = query.where(DowntimeRecord.asset_id == asset_id)

    result = await db.execute(query)

    items = result.scalars().all()

    files = [

        {

            "id": d.id, "asset_id": d.asset_id, "order_id": d.order_id,

            "started_at": d.started_at.isoformat() if d.started_at else None,

            "ended_at": d.ended_at.isoformat() if d.ended_at else None,

            "duration_mins": d.duration_mins,

            "reason": d.reason,

            "condition_after": d.condition_after,

            "is_active": d.ended_at is None,

        }

        for d in items

    ]

    return files


# ============================================================

# 14. Fila de notificações

# ============================================================



@router.get("/notifications/queue")

async def get_notification_queue(status_filter: Optional[str] = None, db: AsyncSession = Depends(get_db)):

    """Lista a fila de notificações (idempotente, com status de envio)."""

    query = select(NotificationQueue).order_by(NotificationQueue.created_at.desc())

    if status_filter:

        query = query.where(NotificationQueue.status == status_filter)

    result = await db.execute(query)

    items = result.scalars().all()

    return [

        {

            "id": n.id, "event_type": n.event_type, "recipient": n.recipient,

            "subject": n.subject, "status": n.status, "attempt_count": n.attempt_count,

            "sent_at": n.sent_at.isoformat() if n.sent_at else None,

            "error_msg": n.error_msg,

            "created_at": n.created_at.isoformat() if n.created_at else None,

        }

        for n in items

    ]



@router.get("/decisions/queue")
async def get_decision_queue(limit: int = 100, db: AsyncSession = Depends(get_db)):
    """Fila operacional única para itens que precisam de decisão humana."""
    max_limit = max(1, min(limit, 300))
    items: list[dict[str, Any]] = []

    async def table_exists(name: str) -> bool:
        return bool((await db.execute(sa.text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"), {"name": name})).scalar())

    if await table_exists("maintenance_orders"):
        rows = (await db.execute(sa.text("""
            SELECT id, friendly_number, status, execution_status, final_condition, completed_at, started_at, planned_date
              FROM maintenance_orders
             WHERE status IN ('completed_with_issues','blocked','waiting_material')
                OR execution_status IN ('blocked','conflict')
                OR final_condition IN ('stopped','released_with_attention')
             ORDER BY COALESCE(completed_at, started_at, planned_date) DESC
             LIMIT :limit
        """), {"limit": max_limit})).mappings().all()
        for row in rows:
            items.append({
                "kind": "maintenance_order",
                "priority": "high" if row.get("final_condition") == "stopped" else "normal",
                "entity_id": row["id"],
                "title": f"OM {row.get('friendly_number') or row['id']} precisa de decisão",
                "status": row.get("status") or row.get("execution_status"),
                "created_at": row.get("completed_at") or row.get("started_at") or row.get("planned_date"),
            })

    if await table_exists("material_requests"):
        rows = (await db.execute(sa.text("""
            SELECT id, order_id, item_name, status, requested_at
              FROM material_requests
             WHERE status IN ('requested','pending','waiting_approval','waiting_material','in_quotation')
             ORDER BY requested_at DESC
             LIMIT :limit
        """), {"limit": max_limit})).mappings().all()
        for row in rows:
            items.append({
                "kind": "material",
                "priority": "normal",
                "entity_id": row["id"],
                "order_id": row.get("order_id"),
                "title": f"Material pendente: {row.get('item_name') or row['id']}",
                "status": row.get("status"),
                "created_at": row.get("requested_at"),
            })

    if await table_exists("file_review_items"):
        rows = (await db.execute(sa.text("""
            SELECT id, file_name, status, reason_message, created_at
              FROM file_review_items
             WHERE status IN ('pending','conflict','needs_review')
             ORDER BY created_at DESC
             LIMIT :limit
        """), {"limit": max_limit})).mappings().all()
        for row in rows:
            items.append({
                "kind": "document_review",
                "priority": "normal",
                "entity_id": row["id"],
                "title": f"Documento para revisar: {row.get('file_name') or row['id']}",
                "status": row.get("status"),
                "message": row.get("reason_message"),
                "created_at": row.get("created_at"),
            })

    if await table_exists("document_ocr_jobs"):
        rows = (await db.execute(sa.text("""
            SELECT id, source_kind, source_id, status, error_message, created_at
              FROM document_ocr_jobs
             WHERE status IN ('pending','needs_review','failed')
             ORDER BY created_at DESC
             LIMIT :limit
        """), {"limit": max_limit})).mappings().all()
        for row in rows:
            items.append({
                "kind": "ocr",
                "priority": "high" if row.get("status") == "failed" else "normal",
                "entity_id": row["id"],
                "source_kind": row.get("source_kind"),
                "source_id": row.get("source_id"),
                "title": "OCR/transcrição documental para revisão",
                "status": row.get("status"),
                "message": row.get("error_message"),
                "created_at": row.get("created_at"),
            })

    if await table_exists("offline_sync_operations"):
        rows = (await db.execute(sa.text("""
            SELECT client_op_id, operation_type, order_id, status, last_error, received_at
              FROM offline_sync_operations
             WHERE status IN ('pending','conflict','failed','rejected')
             ORDER BY received_at DESC
             LIMIT :limit
        """), {"limit": max_limit})).mappings().all()
        for row in rows:
            items.append({
                "kind": "offline_sync",
                "priority": "high" if row.get("status") in {"conflict", "failed"} else "normal",
                "entity_id": row["client_op_id"],
                "order_id": row.get("order_id"),
                "title": f"Sincronização pendente: {row.get('operation_type')}",
                "status": row.get("status"),
                "message": row.get("last_error"),
                "created_at": row.get("received_at"),
            })

    if await table_exists("assets"):
        rows = (await db.execute(sa.text("""
            SELECT id, patrimonio, description
              FROM assets
             WHERE has_patrimonio_conflict = 1
             ORDER BY patrimonio ASC
             LIMIT :limit
        """), {"limit": max_limit})).mappings().all()
        accepted_duplicates = {"M-91", "E13", "E14", "M-89", "M-90", "M-92"}
        for row in rows:
            items.append({
                "kind": "asset_conflict",
                "priority": "accepted" if row.get("patrimonio") in accepted_duplicates else "normal",
                "entity_id": row["id"],
                "title": f"Conflito de patrimônio: {row.get('patrimonio')}",
                "message": row.get("description"),
                "status": "conflict",
                "created_at": None,
            })

    items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return {"total": len(items[:max_limit]), "items": items[:max_limit]}



@router.post("/notifications/retry/{notification_id}")

async def retry_notification(notification_id: str, db: AsyncSession = Depends(get_db)):

    """Retentar envio de notificação com falha."""

    result = await db.execute(select(NotificationQueue).where(NotificationQueue.id == notification_id))

    n = result.scalars().first()

    if not n:

        raise HTTPException(status_code=404, detail="Notificação não encontrada")



    if n.status == 'sent':

        return {"message": "Notificação já foi enviada.", "status": "sent"}



    n.status = "pending"

    n.attempt_count = (n.attempt_count or 0)

    n.last_attempt_at = None

    n.error_msg = None



    await db.flush()

    await db.commit()



    return {"message": "Notificação re-enfileirada.", "id": notification_id}





# ============================================================

# 15. Biblioteca de checklists importados

# ============================================================



def _serialize_cmp_template(template: ChecklistTemplate, plan_count: int = 0, order_count: int = 0) -> dict:
    versions = sorted(template.versions or [], key=lambda version: version.version or 0, reverse=True)
    return {
        "id": template.id,
        "name": template.name,
        "code_reference": template.code_reference,
        "asset_type": template.asset_type,
        "description": getattr(template, "description", None),
        "plans_count": plan_count,
        "orders_count": order_count,
        "latest_version": versions[0].version if versions else None,
        "versions": [
            {
                "id": version.id,
                "version": version.version,
                "source_document": version.source_document,
                "source_document_hash": version.source_document_hash,
                "created_at": version.created_at.isoformat() if version.created_at else None,
                "valid_from": version.valid_from.isoformat() if version.valid_from else None,
                "valid_until": version.valid_until.isoformat() if version.valid_until else None,
                "items_count": len(version.items or []),
                "items": [
                    {
                        "id": item.id,
                        "item_number": item.item_number,
                        "description": item.description,
                        "item_type": item.item_type,
                        "is_mandatory": item.is_mandatory,
                        "is_critical": item.is_critical,
                        "allow_photo": item.allow_photo,
                        "suggested_materials": item.suggested_materials,
                    }
                    for item in sorted(version.items or [], key=lambda item: item.item_number or "")
                ],
            }
            for version in versions
        ],
    }


@router.get("/cmp/templates")
async def get_cmp_templates(db: AsyncSession = Depends(get_db)):
    """Retorna os modelos CMP versionados usados pelo planejamento e execução."""
    result = await db.execute(
        select(ChecklistTemplate).options(
            selectinload(ChecklistTemplate.versions).selectinload(ChecklistTemplateVersion.items)
        )
    )
    templates = sorted(result.scalars().unique().all(), key=lambda item: item.name or "")

    plan_counts = {}
    plan_rows = await db.execute(
        select(ChecklistTemplateVersion.template_id, func.count(MaintenancePlan.id))
        .join(ChecklistTemplateVersion, MaintenancePlan.checklist_template_version_id == ChecklistTemplateVersion.id)
        .group_by(ChecklistTemplateVersion.template_id)
    )
    for template_id, count in plan_rows.all():
        plan_counts[template_id] = count

    order_counts = {}
    order_rows = await db.execute(
        select(ChecklistTemplateVersion.template_id, func.count(MaintenanceOrder.id))
        .join(ChecklistTemplateVersion, MaintenanceOrder.checklist_version_id == ChecklistTemplateVersion.id)
        .group_by(ChecklistTemplateVersion.template_id)
    )
    for template_id, count in order_rows.all():
        order_counts[template_id] = count

    items = [
        _serialize_cmp_template(
            template,
            plan_count=plan_counts.get(template.id, 0),
            order_count=order_counts.get(template.id, 0),
        )
        for template in templates
    ]
    return {
        "total": len(items),
        "templates": items,
        "models": len(items),
        "versions": sum(len(item["versions"]) for item in items),
        "items": sum(version["items_count"] for item in items for version in item["versions"]),
    }


@router.get("/checklist-library")

async def get_checklist_library(

    status_filter: Optional[str] = None,

    db: AsyncSession = Depends(get_db)

):

    """Retorna a biblioteca de checklists importados da pasta de documentos."""

    query = select(ChecklistImportLog).order_by(ChecklistImportLog.imported_at.desc())

    if status_filter:

        query = query.where(ChecklistImportLog.status == status_filter)

    result = await db.execute(query)

    items = result.scalars().all()

    files = [
        {
            "id": c.id,
            "file_name": c.file_name,
            "rq_cmp_number": c.rq_cmp_number,
            "year": c.year,
            "title": c.title,
            "status": c.status,
            "classification": c.classification,
            "items_count": c.items_count,
            "epi_count": c.epi_count,
            "conflicts": json.loads(c.conflicts_json) if c.conflicts_json else [],
            "checklist_template_id": c.checklist_template_id,
            "imported_at": c.imported_at.isoformat() if c.imported_at else None,
            "notes": c.notes,
        }
        for c in items
    ]
    status_counts = {}
    for item in files:
        status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1
    models_res = await db.execute(select(ChecklistTemplate))
    versions_res = await db.execute(select(ChecklistTemplateVersion))
    return {
        "files_analyzed": len(files),
        "imported": status_counts.get("imported", 0),
        "duplicates": status_counts.get("skipped", 0),
        "conflicts": status_counts.get("conflict", 0),
        "errors": status_counts.get("error", 0),
        "documents_to_review": status_counts.get("review", 0),
        "models": len(models_res.scalars().all()),
        "versions": len(versions_res.scalars().all()),
        "status_counts": status_counts,
        "files": files,
        "items": files,
        "total": len(files),
        "page": 1,
        "page_size": len(files) or 20,
        "total_pages": 1,
    }



@router.get("/checklist-library/{import_id}/conflicts")

async def get_import_conflicts(import_id: str, db: AsyncSession = Depends(get_db)):

    """Retorna detalhes dos conflitos de um checklist importado para revisão da Qualidade."""

    result = await db.execute(select(ChecklistImportLog).where(ChecklistImportLog.id == import_id))

    item = result.scalars().first()

    if not item:

        raise HTTPException(status_code=404, detail="Registro de importação não encontrado")



    conflicts = json.loads(item.conflicts_json) if item.conflicts_json else []



    return {

        "id": item.id,

        "file_name": item.file_name,

        "status": item.status,

        "conflicts": conflicts,

        "suggestion": "O conteúdo interno tem peso maior que o nome do arquivo. Confirme ou corrija manualmente.",

    }





# ============================================================

# 16. EPIs por plano

# ============================================================



class EpiRequirementCreate(BaseModel):

    plan_id: Optional[str] = None

    checklist_template_id: Optional[str] = None

    item_name: str

    ca_number: Optional[str] = None

    validity: Optional[str] = None

    is_mandatory: bool = True

    added_by: str



@router.get("/plans/{plan_id}/epi-requirements")

async def get_plan_epi_requirements(plan_id: str, db: AsyncSession = Depends(get_db)):

    """Retorna a lista de EPIs obrigatórios para um plano de manutenção."""

    result = await db.execute(

        select(EpiRequirement).where(EpiRequirement.plan_id == plan_id)

    )

    epis = result.scalars().all()

    return [

        {"id": e.id, "item_name": e.item_name, "ca_number": e.ca_number,

         "is_mandatory": e.is_mandatory, "validity": e.validity}

        for e in epis

    ]



@router.post("/plans/{plan_id}/epi-requirements")

async def add_epi_requirement(plan_id: str, req: EpiRequirementCreate, db: AsyncSession = Depends(get_db)):

    """Adiciona EPI obrigatório a um plano (deve ser aprovado pela Qualidade/SST)."""

    epi = EpiRequirement(

        id=_gen_id(),

        plan_id=plan_id,

        checklist_template_id=req.checklist_template_id,

        item_name=req.item_name,

        ca_number=req.ca_number,

        validity=req.validity,

        is_mandatory=req.is_mandatory,

        added_by=req.added_by,

        added_at=utcnow_naive(),

    )

    db.add(epi)

    await db.flush()

    await db.commit()

    return {"id": epi.id, "item_name": epi.item_name, "message": "EPI adicionado."}



@router.delete("/plans/{plan_id}/epi-requirements/{requirement_id}")
async def delete_plan_epi_requirement(plan_id: str, requirement_id: str, db: AsyncSession = Depends(get_db)):
    """Remove um requisito de EPI de um plano de manutenção."""
    result = await db.execute(
        select(EpiRequirement).where(EpiRequirement.plan_id == plan_id, EpiRequirement.id == requirement_id)
    )
    epi = result.scalars().first()
    if not epi:
        raise HTTPException(status_code=404, detail="Requisito de EPI não encontrado para este plano.")
    await db.delete(epi)
    await db.commit()
    return {"message": "Requisito de EPI removido."}



# ============================================================

# 17. Assistência técnica externa

# ============================================================



class ExternalServiceRequestCreate(BaseModel):

    order_id: Optional[str] = None

    asset_id: Optional[str] = None

    service_type: str

    supplier: str

    requested_by: str

    notes: Optional[str] = None



@router.post("/external-services")

async def create_external_service(req: ExternalServiceRequestCreate, db: AsyncSession = Depends(get_db)):

    """Cria uma solicitação de assistência técnica externa."""

    es = ExternalServiceRequest(

        id=_gen_id(),

        order_id=req.order_id,

        asset_id=req.asset_id,

        service_type=req.service_type,

        supplier=req.supplier,

        status="requested",

        requested_by=req.requested_by,

        requested_at=utcnow_naive(),

        notes=req.notes,

    )

    db.add(es)



    if req.order_id:

        await _add_event(req.order_id, "external_service_requested", req.requested_by, {

            "supplier": req.supplier,

            "service_type": req.service_type,

        }, db)



    await db.flush()

    await db.commit()



    return {"id": es.id, "service_type": es.service_type, "status": es.status, "message": "Solicitação de assistência externa criada."}



@router.get("/external-services")

async def list_external_services(order_id: Optional[str] = None, asset_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):

    """Lista as solicitações de assistência externa."""

    query = select(ExternalServiceRequest).order_by(ExternalServiceRequest.requested_at.desc())

    if order_id:

        query = query.where(ExternalServiceRequest.order_id == order_id)

    if asset_id:

        query = query.where(ExternalServiceRequest.asset_id == asset_id)

    result = await db.execute(query)

    items = result.scalars().all()

    return [

        {

            "id": s.id,

            "order_id": s.order_id,

            "asset_id": s.asset_id,

            "service_type": s.service_type,

            "supplier": s.supplier,

            "status": s.status,

            "requested_by": s.requested_by,

            "requested_at": s.requested_at.isoformat() if s.requested_at else None,

            "scheduled_at": s.scheduled_at.isoformat() if s.scheduled_at else None,

            "completed_at": s.completed_at.isoformat() if s.completed_at else None,

            "notes": s.notes,

        }

        for s in items

    ]



@router.patch("/external-services/{es_id}/status")

async def update_external_service_status(es_id: str, status_val: str, db: AsyncSession = Depends(get_db)):

    """Atualiza o status da assistência externa."""

    result = await db.execute(select(ExternalServiceRequest).where(ExternalServiceRequest.id == es_id))

    es = result.scalars().first()

    if not es:

        raise HTTPException(status_code=404, detail="Solicitação de assistência técnica não encontrada")

    es.status = status_val

    if status_val == "completed":

        es.completed_at = utcnow_naive()

    elif status_val == "scheduled":

        es.scheduled_at = utcnow_naive()



    await db.flush()

    await db.commit()

    return {"id": es_id, "status": status_val}

# ============================================================
# 15. CONFIGURAÇÃO INTELIGENTE, QUALIDADE E SST
# ============================================================

class EpiCatalogCreateRequest(BaseModel):
    name: str
    category: str
    description: Optional[str] = None
    exige_ca: bool = True
    observacoes: Optional[str] = None
    ativo: bool = True

class EpiCatalogUpdateRequest(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    exige_ca: Optional[bool] = None
    observacoes: Optional[str] = None
    ativo: Optional[bool] = None

class EpiRuleItemInput(BaseModel):
    epi_catalog_id: str
    obrigatoriedade: str  # 'mandatory', 'recommended', 'optional'
    observacao: Optional[str] = None
    sequencia: int = 0

class EpiRuleCreateRequest(BaseModel):
    name: str
    scope: str  # 'plant', 'sector', 'asset_type', 'asset_family', 'manufacturer_model', 'checklist_template', 'plan', 'asset'
    scope_id: str
    rule_items: List[EpiRuleItemInput]

class EpiRuleUpdateRequest(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None  # 'draft', 'approved', 'revoked'
    rule_items: Optional[List[EpiRuleItemInput]] = None

class ApproveBatchRequest(BaseModel):
    suggestion_ids: List[str]
    operator_name: str

@router.get("/quality/epi-catalog")
async def get_epi_catalog(db: AsyncSession = Depends(get_db)):
    """Retorna o catálogo completo de EPIs cadastrados."""
    res = await db.execute(select(EpiCatalog).order_by(EpiCatalog.name))
    return res.scalars().all()


@router.get("/quality/epi-missing")
async def get_epi_missing_report(db: AsyncSession = Depends(get_db)):
    """Lista planos/OMs que ainda não possuem EPI definido."""
    from app.rules_engine import resolve_epis_for_plan

    plan_rows = await db.execute(
        select(MaintenancePlan, Asset)
        .join(Asset, MaintenancePlan.asset_id == Asset.id)
        .outerjoin(EpiRequirement, EpiRequirement.plan_id == MaintenancePlan.id)
        .where(MaintenancePlan.is_active == True)  # noqa: E712
        .group_by(MaintenancePlan.id)
        .having(func.count(EpiRequirement.id) == 0)
        .order_by(Asset.patrimonio, MaintenancePlan.name)
    )
    plans = []
    plan_ids = []
    for plan, asset in plan_rows.all():
        resolved_epis = await resolve_epis_for_plan(db, plan.id)
        if resolved_epis:
            continue
        plan_ids.append(plan.id)
        plans.append({
            "plan_id": plan.id,
            "plan_name": plan.name,
            "asset_id": asset.id,
            "patrimonio": asset.patrimonio,
            "asset_description": asset.description,
            "status": "pending_epi_registration",
        })

    orders = []
    if plan_ids:
        order_rows = await db.execute(
            select(MaintenanceOrder, Asset)
            .join(Asset, MaintenanceOrder.asset_id == Asset.id)
            .where(
                MaintenanceOrder.plan_id.in_(plan_ids),
                MaintenanceOrder.status.in_(["scheduled", "today", "overdue", "in_progress"]),
            )
            .order_by(MaintenanceOrder.friendly_number)
        )
        orders = [
            {
                "order_id": order.id,
                "friendly_number": order.friendly_number,
                "plan_id": order.plan_id,
                "asset_id": asset.id,
                "patrimonio": asset.patrimonio,
                "asset_description": asset.description,
                "status": order.status,
            }
            for order, asset in order_rows.all()
        ]

    return {
        "status": "needs_registration" if plans else "ok",
        "plans_without_epi": len(plans),
        "open_orders_without_epi": len(orders),
        "plans": plans,
        "orders": orders,
    }

@router.post("/quality/epi-catalog")
async def create_epi_catalog_item(req: EpiCatalogCreateRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Cadastra um novo EPI no catálogo global."""
    if not verify_quality_auth(request.headers.get("X-ManutencaoEmCampo-Auth-Token")):
        raise HTTPException(status_code=403, detail="Não autorizado. Confirmação administrativa inválida.")
    item = EpiCatalog(
        id=_gen_id(),
        name=req.name,
        category=req.category,
        description=req.description,
        exige_ca=req.exige_ca,
        observacoes=req.observacoes,
        ativo=req.ativo
    )
    db.add(item)
    await db.flush()
    await db.commit()
    return item

@router.put("/quality/epi-catalog/{item_id}")
async def update_epi_catalog_item(item_id: str, req: EpiCatalogUpdateRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Atualiza as propriedades de um EPI do catálogo."""
    if not verify_quality_auth(request.headers.get("X-ManutencaoEmCampo-Auth-Token")):
        raise HTTPException(status_code=403, detail="Não autorizado. Confirmação administrativa inválida.")
    res = await db.execute(select(EpiCatalog).where(EpiCatalog.id == item_id))
    item = res.scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="Item do catálogo não encontrado.")

    if req.name is not None:
        item.name = req.name
    if req.category is not None:
        item.category = req.category
    if req.description is not None:
        item.description = req.description
    if req.exige_ca is not None:
        item.exige_ca = req.exige_ca
    if req.observacoes is not None:
        item.observacoes = req.observacoes
    if req.ativo is not None:
        item.ativo = req.ativo

    await db.flush()
    await db.commit()
    return item

@router.get("/quality/rules")
async def get_epi_rules(scope: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    """Retorna a lista de todas as regras de segurança cadastradas."""
    query = select(EpiRule).options(selectinload(EpiRule.rule_items).selectinload(EpiRuleItem.epi_catalog))
    if scope:
        query = query.where(EpiRule.scope == scope)
    res = await db.execute(query)
    return res.scalars().all()

@router.post("/quality/rules")
async def create_epi_rule(req: EpiRuleCreateRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Cria uma nova regra de segurança para um determinado escopo."""
    if not verify_quality_auth(request.headers.get("X-ManutencaoEmCampo-Auth-Token")):
        raise HTTPException(status_code=403, detail="Não autorizado. Confirmação administrativa inválida.")
    rule = EpiRule(
        id=_gen_id(),
        name=req.name,
        scope=req.scope,
        scope_id=req.scope_id,
        status='draft',  # Inicia como rascunho
        version=1,
        created_at=utcnow_naive(),
        confidence='high'
    )
    db.add(rule)

    for idx, item in enumerate(req.rule_items):
        rule_item = EpiRuleItem(
            id=_gen_id(),
            rule_id=rule.id,
            epi_catalog_id=item.epi_catalog_id,
            obrigatoriedade=item.obrigatoriedade,
            observacao=item.observacao,
            sequencia=item.sequencia or idx
        )
        db.add(rule_item)

    await db.flush()
    await db.commit()
    return rule

@router.put("/quality/rules/{rule_id}")
async def update_epi_rule(rule_id: str, req: EpiRuleUpdateRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Atualiza ou aprova uma regra de segurança (SST)."""
    if not verify_quality_auth(request.headers.get("X-ManutencaoEmCampo-Auth-Token")):
        raise HTTPException(status_code=403, detail="Não autorizado. Confirmação administrativa inválida.")
    res = await db.execute(select(EpiRule).where(EpiRule.id == rule_id).options(selectinload(EpiRule.rule_items)))
    rule = res.scalars().first()
    if not rule:
        raise HTTPException(status_code=404, detail="Regra de EPI não encontrada.")

    if req.name is not None:
        rule.name = req.name
    if req.status is not None:
        rule.status = req.status
        if req.status == 'approved':
            await sync_approved_rule_to_legacy(db, rule)

    if req.rule_items is not None:
        await db.execute(sa.text("DELETE FROM epi_rule_items WHERE rule_id = :rid"), {"rid": rule.id})
        for idx, item in enumerate(req.rule_items):
            rule_item = EpiRuleItem(
                id=_gen_id(),
                rule_id=rule.id,
                epi_catalog_id=item.epi_catalog_id,
                obrigatoriedade=item.obrigatoriedade,
                observacao=item.observacao,
                sequencia=item.sequencia or idx
            )
            db.add(rule_item)

    await db.flush()
    await db.commit()
    return rule

@router.delete("/quality/rules/{rule_id}")
async def delete_epi_rule(rule_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Remove uma regra de segurança."""
    if not verify_quality_auth(request.headers.get("X-ManutencaoEmCampo-Auth-Token")):
        raise HTTPException(status_code=403, detail="Não autorizado. Confirmação administrativa inválida.")
    res = await db.execute(select(EpiRule).where(EpiRule.id == rule_id))
    rule = res.scalars().first()
    if not rule:
        raise HTTPException(status_code=404, detail="Regra não encontrada.")
    await db.delete(rule)
    await db.commit()
    return {"message": "Regra removida com sucesso."}

@router.get("/quality/suggestions")
async def get_epi_suggestions(status_val: str = 'suggested', db: AsyncSession = Depends(get_db)):
    """Retorna todas as sugestões de segurança geradas pelo motor."""
    res = await db.execute(
        select(EpiSuggestion)
        .where(EpiSuggestion.status == status_val)
        .options(selectinload(EpiSuggestion.plan).selectinload(MaintenancePlan.asset))
    )
    suggestions = res.scalars().all()

    out = []
    for s in suggestions:
        out.append({
            "id": s.id,
            "plan_id": s.plan_id,
            "plan_name": s.plan.name if s.plan else "N/A",
            "asset_patrimonio": s.plan.asset.patrimonio if (s.plan and s.plan.asset) else "N/A",
            "asset_description": s.plan.asset.description if (s.plan and s.plan.asset) else "N/A",
            "items": json.loads(s.items_json) if s.items_json else [],
            "hazards": json.loads(s.hazards_json) if s.hazards_json else [],
            "confidence": s.confidence,
            "evidence": json.loads(s.evidence_json) if s.evidence_json else [],
            "similarity_score": s.similarity_score,
            "created_at": s.created_at.isoformat() if s.created_at else None
        })
    return out

@router.post("/quality/suggestions/approve-batch")
async def approve_suggestions_batch(req: ApproveBatchRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Aprova sugestões de segurança em lote, convertendo-as em regras vigentes."""
    # Validar que a pessoa existe. Na regra vigente todos têm o mesmo acesso.
    from app.models import Operator
    op_res = await db.execute(select(Operator).where(Operator.name == req.operator_name))
    if not op_res.scalars().first():
        raise HTTPException(status_code=400, detail="Operador não cadastrado.")

    res = await db.execute(
        select(EpiSuggestion)
        .where(sa.and_(EpiSuggestion.id.in_(req.suggestion_ids), EpiSuggestion.status == 'suggested'))
        .options(selectinload(EpiSuggestion.plan))
    )
    suggestions = res.scalars().all()

    count = 0
    for s in suggestions:
        s.status = 'approved'
        s.decision = 'approved'
        s.decided_by = req.operator_name
        s.decided_at = utcnow_naive()

        # Obter documento de origem da versão do checklist do plano, se houver
        source_path = None
        source_hash = None
        if s.plan and s.plan.checklist_template_version_id:
            ver_res = await db.execute(
                select(ChecklistTemplateVersion).where(ChecklistTemplateVersion.id == s.plan.checklist_template_version_id)
            )
            ver = ver_res.scalars().first()
            if ver:
                source_path = ver.source_document
                source_hash = ver.source_document_hash

        if not source_path and s.plan:
            source_path = s.plan.source_document
            source_hash = s.plan.source_document_hash

        if not source_path:
            source_path = "checklists/manual_pgr"
        if not source_hash:
            source_hash = "d3b07384d113edec49eaa6238ad5ff00" # fallback default hash

        rule_id = _gen_id()
        rule = EpiRule(
            id=rule_id,
            name=f"Regra Sugerida para Plano {s.plan.name if s.plan else s.plan_id}",
            scope='plan',
            scope_id=s.plan_id,
            status='approved',
            version=1,
            created_at=utcnow_naive(),
            confidence=s.confidence,
            approved_by=req.operator_name,
            approved_at=utcnow_naive()
        )
        db.add(rule)

        # Criar fonte de evidência com todos os campos reais
        source = EpiRuleSource(
            id=_gen_id(),
            rule_id=rule_id,
            source_type='ai_suggestion',
            source_path=source_path,
            source_hash=source_hash,
            reference=f"Recomendação de EPI para {s.plan.name if s.plan else s.plan_id}",
            extracted_text=s.evidence_json if s.evidence_json else "Análise do motor de regras.",
            evidence_strength=s.confidence
        )
        db.add(source)

        items = json.loads(s.items_json) if s.items_json else []
        for idx, it in enumerate(items):
            rule_item = EpiRuleItem(
                id=_gen_id(),
                rule_id=rule_id,
                epi_catalog_id=it['epi_catalog_id'],
                obrigatoriedade='mandatory' if it.get('is_mandatory', True) else 'recommended',
                sequencia=idx
            )
            db.add(rule_item)

        count += 1
        await sync_approved_rule_to_legacy(db, rule)

    await db.flush()
    await db.commit()
    return {"message": f"{count} sugestões aprovadas e convertidas em regras com sucesso."}

@router.post("/quality/suggestions/generate")
async def force_generate_suggestions(request: Request, db: AsyncSession = Depends(get_db)):
    """Força o motor de regras a recalcular e sugerir EPIs para todos os planos ativos."""
    if not verify_quality_auth(request.headers.get("X-ManutencaoEmCampo-Auth-Token")):
        raise HTTPException(status_code=403, detail="Não autorizado. Confirmação administrativa inválida.")
    plans_res = await db.execute(select(MaintenancePlan).where(MaintenancePlan.is_active == 1))
    plans = plans_res.scalars().all()

    count = 0
    from app.rules_engine import generate_epi_suggestions_for_plan
    for p in plans:
        s = await generate_epi_suggestions_for_plan(db, p.id)
        if s:
            count += 1

    return {"message": f"Análise concluída. {count} sugestões de segurança foram geradas."}

@router.get("/quality/inactive-candidates")
async def get_inactive_candidates(db: AsyncSession = Depends(get_db)):
    """Retorna ativos com suspeita de inatividade operacional para auditoria de SST."""
    from app.rules_engine import detect_candidate_inactive_assets
    return await detect_candidate_inactive_assets(db)

@router.get("/quality/smart-routes")
async def get_smart_routes(competence: str, db: AsyncSession = Depends(get_db)):
    """Agrupa ordens da competência em rotas de trabalho otimizadas por proximidade operacional."""
    from app.rules_engine import group_orders_in_smart_routes
    return await group_orders_in_smart_routes(db, competence)

@router.get("/quality/plan-suggestions/{plan_id}")
async def get_plan_suggestions(plan_id: str, db: AsyncSession = Depends(get_db)):
    """Retorna as sugestões completas de periodicidade, duração e materiais para o plano."""
    from app.rules_engine import suggest_periodicity_and_duration, suggest_materials_for_plan
    dur_suggestions = await suggest_periodicity_and_duration(db, plan_id)
    mat_suggestions = await suggest_materials_for_plan(db, plan_id)
    return {
        "periodicity_duration": dur_suggestions,
        "materials": mat_suggestions
    }

async def sync_approved_rule_to_legacy(db: AsyncSession, rule: EpiRule):
    """
    Sincroniza uma regra aprovada com a tabela legacy epi_requirements.
    Garante retrocompatibilidade absoluta.
    """
    plan_ids = []
    if rule.scope == 'plan':
        plan_ids.append(rule.scope_id)
    elif rule.scope == 'asset':
        plans_res = await db.execute(select(MaintenancePlan.id).where(MaintenancePlan.asset_id == rule.scope_id))
        plan_ids.extend([r[0] for r in plans_res.fetchall()])
    elif rule.scope == 'checklist_template':
        from app.models import ChecklistTemplateVersion
        plans_res = await db.execute(
            select(MaintenancePlan.id)
            .join(ChecklistTemplateVersion, MaintenancePlan.checklist_template_version_id == ChecklistTemplateVersion.id)
            .where(ChecklistTemplateVersion.template_id == rule.scope_id)
        )
        plan_ids.extend([r[0] for r in plans_res.fetchall()])
    elif rule.scope in ('plant', 'sector', 'asset_type', 'asset_family'):
        query = select(MaintenancePlan.id).join(Asset, MaintenancePlan.asset_id == Asset.id)
        if rule.scope == 'sector':
            query = query.where(Asset.sector_id == rule.scope_id)
        elif rule.scope in ('asset_type', 'asset_family'):
            query = query.where(Asset.type == rule.scope_id)
        plans_res = await db.execute(query)
        plan_ids.extend([r[0] for r in plans_res.fetchall()])

    from app.rules_engine import resolve_epis_for_plan
    for pid in plan_ids:
        await db.execute(sa.text("DELETE FROM epi_requirements WHERE plan_id = :pid"), {"pid": pid})
        resolved_epis = await resolve_epis_for_plan(db, pid)
        for idx, epi in enumerate(resolved_epis):
            req = EpiRequirement(
                id=str(uuid.uuid4()),
                plan_id=pid,
                item_name=epi['item_name'],
                ca_number=None,
                is_mandatory=epi['is_mandatory'],
                added_by="SST SmartSync",
                added_at=utcnow_naive()
            )
            db.add(req)
