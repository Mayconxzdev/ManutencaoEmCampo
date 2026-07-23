import hashlib
import json
import os
import secrets
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from dateutil.relativedelta import relativedelta
from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.clock import local_today, utcnow_naive
from app.config import REPORTS_DIR, UPLOADS_DIR
from app.file_limits import AUDIO_EXTENSIONS, category_for_name, get_limit_for_name
from app.models import (
    Asset,
    ChecklistImportLog,
    ChecklistItem,
    ChecklistTemplate,
    ChecklistTemplateVersion,
    DowntimeRecord,
    EpiConfirmation,
    EpiRequirement,
    MaintenanceMaterial,
    MaintenanceEvidence,
    MaintenanceIssue,
    MaintenanceOrder,
    MaintenanceOrderItem,
    MaintenancePlan,
    MaterialRequest,
    RoundOrder,
    WorkOrderEvent,
    WorkOrderSnapshot,
)
from app.planning_service import create_order_items_from_checklist, next_friendly_number
from app.upload_service import validate_and_save_image


def gen_id() -> str:
    return str(uuid.uuid4())


def iso(value: Any) -> Optional[str]:
    return value.isoformat() if value else None


def _text(value: Optional[str]) -> str:
    return (value or "").strip()


RESERVATION_TTL_MINUTES = 45


def _normalize_mime(content_type: Optional[str]) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def _detect_audio_extension(contents: bytes) -> str:
    header = contents[:32]
    if header.startswith(b"\x1aE\xdf\xa3"):
        return ".webm"
    if header.startswith(b"OggS"):
        return ".ogg"
    if header.startswith(b"RIFF") and contents[8:12] == b"WAVE":
        return ".wav"
    if header.startswith(b"ID3") or (len(header) > 1 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0):
        return ".mp3"
    if b"ftyp" in header:
        return ".m4a"
    return ""


def _audio_extension(filename: str, content_type: Optional[str]) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix in AUDIO_EXTENSIONS:
        return suffix
    mime = _normalize_mime(content_type)
    if mime in {"audio/webm", "video/webm"}:
        return ".webm"
    if mime in {"audio/wav", "audio/x-wav", "audio/wave"}:
        return ".wav"
    if mime in {"audio/mpeg", "audio/mp3"}:
        return ".mp3"
    if mime in {"audio/mp4", "audio/x-m4a", "audio/m4a"}:
        return ".m4a"
    if mime in {"audio/ogg", "application/ogg"}:
        return ".ogg"
    return ""


def _validate_audio_signature(contents: bytes, extension: str, content_type: Optional[str]) -> None:
    detected = _detect_audio_extension(contents)
    mime = _normalize_mime(content_type)
    compatible_mimes = {
        ".webm": {"audio/webm", "video/webm"},
        ".ogg": {"audio/ogg", "application/ogg"},
        ".wav": {"audio/wav", "audio/x-wav", "audio/wave"},
        ".mp3": {"audio/mpeg", "audio/mp3"},
        ".m4a": {"audio/mp4", "audio/x-m4a", "audio/m4a"},
    }
    if extension in compatible_mimes:
        valid_signature = detected == extension
        valid_mime = not mime or mime in compatible_mimes[extension] or mime.startswith("audio/")
        valid = valid_signature and valid_mime
    else:
        valid = False
    if not valid:
        raise HTTPException(status_code=400, detail="Assinatura real do áudio não confere com extensão/MIME.")


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _transcribe_audio_if_enabled(path: Path) -> tuple[Optional[str], str, Optional[str]]:
    from app.transcription_service import transcribe_audio

    return transcribe_audio(path).as_tuple()


def order_reservation_info(order: MaintenanceOrder) -> dict[str, Any]:
    now = utcnow_naive()
    expires_at = getattr(order, "reservation_expires_at", None)
    is_active = bool(expires_at and expires_at > now)
    return {
        "active": is_active,
        "operator_name": getattr(order, "reservation_operator", None) if is_active else None,
        "device_id": getattr(order, "reservation_device_id", None) if is_active else None,
        "started_at": iso(getattr(order, "reservation_started_at", None)) if is_active else None,
        "expires_at": iso(expires_at) if is_active else None,
        "ttl_seconds": max(0, int((expires_at - now).total_seconds())) if is_active and expires_at else 0,
    }


def _same_reservation(order: MaintenanceOrder, operator_name: Optional[str], device_id: Optional[str]) -> bool:
    if not device_id:
        return False
    # Um supervisor pode entregar o mesmo tablet a outro supervisor. O evento
    # de troca é registrado no salvamento da resposta; não se bloqueia o uso
    # por uma identidade antiga da própria sessão física.
    return getattr(order, "reservation_device_id", None) == device_id


def ensure_order_reservation_allowed(
    order: MaintenanceOrder,
    *,
    operator_name: Optional[str],
    device_id: Optional[str],
) -> None:
    info = order_reservation_info(order)
    if not info["active"] or not info["device_id"] or _same_reservation(order, operator_name, device_id):
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            "OM reservada em outro dispositivo por "
            f"{info['operator_name'] or 'outro operador'} até {info['expires_at']}."
        ),
    )


def reserve_order_for_execution(
    order: MaintenanceOrder,
    *,
    operator_name: Optional[str],
    device_id: Optional[str],
    ttl_minutes: int = RESERVATION_TTL_MINUTES,
) -> dict[str, Any]:
    if not device_id:
        return order_reservation_info(order)
    ensure_order_reservation_allowed(order, operator_name=operator_name, device_id=device_id)
    now = utcnow_naive()
    order.reservation_operator = operator_name
    order.reservation_device_id = device_id
    order.reservation_started_at = getattr(order, "reservation_started_at", None) or now
    order.reservation_expires_at = now + timedelta(minutes=ttl_minutes)
    return order_reservation_info(order)


async def acquire_order_reservation(
    db: AsyncSession,
    order_id: str,
    *,
    operator_name: Optional[str],
    operator_id: Optional[str] = None,
    device_id: Optional[str],
) -> dict[str, Any]:
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id é obrigatório para reservar a OM.")
    order = await get_order_or_404(db, order_id)
    if order.execution_status in {"completed", "cancelled"}:
        raise HTTPException(status_code=400, detail="OM encerrada não pode ser reservada.")
    reservation = reserve_order_for_execution(order, operator_name=operator_name, device_id=device_id)
    await add_event(
        db,
        order_id,
        "reservation_acquired",
        operator_name,
        {"reservation": reservation},
        operator_id=operator_id,
    )
    await db.commit()
    return {"reservation": order_reservation_info(order)}


async def reservation_status(
    db: AsyncSession,
    order_id: str,
) -> dict[str, Any]:
    order = await get_order_or_404(db, order_id)
    return {"reservation": order_reservation_info(order)}


async def renew_order_reservation(
    db: AsyncSession,
    order_id: str,
    *,
    operator_name: Optional[str],
    operator_id: Optional[str] = None,
    device_id: Optional[str],
) -> dict[str, Any]:
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id é obrigatório para renovar a reserva.")
    order = await get_order_or_404(db, order_id)
    if order.execution_status in {"completed", "cancelled"}:
        raise HTTPException(status_code=400, detail="OM encerrada não pode ter reserva renovada.")
    reservation = reserve_order_for_execution(order, operator_name=operator_name, device_id=device_id)
    await add_event(
        db,
        order_id,
        "reservation_renewed",
        operator_name,
        {"reservation": reservation},
        operator_id=operator_id,
    )
    await db.commit()
    return {"reservation": order_reservation_info(order)}


