from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import utcnow_naive
from app.database import get_db
from app.security_service import resolve_actor, require_permission
from app import order_execution_service
from app.operator_service import resolve_maintenance_executor

router = APIRouter(prefix="/v2/offline", tags=["offline-sync"])

class OfflineOperationIn(BaseModel):
    id: str = Field(..., description="UUID/idempotency key gerado no dispositivo")
    type: str
    order_id: Optional[str] = None
    entity_name: Optional[str] = None
    entity_id: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None

class OfflineSyncBatch(BaseModel):
    operations: list[OfflineOperationIn]
    selected_user_id: Optional[str] = None
    operator_name: Optional[str] = None
    device_id: Optional[str] = None
    dry_run: bool = False

async def _table_exists(db: AsyncSession, name: str) -> bool:
    try:
        return bool((await db.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"), {"name": name})).scalar())
    except Exception:
        return False

async def _existing(db: AsyncSession, op_id: str) -> Optional[dict[str, Any]]:
    if not await _table_exists(db, "offline_sync_operations"):
        return None
    row = (await db.execute(text("SELECT * FROM offline_sync_operations WHERE client_op_id=:id"), {"id": op_id})).mappings().first()
    return dict(row) if row else None

async def _insert_or_update(
    db: AsyncSession,
    *,
    op: OfflineOperationIn,
    status: str,
    response: Any = None,
    error: Optional[str] = None,
    operator_name: Optional[str] = None,
    selected_user_id: Optional[str] = None,
    device_id: Optional[str] = None,
) -> None:
    if not await _table_exists(db, "offline_sync_operations"):
        return
    now = utcnow_naive()
    existing = await _existing(db, op.id)
    params = {
        "id": existing["id"] if existing else str(uuid.uuid4()),
        "client_op_id": op.id,
        "operation_type": op.type,
        "order_id": op.order_id,
        "entity_name": op.entity_name,
        "entity_id": op.entity_id,
        "payload_json": json.dumps(op.payload, ensure_ascii=False),
        "response_json": json.dumps(response, ensure_ascii=False, default=str) if response is not None else None,
        "status": status,
        "last_error": error,
        "operator_name": operator_name,
        "selected_user_id": selected_user_id,
        "device_id": device_id,
        "created_at": op.created_at or now.isoformat(),
        "received_at": now,
        "applied_at": now if status in {"applied", "dry_run_ok", "duplicate"} else None,
    }
    if existing:
        await db.execute(text("""
            UPDATE offline_sync_operations
               SET status=:status, response_json=:response_json, last_error=:last_error,
                   attempts=attempts+1, applied_at=:applied_at, received_at=:received_at
             WHERE client_op_id=:client_op_id
        """), params)
    else:
        await db.execute(text("""
            INSERT INTO offline_sync_operations(
                id, client_op_id, operation_type, order_id, entity_name, entity_id,
                payload_json, response_json, status, attempts, last_error,
                operator_name, selected_user_id, device_id, created_at, received_at, applied_at
            ) VALUES (
                :id, :client_op_id, :operation_type, :order_id, :entity_name, :entity_id,
                :payload_json, :response_json, :status, 1, :last_error,
                :operator_name, :selected_user_id, :device_id, :created_at, :received_at, :applied_at
            )
        """), params)

async def _apply_operation(db: AsyncSession, op: OfflineOperationIn, *, operator_name: str, operator_id: Optional[str], device_id: Optional[str]) -> Any:
    payload = dict(op.payload or {})
    order_id = op.order_id or payload.get("order_id")
    if op.type in {"epi_confirm", "confirm_epi"}:
        if not order_id:
            raise HTTPException(status_code=400, detail="order_id obrigatório para epi_confirm")
        return await order_execution_service.confirm_epi(
            db=db,
            order_id=order_id,
            operator_name=operator_name,
            operator_id=operator_id,
            confirmed=bool(payload.get("confirmed", True)),
            missing_items=payload.get("missing_items"),
            updated_items=payload.get("updated_items"),
            save_as_default=bool(payload.get("save_as_default", False)),
        )
    if op.type in {"start_order", "order_start"}:
        if not order_id:
            raise HTTPException(status_code=400, detail="order_id obrigatório para start_order")
        return await order_execution_service.start_order(
            db=db,
            order_id=order_id,
            operator_name=operator_name,
            operator_id=operator_id,
            device_id=device_id or payload.get("device_id"),
        )
    if op.type in {"answer_item", "order_item_answer"}:
        if not order_id:
            raise HTTPException(status_code=400, detail="order_id obrigatório para answer_item")
        return await order_execution_service.answer_item(
            db=db,
            order_id=order_id,
            item_id=str(payload.get("item_id") or payload.get("itemId") or ""),
            result=str(payload.get("result") or payload.get("status") or "unanswered"),
            operator_name=operator_name,
            operator_id=operator_id,
            notes=payload.get("notes"),
            defect_found=payload.get("defect_found"),
            corrected_in_place=payload.get("corrected_in_place"),
            correction_description=payload.get("correction_description"),
            needs_part=payload.get("needs_part"),
            part_name=payload.get("part_name"),
            can_operate=payload.get("can_operate"),
            not_applicable_reason=payload.get("not_applicable_reason"),
            audio_transcript=payload.get("audio_transcript"),
            photo_category=payload.get("photo_category"),
            device_id=device_id or payload.get("device_id"),
        )
    if op.type in {"complete_order", "order_complete"}:
        if not order_id:
            raise HTTPException(status_code=400, detail="order_id obrigatório para complete_order")
        performer_id = str(payload.get("performed_by_operator_id") or "").strip()
        if not performer_id:
            raise HTTPException(status_code=400, detail="Selecione quem realizou a manutenção antes de sincronizar a conclusão.")
        performer = await resolve_maintenance_executor(db, performer_id)
        participant_ids = list(dict.fromkeys(str(value) for value in (payload.get("performed_by_participant_ids") or []) if str(value) and str(value) != performer.id))
        participants = []
        for participant_id in participant_ids:
            participant = await resolve_maintenance_executor(db, participant_id)
            participants.append({"id": participant.id, "name": participant.name})
        return await order_execution_service.complete_order(
            db=db,
            order_id=order_id,
            operator_name=operator_name,
            operator_id=operator_id,
            final_condition=str(payload.get("final_condition") or "released"),
            notes=payload.get("notes"),
            idempotency_key=str(payload.get("idempotency_key") or op.id),
            device_id=device_id or payload.get("device_id"),
            performed_by_name=performer.name,
            performed_by_operator_id=performer.id,
            performed_by_participants=participants,
        )
    return {"pending": True, "message": "Tipo de operação preservado para conferência manual.", "type": op.type}

@router.get("/status")
async def offline_status(db: AsyncSession = Depends(get_db)):
    if not await _table_exists(db, "offline_sync_operations"):
        return {"available": False, "reason": "migration_190_not_applied"}
    rows = (await db.execute(text("""
        SELECT status, count(*) AS total
          FROM offline_sync_operations
         GROUP BY status
         ORDER BY status
    """))).mappings().all()
    recent = (await db.execute(text("""
        SELECT client_op_id, operation_type, order_id, status, attempts, last_error, received_at, applied_at
          FROM offline_sync_operations
         ORDER BY received_at DESC
         LIMIT 25
    """))).mappings().all()
    return {"available": True, "counts": [dict(r) for r in rows], "recent": [dict(r) for r in recent]}

@router.post("/sync")
async def sync_batch(req: OfflineSyncBatch, db: AsyncSession = Depends(get_db)):
    actor = await resolve_actor(db, selected_user_id=req.selected_user_id, operator_name=req.operator_name)
    require_permission(actor, "offline:sync")
    if len(req.operations) > 200:
        raise HTTPException(status_code=413, detail="Lote offline limitado a 200 operações por envio.")
    if not await _table_exists(db, "offline_sync_operations"):
        return {"accepted": False, "schema_missing": True, "message": "Rode as migrations pendentes antes de sincronizar offline."}

    results: list[dict[str, Any]] = []
    for op in req.operations:
        existing = await _existing(db, op.id)
        if existing and existing.get("status") in {"applied", "dry_run_ok", "duplicate"}:
            results.append({"id": op.id, "status": existing.get("status"), "idempotent": True, "response": json.loads(existing.get("response_json") or "null")})
            continue
        if req.dry_run:
            await _insert_or_update(db, op=op, status="dry_run_ok", response={"validated": True}, operator_name=actor.operator_name, selected_user_id=actor.operator_id, device_id=req.device_id)
            await db.commit()
            results.append({"id": op.id, "status": "dry_run_ok"})
            continue
        try:
            response = await _apply_operation(
                db,
                op,
                operator_name=actor.operator_name or req.operator_name or "Offline",
                operator_id=actor.operator_id,
                device_id=req.device_id or (op.payload or {}).get("device_id"),
            )
            status_value = "pending" if isinstance(response, dict) and response.get("pending") else "applied"
            await _insert_or_update(db, op=op, status=status_value, response=response, operator_name=actor.operator_name, selected_user_id=actor.operator_id, device_id=req.device_id)
            await db.commit()
            results.append({"id": op.id, "status": status_value, "response": response})
        except Exception as exc:
            await db.rollback()
            detail = getattr(exc, "detail", None) or str(exc)
            await _insert_or_update(db, op=op, status="failed", error=str(detail), operator_name=actor.operator_name, selected_user_id=actor.operator_id, device_id=req.device_id)
            await db.commit()
            results.append({"id": op.id, "status": "failed", "error": str(detail)})
    return {"accepted": True, "total": len(results), "results": results}