async def takeover_order_reservation(
    db: AsyncSession,
    order_id: str,
    *,
    operator_name: Optional[str],
    operator_id: Optional[str] = None,
    device_id: Optional[str],
    reason: Optional[str],
) -> dict[str, Any]:
    if not reason or not reason.strip():
        raise HTTPException(status_code=400, detail="Informe o motivo para assumir a execução.")
    order = await get_order_or_404(db, order_id)
    previous = order_reservation_info(order)
    order.reservation_operator = None
    order.reservation_device_id = None
    order.reservation_started_at = None
    order.reservation_expires_at = None
    reservation = reserve_order_for_execution(order, operator_name=operator_name, device_id=device_id)
    await add_event(
        db,
        order_id,
        "reservation_taken_over",
        operator_name,
        {"previous": previous if previous.get("active") else None, "reservation": reservation, "reason": reason},
        operator_id=operator_id,
    )
    await db.commit()
    return {"reservation": order_reservation_info(order), "previous": previous if previous.get("active") else None, "taken_over": True}


async def release_order_reservation(
    db: AsyncSession,
    order_id: str,
    *,
    operator_name: Optional[str],
    operator_id: Optional[str] = None,
    device_id: Optional[str],
    force: bool = False,
    reason: Optional[str] = None,
) -> dict[str, Any]:
    order = await get_order_or_404(db, order_id)
    info = order_reservation_info(order)
    if info["active"] and not _same_reservation(order, operator_name, device_id) and not force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "OM reservada em outro dispositivo. Confirme com o operador responsável "
                "antes de liberar a reserva manualmente."
            ),
        )
    previous = info if info["active"] else None
    order.reservation_operator = None
    order.reservation_device_id = None
    order.reservation_started_at = None
    order.reservation_expires_at = None
    await add_event(
        db,
        order_id,
        "reservation_released",
        operator_name,
        {"previous": previous, "forced": force, "reason": reason},
        operator_id=operator_id,
    )
    await db.commit()
    return {"reservation": order_reservation_info(order), "previous": previous, "forced": force}


def validate_item_response(
    *,
    result: Optional[str],
    defect_found: Optional[str] = None,
    corrected_in_place: Optional[bool] = None,
    correction_description: Optional[str] = None,
    needs_part: Optional[bool] = None,
    part_name: Optional[str] = None,
    can_operate: Optional[bool] = None,
    not_applicable_reason: Optional[str] = None,
) -> dict[str, Any]:
    missing: list[str] = []
    status_value = result or "unanswered"
    if status_value == "attention":
        if not _text(defect_found):
            missing.append("defect_found")
        if corrected_in_place is None:
            missing.append("corrected_in_place")
        if can_operate is None:
            missing.append("can_operate")
        if corrected_in_place is True and not _text(correction_description):
            missing.append("correction_description")
        if needs_part is True and not _text(part_name):
            missing.append("part_name")
    elif status_value == "not_applicable":
        if not _text(not_applicable_reason):
            missing.append("not_applicable_reason")
    return {
        "ready_to_complete": not missing,
        "missing_required_fields": missing,
    }


def validate_order_item_response(item: MaintenanceOrderItem) -> dict[str, Any]:
    return validate_item_response(
        result=item.status,
        defect_found=item.defect_found,
        corrected_in_place=item.corrected_in_place,
        correction_description=item.correction_description,
        needs_part=item.needs_part,
        part_name=item.part_name,
        can_operate=item.can_operate,
        not_applicable_reason=item.not_applicable_reason,
    )


def effective_open_status(order: MaintenanceOrder, today: Optional[date] = None) -> str:
    if order.status in {"completed", "completed_with_issues", "cancelled", "needs_review"}:
        return order.status
    if getattr(order, "execution_status", None) == "in_progress":
        return "in_progress"
    today = today or local_today()
    if order.scheduled_day_is_explicit and order.planned_date:
        if order.planned_date < today:
            return "overdue"
        if order.planned_date == today:
            return "today"
        return "scheduled"
    planned_year = order.planned_year
    planned_month = order.planned_month
    if (not planned_year or not planned_month) and order.planned_date:
        planned_year = order.planned_date.year
        planned_month = order.planned_date.month
    if planned_year and planned_month:
        planned = (planned_year, planned_month)
        current = (today.year, today.month)
        if planned < current:
            return "overdue"
        if planned == current:
            return "today"
        return "scheduled"
    return order.status or "scheduled"


def calculate_next_date(
    planned_date: Optional[date],
    completed_date: Optional[date],
    periodicity: str,
    frequency_days: Optional[int],
    frequency_months: Optional[int],
    calculation_basis: str,
) -> Optional[date]:
    base_date = planned_date if calculation_basis == "fixed_calendar" else completed_date
    if not base_date:
        base_date = completed_date or planned_date
    if not base_date:
        return None
    if frequency_days:
        from datetime import timedelta

        return base_date + timedelta(days=frequency_days)
    if frequency_months:
        return base_date + relativedelta(months=frequency_months)

    months = {
        "monthly": 1,
        "mensal": 1,
        "bimonthly": 2,
        "bimestral": 2,
        "trimonthly": 3,
        "trimestral": 3,
        "quarterly": 3,
        "semiannual": 6,
        "semestral": 6,
        "annual": 12,
        "anual": 12,
    }.get((periodicity or "").lower().strip())
    if not months:
        return None
    return base_date + relativedelta(months=months)


async def get_order_or_404(db: AsyncSession, order_id: str) -> MaintenanceOrder:
    result = await db.execute(
        select(MaintenanceOrder)
        .where(MaintenanceOrder.id == order_id)
        .options(
            selectinload(MaintenanceOrder.asset).selectinload(Asset.sector),
            selectinload(MaintenanceOrder.items),
            selectinload(MaintenanceOrder.evidences),
            selectinload(MaintenanceOrder.materials),
            selectinload(MaintenanceOrder.events),
            selectinload(MaintenanceOrder.snapshot),
        )
    )
    order = result.scalars().first()
    if not order:
        raise HTTPException(status_code=404, detail="OM não encontrada")
    return order


async def add_event(
    db: AsyncSession,
    order_id: str,
    event_type: str,
    operator_name: Optional[str],
    payload: dict[str, Any],
    operator_id: Optional[str] = None,
) -> WorkOrderEvent:
    event = WorkOrderEvent(
        id=gen_id(),
        order_id=order_id,
        event_type=event_type,
        operator_name=operator_name,
        operator_id=operator_id,
        payload=json.dumps(payload, ensure_ascii=False, default=str),
        created_at=utcnow_naive(),
    )
    db.add(event)
    return event


async def ensure_snapshot(db: AsyncSession, order: MaintenanceOrder) -> None:
    existing = await db.execute(select(WorkOrderSnapshot).where(WorkOrderSnapshot.order_id == order.id))
    if existing.scalars().first():
        return

    checklist_items = []
    if order.checklist_version_id:
        items_res = await db.execute(
            select(ChecklistItem)
            .where(ChecklistItem.version_id == order.checklist_version_id)
            .order_by(ChecklistItem.item_number)
        )
        checklist_items = [
            {
                "id": item.id,
                "item_number": item.item_number,
                "description": item.description,
                "item_type": item.item_type,
                "is_mandatory": bool(item.is_mandatory),
                "is_critical": bool(item.is_critical),
            }
            for item in items_res.scalars().all()
        ]

    epi_policy = await resolve_epi_policy(db, order)

    snapshot = {
        "order_id": order.id,
        "friendly_number": order.friendly_number,
        "asset_id": order.asset_id,
        "plan_id": order.plan_id,
        "order_type": order.order_type,
        "occurrence_number": order.occurrence_number,
        "competence": order.original_competence,
        "checklist_version_id": order.checklist_version_id,
        "snapshot_at": utcnow_naive().isoformat(),
        "asset": serialize_asset(order.asset) if order.asset else None,
        "checklist_items": checklist_items,
        "epi_requirements": epi_policy["requirements"],
        "epi_policy": epi_policy,
    }
    db.add(
        WorkOrderSnapshot(
            id=gen_id(),
            order_id=order.id,
            snapshot_json=json.dumps(snapshot, ensure_ascii=False, default=str),
            created_at=utcnow_naive(),
        )
    )


def serialize_asset(asset: Optional[Asset]) -> Optional[dict[str, Any]]:
    if not asset:
        return None
    return {
        "id": asset.id,
        "patrimonio": asset.patrimonio,
        "type": asset.type,
        "description": asset.description,
        "manufacturer": asset.manufacturer,
        "model": asset.model,
        "serial_number": asset.serial_number,
        "status": asset.status,
        "is_operable": bool(asset.is_operable),
        "sector": {
            "id": asset.sector.id,
            "name": asset.sector.name,
            "description": asset.sector.description,
        }
        if asset.sector
        else None,
    }


def serialize_order(order: MaintenanceOrder) -> dict[str, Any]:
    return {
        "id": order.id,
        "friendly_number": order.friendly_number,
        "asset_id": order.asset_id,
        "plan_id": order.plan_id,
        "checklist_version_id": order.checklist_version_id,
        "planned_date": iso(order.planned_date),
        "planned_year": order.planned_year,
        "planned_month": order.planned_month,
        "original_competence": order.original_competence,
        "scheduled_day_is_explicit": bool(order.scheduled_day_is_explicit),
        "priority": order.priority,
        "status": order.status,
        "deadline_status": effective_open_status(order),
        "execution_status": order.execution_status or "not_started",
        "record_kind": getattr(order, "record_kind", "official") or "official",
        "record_kind_reason": getattr(order, "record_kind_reason", None),
        "started_at": iso(order.started_at),
        "completed_at": iso(order.completed_at),
        "duration_mins": order.duration_mins,
        "notes": order.notes,
        "final_condition": order.final_condition,
        "operator_name": order.operator_name,
        "operator_id": getattr(order, "operator_id", None),
        "checked_by_name": order.operator_name,
        "checked_by_operator_id": getattr(order, "operator_id", None),
        "performed_by_name": getattr(order, "performed_by_snapshot", None) or getattr(order, "performed_by_name", None),
        "performed_by_operator_id": getattr(order, "performed_by_operator_id", None),
        "opaque_token": order.opaque_token,
        "order_type": order.order_type,
        "parent_work_order_id": order.parent_work_order_id,
        "relation_type": order.relation_type,
        "occurrence_number": order.occurrence_number,
        "plan_code": order.plan_code,
        "epi_confirmed": bool(order.epi_confirmed),
        "epi_confirmed_at": iso(order.epi_confirmed_at),
        "epi_confirmed_by": order.epi_confirmed_by,
        "machine_stopped": bool(order.machine_stopped),
        "machine_stopped_at": iso(order.machine_stopped_at),
        "machine_released_at": iso(order.machine_released_at),
        "final_pdf_path": order.final_pdf_path,
        "final_pdf_sha256": getattr(order, "final_pdf_sha256", None),
        "final_sha256": order.final_sha256,
        "final_revision": order.final_revision,
        "round_id": order.round_id,
    }


def _epi_policy(status_value: str, requirements: list[dict[str, Any]], source: Optional[str] = None, suggestions: list[dict[str, Any]] = None) -> dict[str, Any]:
    return {
        "status": status_value,
        "requirements": requirements,
        "suggestions": suggestions or [],
        "source": source,
    }


def _serialize_epi_requirement(epi: EpiRequirement, source: str) -> dict[str, Any]:
    return {
        "id": epi.id,
        "item_name": epi.item_name,
        "is_mandatory": bool(epi.is_mandatory),
        "source": source,
    }


async def resolve_epi_policy(db: AsyncSession, order: MaintenanceOrder) -> dict[str, Any]:
    # 1. snapshot da OM, caso a execução já tenha sido iniciada;
    if order.snapshot:
        try:
            snapshot = json.loads(order.snapshot.snapshot_json)
        except json.JSONDecodeError:
            snapshot = {}
        if isinstance(snapshot.get("epi_policy"), dict):
            policy = snapshot["epi_policy"]
            return {
                "status": policy.get("status") or ("defined" if policy.get("requirements") else "not_defined"),
                "requirements": policy.get("requirements") or [],
                "suggestions": policy.get("suggestions") or [],
                "source": "snapshot",
            }
        if isinstance(snapshot.get("epi_requirements"), list):
            requirements = snapshot["epi_requirements"]
            return _epi_policy("defined" if requirements else "not_defined", requirements, "snapshot")

    # Buscar sugestões primeiro para passar a qualquer política resolvida
    suggestions = []
    if order.plan_id:
        from app.models import EpiSuggestion
        sugg_res = await db.execute(
            select(EpiSuggestion).where(EpiSuggestion.plan_id == order.plan_id)
        )
        sugg = sugg_res.scalars().first()
        if sugg and sugg.items_json:
            try:
                raw_sugg = json.loads(sugg.items_json)
                suggestions = [
                    {
                        "id": item.get("epi_catalog_id"),
                        "item_name": item.get("name"),
                        "is_mandatory": bool(item.get("is_mandatory")),
                        "category": item.get("category"),
                    }
                    for item in raw_sugg
                ]
            except Exception:
                suggestions = []

    # 1.5. Se houver EpiConfirmation com status 'confirmed', usar os itens dela
    confirm_res = await db.execute(
        select(EpiConfirmation)
        .where(EpiConfirmation.order_id == order.id, EpiConfirmation.status == "confirmed")
    )
    conf = confirm_res.scalars().first()
    if conf and conf.items_json:
        try:
            confirmed_items = json.loads(conf.items_json)
            requirements = [
                {
                    "id": f"conf_{i}",
                    "item_name": name,
                    "is_mandatory": True,
                    "source": "confirmation",
                }
                for i, name in enumerate(confirmed_items)
            ]
            return _epi_policy("defined" if confirmed_items else "not_defined", requirements, "confirmation", suggestions)
        except Exception:
            pass

    # 2. EPIs da versão do checklist usada pela OM
    if order.checklist_version_id:
        version_res = await db.execute(
            select(ChecklistTemplateVersion).where(ChecklistTemplateVersion.id == order.checklist_version_id)
        )
        version = version_res.scalars().first()
        if version:
            checklist_epi_res = await db.execute(
                select(EpiRequirement).where(EpiRequirement.checklist_template_id == version.template_id)
            )
            checklist_epis = [
                _serialize_epi_requirement(epi, "checklist")
                for epi in checklist_epi_res.scalars().all()
            ]
            if checklist_epis:
                return _epi_policy("defined", checklist_epis, "checklist", suggestions)

    # 3. EPIs configurados no plano
    if order.plan_id:
        epi_res = await db.execute(select(EpiRequirement).where(EpiRequirement.plan_id == order.plan_id))
        plan_epis = [
            _serialize_epi_requirement(epi, "plan")
            for epi in epi_res.scalars().all()
        ]
        if plan_epis:
            return _epi_policy("defined", plan_epis, "plan", suggestions)

    # 4. EPIs resolvidos pelo motor de regras aprovado. Isso cobre regras globais,
    # por setor, tipo, família, checklist, plano e ativo sem depender de cópia legada.
    if order.plan_id:
        try:
            from app.rules_engine import resolve_epis_for_plan
            resolved_epis = await resolve_epis_for_plan(db, order.plan_id)
        except Exception:
            resolved_epis = []
        if resolved_epis:
            requirements = [
                {
                    "id": item.get("id"),
                    "item_name": item.get("item_name"),
                    "is_mandatory": bool(item.get("is_mandatory", True)),
                    "source": item.get("source") or "rules",
                    "category": item.get("category"),
                }
                for item in resolved_epis
            ]
            return _epi_policy("defined", requirements, "rules", suggestions)

    # 5. EPIs configurados diretamente para o ativo, se o modelo atual suportar
    if order.asset_id:
        from app.models import EpiRule, EpiRuleItem
        rule_res = await db.execute(
            select(EpiRule)
            .where(
                EpiRule.scope == "asset",
                EpiRule.scope_id == order.asset_id,
                EpiRule.status == "approved"
            )
            .options(selectinload(EpiRule.rule_items).selectinload(EpiRuleItem.epi_catalog))
        )
        rule = rule_res.scalars().first()
        if rule and rule.rule_items:
            asset_epis = [
                {
                    "id": item.id,
                    "item_name": item.epi_catalog.name,
                    "is_mandatory": item.obrigatoriedade == "mandatory",
                    "source": "asset",
                }
                for item in rule.rule_items if item.epi_catalog
            ]
            if asset_epis:
                return _epi_policy("defined", asset_epis, "asset", suggestions)

    return {
        "status": "not_defined",
        "requirements": [],
        "suggestions": suggestions,
        "source": None,
    }


async def get_order_detail(db: AsyncSession, order_id: str) -> dict[str, Any]:
    order = await get_order_or_404(db, order_id)

    plan = None
    if order.plan_id:
        plan_res = await db.execute(select(MaintenancePlan).where(MaintenancePlan.id == order.plan_id))
        plan = plan_res.scalars().first()

    checklist_version = None
    checklist_items = []
    if order.checklist_version_id:
        version_res = await db.execute(
            select(ChecklistTemplateVersion)
            .where(ChecklistTemplateVersion.id == order.checklist_version_id)
            .options(selectinload(ChecklistTemplateVersion.template))
        )
        version = version_res.scalars().first()
        if version:
            checklist_version = {
                "id": version.id,
                "version": version.version,
                "template_id": version.template_id,
                "template_name": version.template.name if version.template else None,
                "template_code": version.template.code_reference if version.template else None,
                "source_document": version.source_document,
                "source_document_hash": version.source_document_hash,
                "created_at": iso(version.created_at),
                "valid_from": iso(version.valid_from),
                "valid_until": iso(version.valid_until),
            }
        items_res = await db.execute(
            select(ChecklistItem)
            .where(ChecklistItem.version_id == order.checklist_version_id)
            .order_by(ChecklistItem.item_number)
        )
        checklist_items = items_res.scalars().all()

    response_by_item_id = {item.item_id: item for item in order.items}
    photo_by_order_item_id: dict[str, str] = {}
    for evidence in sorted(order.evidences, key=lambda ev: ev.uploaded_at or datetime.min):
        if evidence.order_item_id and evidence.evidence_type in {"item_photo", "defect_photo", "general_photo"}:
            photo_by_order_item_id[evidence.order_item_id] = evidence.file_path
    items = []
    for checklist_item in checklist_items:
        response = response_by_item_id.get(checklist_item.id)
        items.append(
            {
                "id": checklist_item.id,
                "answer_id": response.id if response else None,
                "item_id": checklist_item.id,
                "item_number": checklist_item.item_number,
                "description": checklist_item.description,
                "is_mandatory": bool(checklist_item.is_mandatory),
                "allow_photo": bool(checklist_item.allow_photo),
                "is_critical": bool(checklist_item.is_critical),
                "item_type": checklist_item.item_type,
                "suggested_materials": checklist_item.suggested_materials,
                "status": response.status if response else "unanswered",
                "notes": response.notes if response else None,
                "answered_at": iso(response.answered_at) if response else None,
                "operator_name": response.operator_name if response else None,
                "operator_id": getattr(response, "operator_id", None) if response else None,
                "defect_found": response.defect_found if response else None,
                "corrected_in_place": response.corrected_in_place if response else None,
                "correction_description": response.correction_description if response else None,
                "needs_part": response.needs_part if response else None,
                "part_name": response.part_name if response else None,
                "can_operate": response.can_operate if response else None,
                "not_applicable_reason": response.not_applicable_reason if response else None,
                "audio_transcript": response.audio_transcript if response else None,
                "photo_category": response.photo_category if response else None,
                "photo_path": photo_by_order_item_id.get(response.id) if response else None,
                "validation": validate_order_item_response(response) if response else validate_item_response(result="unanswered"),
            }
        )
    for response in order.items:
        if response.item_id not in {item["item_id"] for item in items}:
            items.append(
                {
                    "id": response.id,
                    "item_id": response.item_id,
                    "item_number": None,
                    "description": "Item do checklist não encontrado",
                    "status": response.status,
                    "notes": response.notes,
                    "answered_at": iso(response.answered_at),
                    "operator_name": response.operator_name,
                    "operator_id": getattr(response, "operator_id", None),
                }
            )

    epi_policy = await resolve_epi_policy(db, order)

    material_req_res = await db.execute(select(MaterialRequest).where(MaterialRequest.order_id == order.id))
    relations_res = await db.execute(
        select(MaintenanceOrder).where(
            (MaintenanceOrder.parent_work_order_id == order.id) | (MaintenanceOrder.id == order.parent_work_order_id)
        )
    )
    round_link = None
    if order.round_id:
        round_res = await db.execute(
            select(RoundOrder).where(RoundOrder.order_id == order.id).options(selectinload(RoundOrder.round))
        )
        round_order = round_res.scalars().first()
        if round_order and round_order.round:
            round_link = {
                "id": round_order.round.id,
                "name": round_order.round.name,
                "status": round_order.round.status,
                "sequence": round_order.sequence,
            }

    snapshot = None
    if order.snapshot:
        try:
            snapshot = json.loads(order.snapshot.snapshot_json)
        except json.JSONDecodeError:
            snapshot = {"raw": order.snapshot.snapshot_json}

    return {
        "order": serialize_order(order),
        "asset": serialize_asset(order.asset),
        "plan": {
            "id": plan.id,
            "name": plan.name,
            "periodicity": plan.periodicity,
            "frequency_days": plan.frequency_days,
            "frequency_months": plan.frequency_months,
            "calculation_basis": plan.calculation_basis,
            "plan_type": plan.plan_type,
            "recurrence_status": plan.recurrence_status,
            "safety_instructions": plan.safety_instructions,
            "checklist_template_version_id": plan.checklist_template_version_id,
        }
        if plan
        else None,
        "deadline_status": effective_open_status(order),
        "execution_status": order.execution_status or "not_started",
        "checklist_version": checklist_version,
        "items": items,
        "answers": [item for item in items if item.get("id")],
        "epi_requirements": epi_policy,
        "materials": [
            {"id": mat.id, "name": mat.name, "quantity_text": mat.quantity_text}
            for mat in order.materials
        ],
        "material_requests": [
            {
                "id": req.id,
                "item_name": req.item_name,
                "quantity": req.quantity,
                "unit": req.unit,
                "priority": req.priority,
                "status": req.status,
            }
            for req in material_req_res.scalars().all()
        ],
        "evidences": [
            {
                "id": ev.id,
                "order_id": ev.order_id,
                "order_item_id": ev.order_item_id,
                "asset_id": ev.asset_id,
                "evidence_type": ev.evidence_type,
                "file_path": ev.file_path,
                "file_hash": ev.file_hash,
                "uploaded_at": iso(ev.uploaded_at),
            }
            for ev in order.evidences
        ],
        "relations": [
            {
                "id": rel.id,
                "friendly_number": rel.friendly_number,
                "order_type": rel.order_type,
                "relation_type": rel.relation_type,
                "parent_work_order_id": rel.parent_work_order_id,
                "status": rel.status,
                "execution_status": rel.execution_status,
            }
            for rel in relations_res.scalars().all()
            if rel.id != order.id
        ],
        "round": round_link,
        "draft": {
            "answered_count": len([item for item in items if item.get("status") not in (None, "unanswered")]),
            "unanswered_count": len([item for item in items if item.get("status") in (None, "unanswered")]),
            "has_draft": any(item.get("status") not in (None, "unanswered") for item in items)
            and order.execution_status == "in_progress",
        },
        "snapshot": snapshot,
        "reservation": order_reservation_info(order),
    }





async def confirm_epi(
    db: AsyncSession,
    order_id: str,
    operator_name: str,
    operator_id: Optional[str] = None,
    confirmed: bool = True,
    missing_items: Optional[list[str]] = None,
    updated_items: Optional[list[str]] = None,
    save_as_default: bool = False,
) -> dict[str, Any]:
    from sqlalchemy import delete
    order = await get_order_or_404(db, order_id)
    if order.execution_status in {"completed", "cancelled"}:
        raise HTTPException(status_code=400, detail="OM encerrada não pode receber confirmação de EPI.")

    # Se a lista foi customizada e o usuário pediu para salvar como default
    if save_as_default and updated_items is not None:
        if order.plan_id:
            # Remover EPIs antigos do plano
            await db.execute(
                delete(EpiRequirement).where(EpiRequirement.plan_id == order.plan_id)
            )
            # Adicionar novos EPIs ao plano
            for name in updated_items:
                db.add(EpiRequirement(
                    id=gen_id(),
                    plan_id=order.plan_id,
                    item_name=name,
                    is_mandatory=True,
                    added_by=operator_name,
                    added_at=utcnow_naive(),
                ))
        elif order.checklist_version_id:
            # Obter a versão do checklist para saber o template_id
            version_res = await db.execute(
                select(ChecklistTemplateVersion).where(ChecklistTemplateVersion.id == order.checklist_version_id)
            )
            version = version_res.scalars().first()
            if version and version.template_id:
                # Remover EPIs antigos do checklist template
                await db.execute(
                    delete(EpiRequirement).where(EpiRequirement.checklist_template_id == version.template_id)
                )
                # Adicionar novos EPIs ao checklist template
                for name in updated_items:
                    db.add(EpiRequirement(
                        id=gen_id(),
                        checklist_template_id=version.template_id,
                        item_name=name,
                        is_mandatory=True,
                        added_by=operator_name,
                        added_at=utcnow_naive(),
                    ))

    # Determinar a lista de itens obrigatórios confirmados
    if updated_items is not None:
        confirmed_names = updated_items
    else:
        epi_policy = await resolve_epi_policy(db, order)
        confirmed_names = [epi["item_name"] for epi in epi_policy["requirements"]]

    status_value = "confirmed" if confirmed else "blocked"
    blocker = None if confirmed else f"Itens faltando: {', '.join(missing_items or [])}"

    # Salvar ou atualizar confirmação de EPI
    existing = await db.execute(select(EpiConfirmation).where(EpiConfirmation.order_id == order_id))
    previous = existing.scalars().first()
    if previous:
        previous.operator_name = operator_name
        previous.operator_id = operator_id
        previous.confirmed_at = utcnow_naive()
        previous.items_json = json.dumps(confirmed_names, ensure_ascii=False)
        previous.status = status_value
        previous.blocker_reason = blocker
    else:
        confirmation = EpiConfirmation(
            id=gen_id(),
            order_id=order_id,
            operator_name=operator_name,
            operator_id=operator_id,
            confirmed_at=utcnow_naive(),
            items_json=json.dumps(confirmed_names, ensure_ascii=False),
            status=status_value,
            blocker_reason=blocker,
        )
        db.add(confirmation)

    if confirmed:
        order.epi_confirmed = True
        order.epi_confirmed_at = utcnow_naive()
        order.epi_confirmed_by = operator_name
        await add_event(
            db,
            order_id,
            "epi_confirmed",
            operator_name,
            {
                "epi_count": len(confirmed_names),
                "items": confirmed_names,
                "epi_status": "defined" if confirmed_names else "not_defined",
            },
            operator_id=operator_id,
        )
    else:
        await add_event(db, order_id, "epi_blocked", operator_name, {"missing": missing_items or []}, operator_id=operator_id)

    await db.commit()
    return {
        "status": status_value,
        "epi_confirmed": confirmed,
        "message": "EPI confirmado. Pode iniciar a manutenção." if confirmed else f"Início bloqueado. {blocker}",
        "epis_required": confirmed_names,
    }


async def start_order(
    db: AsyncSession,
    order_id: str,
    operator_name: str,
    operator_id: Optional[str] = None,
    device_id: Optional[str] = None,
    record_kind: str = "official",
) -> dict[str, Any]:
    if record_kind not in {"official", "demo_test"}:
        raise HTTPException(status_code=400, detail="Tipo de início inválido.")
    order = await get_order_or_404(db, order_id)
    if order.execution_status in {"in_progress", "completed", "cancelled"}:
        raise HTTPException(status_code=400, detail=f"OM já está em estado '{order.execution_status}'.")
    reservation = reserve_order_for_execution(order, operator_name=operator_name, device_id=device_id)

    await ensure_snapshot(db, order)
    now = utcnow_naive()
    order.execution_status = "in_progress"
    order.status = "in_progress"
    order.record_kind = record_kind
    if record_kind == "demo_test":
        order.record_kind_reason = "Teste/demonstração iniciado no aplicativo"
        order.record_kind_classified_at = now
        order.record_kind_classified_by = operator_name
    order.started_at = now
    order.operator_name = operator_name

    # Decisão operacional ManutencaoEmCampo: EPI é orientação apresentada, não uma barreira
    # de interface. A ausência de confirmação permanece explicitamente auditada;
    # isso não substitui PGR, treinamento, bloqueio/etiquetagem ou a regra física.
    if not order.epi_confirmed:
        await add_event(
            db,
            order_id,
            "epi_guidance_not_confirmed",
            operator_name,
            {"message": "Orientações de EPI exibidas; execução iniciada sem confirmação digital bloqueante."},
            operator_id=operator_id,
        )
    order.operator_id = operator_id

    if order.plan_id:
        count_res = await db.execute(
            select(func.count(MaintenanceOrder.id)).where(
                MaintenanceOrder.plan_id == order.plan_id,
                MaintenanceOrder.execution_status.in_(["completed", "in_progress"]),
                MaintenanceOrder.id != order.id,
            )
        )
        order.occurrence_number = (count_res.scalar() or 0) + 1

    await add_event(
        db,
        order_id,
        "started",
        operator_name,
        {
            "started_at": now.isoformat(),
            "occurrence_number": order.occurrence_number,
            "reservation": reservation,
            "record_kind": record_kind,
        },
        operator_id=operator_id,
    )
    await db.commit()
    return {
        "status": "in_progress",
        "order_id": order_id,
        "friendly_number": order.friendly_number,
        "started_at": now.isoformat(),
        "operator_name": operator_name,
        "occurrence_number": order.occurrence_number,
        "record_kind": record_kind,
        "reservation": order_reservation_info(order),
        "message": "Execução iniciada. Responda os itens do checklist.",
    }


async def answer_item(
    db: AsyncSession,
    order_id: str,
    item_id: str,
    result: str,
    operator_name: Optional[str] = None,
    operator_id: Optional[str] = None,
    notes: Optional[str] = None,
    defect_found: Optional[str] = None,
    corrected_in_place: Optional[bool] = None,
    correction_description: Optional[str] = None,
    needs_part: Optional[bool] = None,
    part_name: Optional[str] = None,
    can_operate: Optional[bool] = None,
    not_applicable_reason: Optional[str] = None,
    audio_transcript: Optional[str] = None,
    photo_category: Optional[str] = None,
    device_id: Optional[str] = None,
) -> dict[str, Any]:
    if result not in {"unanswered", "ok", "attention", "not_applicable"}:
        raise HTTPException(status_code=400, detail="Resposta inválida para o checklist.")
    order = await get_order_or_404(db, order_id)
    if order.execution_status != "in_progress":
        raise HTTPException(status_code=409, detail="OM não está em execução. Confirme o EPI e toque em começar antes de responder.")
    prior_reservation = order_reservation_info(order)
    reserve_order_for_execution(order, operator_name=operator_name, device_id=device_id)

    item_res = await db.execute(
        select(MaintenanceOrderItem).where(
            MaintenanceOrderItem.order_id == order_id,
            MaintenanceOrderItem.item_id == item_id,
        )
    )
    item = item_res.scalars().first()
    if not item:
        item = MaintenanceOrderItem(order_id=order_id, item_id=item_id, status="unanswered")
        db.add(item)

    previous = {
        "status": item.status,
        "notes": item.notes,
        "operator_name": item.operator_name,
        "operator_id": item.operator_id,
        "answered_at": iso(item.answered_at),
    }

    now = utcnow_naive()
    item.status = result
    item.operator_name = operator_name
    item.operator_id = operator_id
    item.answered_at = now if result != "unanswered" else None
    item.notes = notes
    if result == "ok":
        item.defect_found = None
        item.corrected_in_place = None
        item.correction_description = None
        item.needs_part = None
        item.part_name = None
        item.can_operate = None
        item.not_applicable_reason = None
    elif result == "not_applicable":
        item.defect_found = None
        item.corrected_in_place = None
        item.correction_description = None
        item.needs_part = None
        item.part_name = None
        item.can_operate = None
        item.not_applicable_reason = _text(not_applicable_reason) or None
    elif result == "attention":
        item.defect_found = _text(defect_found) or None
        item.corrected_in_place = corrected_in_place
        item.correction_description = _text(correction_description) or None
        item.needs_part = bool(needs_part) if needs_part is not None else None
        item.part_name = _text(part_name) or None
        item.can_operate = can_operate
        item.not_applicable_reason = None
    else:
        item.defect_found = None
        item.corrected_in_place = None
        item.correction_description = None
        item.needs_part = None
        item.part_name = None
        item.can_operate = None
        item.not_applicable_reason = None
    item.audio_transcript = audio_transcript
    item.photo_category = photo_category

    # Camila e Rafael podem usar o mesmo tablet em momentos distintos. A
    # resposta atual segue editável até concluir, mas uma troca de conferente
    # ou de resultado nunca fica silenciosa para a auditoria.
    previous_answered = previous["status"] and previous["status"] != "unanswered"
    reviewer_changed = previous_answered and previous["operator_id"] != operator_id
    result_changed = previous_answered and previous["status"] != result
    if reviewer_changed or result_changed:
        await add_event(
            db,
            order_id,
            "checklist_item_revised",
            operator_name,
            {
                "item_id": item_id,
                "previous": previous,
                "current": {"status": result, "notes": item.notes, "operator_name": operator_name, "operator_id": operator_id, "answered_at": iso(now)},
            },
            operator_id=operator_id,
        )
    if prior_reservation["active"] and prior_reservation["operator_name"] != operator_name and prior_reservation["device_id"] == device_id:
        await add_event(
            db,
            order_id,
            "checklist_reviewer_handover",
            operator_name,
            {"from": prior_reservation["operator_name"], "to": operator_name, "device_id": device_id},
            operator_id=operator_id,
        )

    if needs_part and part_name:
        existing_material_res = await db.execute(
            select(MaterialRequest).where(
                MaterialRequest.order_id == order_id,
                MaterialRequest.item_name == part_name,
            )
        )
        if not existing_material_res.scalars().first():
            db.add(MaterialRequest(
                order_id=order_id,
                asset_id=order.asset_id,
                item_name=part_name,
                priority=order.priority or "medium",
                status="requested",
                requested_by=operator_name,
                requested_at=now,
                defect_description=defect_found or notes,
                notes=f"Solicitado a partir do item {item_id}",
            ))

    await db.commit()

    validation = validate_order_item_response(item)
    response = {"saved": True, "item_id": item_id, "result": result, "validation": validation}
    if item.needs_part and item.part_name:
        response["material_requested"] = True
    if result == "attention" and item.can_operate is False:
        response.update({"requires_action": "machine_stopped", "message": "Item reprovado com máquina parada. Registre a parada."})
    elif result == "attention" and item.corrected_in_place is False:
        response.update({"requires_action": "create_corrective", "message": "Problema não corrigido no local. Deseja criar uma ordem corretiva?"})
    return response


async def attach_item_audio(
    db: AsyncSession,
    order_id: str,
    *,
    item_id: str,
    contents: bytes,
    filename: str,
    content_type: Optional[str],
    operator_name: Optional[str] = None,
    operator_id: Optional[str] = None,
    manual_transcript: Optional[str] = None,
    device_id: Optional[str] = None,
    duration_sec: Optional[float] = None,
) -> dict[str, Any]:
    if not contents:
        raise HTTPException(status_code=400, detail="Arquivo de áudio vazio.")
    if category_for_name(filename, content_type) != "audio":
        raise HTTPException(status_code=400, detail="Envie um arquivo de áudio válido.")
    limit = get_limit_for_name(filename, content_type)
    if len(contents) > limit:
        raise HTTPException(status_code=400, detail=f"Arquivo de áudio muito grande. Limite: {round(limit / 1024 / 1024)} MB.")
    extension = _detect_audio_extension(contents) or _audio_extension(filename, content_type)
    if not extension:
        raise HTTPException(status_code=400, detail="Extensão de áudio não permitida.")
    _validate_audio_signature(contents, extension, content_type)

    order = await get_order_or_404(db, order_id)
    if order.execution_status != "in_progress":
        raise HTTPException(status_code=409, detail="OM não está em execução. Confirme o EPI e toque em começar antes de gravar áudio.")
    reserve_order_for_execution(order, operator_name=operator_name, device_id=device_id)

    item_res = await db.execute(
        select(MaintenanceOrderItem).where(
            MaintenanceOrderItem.order_id == order_id,
            MaintenanceOrderItem.item_id == item_id,
        )
    )
    item = item_res.scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="Item do checklist não encontrado nesta OM.")

    file_hash = hashlib.sha256(contents).hexdigest()
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4()}{extension}"
    stored_path = UPLOADS_DIR / stored_name
    stored_path.write_bytes(contents)
    relative_path = f"data/uploads/{stored_name}"

    transcript = _text(manual_transcript) or None
    transcription_status = "manual_transcript" if transcript else "stored_without_transcription"
    transcription_error = None
    if not transcript:
        transcript, transcription_status, transcription_error = _transcribe_audio_if_enabled(stored_path)

    if transcript:
        label = transcript
        existing_notes = _text(item.notes)
        if label not in existing_notes:
            item.notes = f"{existing_notes}\n{label}".strip() if existing_notes else label
        existing_transcript = _text(item.audio_transcript)
        item.audio_transcript = f"{existing_transcript}\n{transcript}".strip() if existing_transcript and transcript not in existing_transcript else transcript
    if operator_name:
        item.operator_name = operator_name
    if operator_id:
        item.operator_id = operator_id

    evidence = MaintenanceEvidence(
        id=gen_id(),
        order_id=order_id,
        order_item_id=item.id,
        asset_id=order.asset_id,
        evidence_type="item_audio",
        file_path=relative_path,
        file_hash=file_hash,
        uploaded_at=utcnow_naive(),
        uploader_name=operator_name,
        uploader_operator_id=operator_id,
        device_id=device_id,
        captured_at=utcnow_naive(),
        received_at=utcnow_naive(),
        source="checklist_audio",
        original_filename=filename,
        mime_type=_normalize_mime(content_type),
        file_size=len(contents),
        dossier_status="pending",
    )
    db.add(evidence)
    await add_event(
        db,
        order_id,
        "audio_attached",
        operator_name,
        {
            "item_id": item_id,
            "order_item_id": item.id,
            "evidence_id": evidence.id,
            "file_hash": file_hash,
            "content_type": content_type,
            "transcription_status": transcription_status,
            "duration_sec": duration_sec,
        },
        operator_id=operator_id,
    )
    from app.dossier_service import queue_order_dossier
    dossier_job = await queue_order_dossier(
        db,
        order_id,
        requested_by=operator_name,
        requested_by_operator_id=operator_id,
        device_id=device_id,
    )
    await db.commit()
    from app.dossier_service import sync_job
    dossier_sync = await sync_job(db, dossier_job)
    return {
        "saved": True,
        "evidence_id": evidence.id,
        "item_id": item_id,
        "order_item_id": item.id,
        "file_path": relative_path,
        "file_hash": file_hash,
        "transcription": {
            "status": transcription_status,
            "text": transcript,
            "raw_text": transcript,
            "corrected_text": None,
            "error": transcription_error,
        },
        "duration_sec": duration_sec,
        "dossier_sync": dossier_sync,
    }


async def attach_item_photo(
    db: AsyncSession,
    order_id: str,
    *,
    item_id: str,
    contents: bytes,
    filename: str,
    content_type: Optional[str],
    operator_name: Optional[str] = None,
    operator_id: Optional[str] = None,
    device_id: Optional[str] = None,
) -> dict[str, Any]:
    if not contents:
        raise HTTPException(status_code=400, detail="Arquivo de imagem vazio.")

    order = await get_order_or_404(db, order_id)
    if order.execution_status != "in_progress":
        raise HTTPException(status_code=409, detail="OM não está em execução. Confirme o EPI e toque em começar antes de anexar foto.")
    reserve_order_for_execution(order, operator_name=operator_name, device_id=device_id)

    item_res = await db.execute(
        select(MaintenanceOrderItem).where(
            MaintenanceOrderItem.order_id == order_id,
            MaintenanceOrderItem.item_id == item_id,
        )
    )
    item = item_res.scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="Item do checklist não encontrado nesta OM.")

    relative_path, file_hash = validate_and_save_image(contents, filename, content_type or "", str(UPLOADS_DIR))
    evidence = MaintenanceEvidence(
        id=gen_id(),
        order_id=order_id,
        order_item_id=item.id,
        asset_id=order.asset_id,
        evidence_type="item_photo",
        file_path=relative_path,
        file_hash=file_hash,
        uploaded_at=utcnow_naive(),
        uploader_name=operator_name,
        uploader_operator_id=operator_id,
        device_id=device_id,
        captured_at=utcnow_naive(),
        received_at=utcnow_naive(),
        source="checklist_photo",
        original_filename=filename,
        mime_type=_normalize_mime(content_type),
        file_size=len(contents),
        dossier_status="pending",
    )
    db.add(evidence)
    if operator_name:
        item.operator_name = operator_name
    if operator_id:
        item.operator_id = operator_id
    await add_event(
        db,
        order_id,
        "photo_attached",
        operator_name,
        {
            "item_id": item_id,
            "order_item_id": item.id,
            "evidence_id": evidence.id,
            "file_hash": file_hash,
            "content_type": content_type,
        },
        operator_id=operator_id,
    )
    from app.dossier_service import queue_order_dossier
    dossier_job = await queue_order_dossier(
        db,
        order_id,
        requested_by=operator_name,
        requested_by_operator_id=operator_id,
        device_id=device_id,
    )
    await db.commit()
    from app.dossier_service import sync_job
    dossier_sync = await sync_job(db, dossier_job)
    return {
        "saved": True,
        "evidence_id": evidence.id,
        "item_id": item_id,
        "order_item_id": item.id,
        "file_path": relative_path,
        "file_hash": file_hash,
        "dossier_sync": dossier_sync,
    }


async def complete_order(
    db: AsyncSession,
    order_id: str,
    operator_name: str,
    operator_id: Optional[str] = None,
    final_condition: str = "released",
    notes: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    device_id: Optional[str] = None,
    performed_by_name: Optional[str] = None,
    performed_by_operator_id: Optional[str] = None,
    performed_by_participants: Optional[list[dict[str, str]]] = None,
) -> dict[str, Any]:
    if final_condition not in {"released", "released_with_attention", "stopped"}:
        raise HTTPException(status_code=400, detail="Condição final inválida.")
    if idempotency_key:
        existing_res = await db.execute(select(MaintenanceOrder).where(MaintenanceOrder.idempotency_key == idempotency_key))
        existing = existing_res.scalars().first()
        if existing and existing.id != order_id:
            raise HTTPException(status_code=400, detail="Chave de idempotência já utilizada em outra OM.")
        if existing and existing.execution_status == "completed":
            return {
                "status": "completed",
                "order_id": existing.id,
                "friendly_number": existing.friendly_number,
                "completed_at": iso(existing.completed_at),
                "final_condition": existing.final_condition,
                "final_sha256": existing.final_sha256,
                "pdf_path": existing.final_pdf_path,
                "final_pdf_sha256": getattr(existing, "final_pdf_sha256", None),
                "performed_by_name": getattr(existing, "performed_by_snapshot", None) or getattr(existing, "performed_by_name", None),
            }

    order = await get_order_or_404(db, order_id)
    if order.execution_status != "in_progress":
        raise HTTPException(status_code=409, detail="OM não está em execução.")
    ensure_order_reservation_allowed(order, operator_name=operator_name, device_id=device_id)
    if not (performed_by_name or "").strip():
        raise HTTPException(status_code=400, detail="Selecione quem realizou a manutenção antes de finalizar.")

    unanswered = [item for item in order.items if not item.status or item.status == "unanswered"]
    if unanswered:
        raise HTTPException(status_code=400, detail=f"Ainda existem {len(unanswered)} item(ns) sem resposta.")
    invalid_items = [
        {
            "item_id": item.item_id,
            "missing_required_fields": validation["missing_required_fields"],
        }
        for item in order.items
        for validation in [validate_order_item_response(item)]
        if not validation["ready_to_complete"]
    ]
    if invalid_items:
        summary = "; ".join(
            f"{item['item_id']}: {', '.join(item['missing_required_fields'])}"
            for item in invalid_items[:5]
        )
        raise HTTPException(
            status_code=400,
            detail=f"Existem {len(invalid_items)} item(ns) com campos obrigatórios pendentes: {summary}",
        )
    if final_condition == "released" and order.asset and not order.asset.is_operable:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Não é possível finalizar como liberada pois o ativo está marcado como parado.",
        )

    now = utcnow_naive()
    duration_mins = int((now - order.started_at).total_seconds() / 60) if order.started_at else None
    approved_count = sum(1 for item in order.items if item.status == "ok")
    repproved_count = sum(1 for item in order.items if item.status == "attention")
    na_count = sum(1 for item in order.items if item.status == "not_applicable")

    final_data = {
        "order_id": order.id,
        "friendly_number": order.friendly_number,
        "completed_at": now.isoformat(),
        "operator_name": operator_name,
        "operator_id": operator_id,
        "checked_by": {"name": operator_name, "operator_id": operator_id},
        "performed_by": {
            "name": performed_by_name,
            "operator_id": performed_by_operator_id,
            "participants": performed_by_participants or [],
        },
        "duration_mins": duration_mins,
        "final_condition": final_condition,
        "notes": notes,
        "summary": {
            "total_items": len(order.items),
            "approved": approved_count,
            "repproved": repproved_count,
            "not_applicable": na_count,
            "unanswered": 0,
        },
        "items": [
            {
                "item_id": item.item_id,
                "status": item.status,
                "notes": item.notes,
                "defect_found": item.defect_found,
                "corrected_in_place": item.corrected_in_place,
                "correction_description": item.correction_description,
                "needs_part": item.needs_part,
                "part_name": item.part_name,
                "can_operate": item.can_operate,
                "not_applicable_reason": item.not_applicable_reason,
                "answered_at": iso(item.answered_at),
                "operator_name": item.operator_name,
                "validation": validate_order_item_response(item),
            }
            for item in order.items
        ],
    }
    final_json = json.dumps(final_data, ensure_ascii=False, default=str)
    final_sha256 = hashlib.sha256(final_json.encode("utf-8")).hexdigest()

    order.execution_status = "completed"
    order.status = (
        "demo_completed"
        if getattr(order, "record_kind", "official") == "demo_test"
        else ("completed" if repproved_count == 0 and final_condition == "released" else "completed_with_issues")
    )
    order.completed_at = now
    order.duration_mins = duration_mins
    order.final_condition = final_condition
    order.notes = notes
    order.operator_name = operator_name
    order.operator_id = operator_id
    order.performed_by_name = performed_by_name
    order.performed_by_operator_id = performed_by_operator_id
    order.performed_by_snapshot = performed_by_name
    order.performed_by_participants_json = json.dumps(performed_by_participants or [], ensure_ascii=False)
    order.final_json = final_json
    order.final_sha256 = final_sha256
    order.final_revision = 1
    order.reservation_operator = None
    order.reservation_device_id = None
    order.reservation_started_at = None
    order.reservation_expires_at = None
    if idempotency_key:
        order.idempotency_key = idempotency_key

    if final_condition == "stopped" and order.asset:
        order.asset.is_operable = False
        order.machine_stopped = True
        order.machine_stopped_at = now
        db.add(
            MaintenanceIssue(
                asset_id=order.asset_id,
                order_id=order.id,
                description=f"Máquina parada registrada durante a manutenção OM nº {order.friendly_number}. Obs: {notes or 'Sem observações'}",
                priority="critical",
                is_operable_affected=True,
                status="open",
                operator_name=operator_name,
            )
        )
        db.add(
            DowntimeRecord(
                id=gen_id(),
                asset_id=order.asset_id,
                order_id=order.id,
                started_at=now,
                reason=notes or f"Parada registrada na OM {order.friendly_number}",
            )
        )

    pdf_path = None
    try:
        from app.pdf_generator import generate_complete_order_pdf

        pdf_buffer = await generate_complete_order_pdf(db, order_id)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        pdf_path_obj = REPORTS_DIR / f"OM_{order.friendly_number:04d}_v{order.final_revision}.pdf"
        pdf_path_obj.write_bytes(pdf_buffer.getvalue())
        pdf_path = str(pdf_path_obj)
        order.final_pdf_path = pdf_path
        order.final_pdf_sha256 = hashlib.sha256(pdf_path_obj.read_bytes()).hexdigest()
    except Exception as exc:
        print(f"[WARN] PDF não gerado para OM {order_id}: {exc}")

    await add_event(
        db,
        order_id,
        "completed",
        operator_name,
        {
            "completed_at": now.isoformat(),
            "duration_mins": duration_mins,
            "final_condition": final_condition,
            "final_sha256": final_sha256,
            "final_pdf_sha256": order.final_pdf_sha256,
            "checked_by": {"name": operator_name, "operator_id": operator_id},
            "performed_by": {"name": performed_by_name, "operator_id": performed_by_operator_id, "participants": performed_by_participants or []},
            "items_summary": final_data["summary"],
            "pdf_path": pdf_path,
        },
        operator_id=operator_id,
    )
    # Demonstrações ficam completas para treinamento, mas não cumprem plano
    # preventivo nem podem alterar o próximo vencimento real.
    if getattr(order, "record_kind", "official") == "official" and order.order_type == "preventive":
        await create_next_order_if_needed(db, order)
    # O encerramento nunca depende da disponibilidade do NAS. A fila é
    # persistida com a OM; se a rede cair, o dossiê continua pendente e pode
    # ser reenviado com a mesma identidade/hashes.
    from app.dossier_service import queue_order_dossier
    dossier_job = await queue_order_dossier(
        db,
        order_id,
        requested_by=operator_name,
        requested_by_operator_id=operator_id,
        device_id=device_id,
    )
    await db.commit()
    return {
        "status": "completed",
        "order_id": order_id,
        "friendly_number": order.friendly_number,
        "completed_at": now.isoformat(),
        "duration_mins": duration_mins,
        "final_condition": final_condition,
        "final_sha256": final_sha256,
        "sha256": final_sha256,
        "pdf_path": pdf_path,
        "final_pdf_sha256": order.final_pdf_sha256,
        "performed_by_name": performed_by_name,
        "performed_by_participants": performed_by_participants or [],
        "summary": final_data["summary"],
        "dossier_sync": {"job_id": dossier_job.id, "status": "pending"},
        "message": "Manutenção concluída. O PDF e o dossiê serão arquivados automaticamente.",
    }


async def create_next_order_if_needed(db: AsyncSession, order: MaintenanceOrder) -> None:
    if not order.plan_id:
        return
    plan_res = await db.execute(select(MaintenancePlan).where(MaintenancePlan.id == order.plan_id))
    plan = plan_res.scalars().first()
    if not plan or plan.recurrence_status != "confirmed":
        return
    base_planned = order.planned_date
    monthly_competence = bool(order.planned_year and order.planned_month and not order.scheduled_day_is_explicit)
    if not base_planned and order.planned_year and order.planned_month:
        base_planned = date(order.planned_year, order.planned_month, 1)
    completed_date = order.completed_at.date() if order.completed_at else local_today()
    next_date = calculate_next_date(
        planned_date=base_planned,
        completed_date=completed_date,
        periodicity=plan.periodicity,
        frequency_days=plan.frequency_days,
        frequency_months=plan.frequency_months,
        calculation_basis=plan.calculation_basis or "fixed_calendar",
    )
    if not next_date:
        return

    existing_res = await db.execute(
        select(MaintenanceOrder.id).where(
            MaintenanceOrder.plan_id == plan.id,
            MaintenanceOrder.planned_year == next_date.year,
            MaintenanceOrder.planned_month == next_date.month,
        )
    )
    if existing_res.scalars().first():
        return

    next_num = await next_friendly_number(db)
    keep_month_only = monthly_competence and (plan.calculation_basis or "fixed_calendar") == "fixed_calendar"
    next_order = MaintenanceOrder(
        id=gen_id(),
        friendly_number=next_num,
        asset_id=order.asset_id,
        plan_id=plan.id,
        checklist_version_id=plan.checklist_template_version_id,
        planned_date=None if keep_month_only else next_date,
        planned_year=next_date.year,
        planned_month=next_date.month,
        original_competence=f"{next_date.year:04d}-{next_date.month:02d}",
        scheduled_day_is_explicit=not keep_month_only,
        original_date=None if keep_month_only else next_date,
        priority=order.priority,
        status=effective_open_status(
            type(
                "TmpOrder",
                (),
                {
                    "status": "scheduled",
                    "execution_status": "not_started",
                    "scheduled_day_is_explicit": not keep_month_only,
                    "planned_date": None if keep_month_only else next_date,
                    "planned_year": next_date.year,
                    "planned_month": next_date.month,
                },
            )()
        ),
        execution_status="not_started",
        opaque_token=secrets.token_urlsafe(32),
        is_monthly_competency=keep_month_only,
        order_type="preventive",
    )
    db.add(next_order)
    await db.flush()
    await create_order_items_from_checklist(db, next_order)
    if order.asset:
        order.asset.last_maintenance_date = order.completed_at
        order.asset.next_maintenance_date = datetime(next_date.year, next_date.month, next_date.day)
    await add_event(
        db,
        order.id,
        "next_order_created",
        order.operator_name,
        {"next_order_id": next_order.id, "next_number": next_num, "competence": next_order.original_competence},
        operator_id=getattr(order, "operator_id", None),
    )


async def checklist_library_summary(db: AsyncSession) -> dict[str, Any]:
    logs_res = await db.execute(select(ChecklistImportLog).order_by(ChecklistImportLog.file_name))
    logs = logs_res.scalars().all()
    templates_count = (await db.execute(select(func.count(ChecklistTemplate.id)))).scalar() or 0
    versions_count = (await db.execute(select(func.count(ChecklistTemplateVersion.id)))).scalar() or 0
    status_counts: dict[str, int] = {}
    for log in logs:
        status_counts[log.status] = status_counts.get(log.status, 0) + 1
    return {
        "files_analyzed": len(logs),
        "imported": status_counts.get("imported", 0),
        "duplicates": status_counts.get("duplicate", 0) + status_counts.get("skipped", 0),
        "conflicts": status_counts.get("conflict", 0),
        "errors": status_counts.get("error", 0),
        "documents_to_review": status_counts.get("review", 0) + status_counts.get("ambiguous", 0) + status_counts.get("to_review", 0),
        "models": templates_count,
        "versions": versions_count,
        "status_counts": status_counts,
        "files": [
            {
                "file_name": log.file_name,
                "file_path": log.file_path,
                "file_hash": log.file_hash,
                "rq_cmp_number": log.rq_cmp_number,
                "year": log.year,
                "version": log.version,
                "title": log.title,
                "status": log.status,
                "classification": log.classification,
                "conflicts": json.loads(log.conflicts_json or "[]"),
                "checklist_template_id": log.checklist_template_id,
                "checklist_version_id": log.checklist_version_id,
                "imported_at": iso(log.imported_at),
            }
            for log in logs
        ],
    }
