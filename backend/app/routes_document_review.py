from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.clock import utcnow_naive
from app.database import get_db
from app.document_text import extract_text
from app.models import Asset, AssetDocument, AssetDocumentIndex, DocumentOcrJob, FileReviewItem
from app.search_service import rebuild_search_index, upsert_search_document
from app.security_service import resolve_actor, require_permission

router = APIRouter(prefix="/v2/document-review", tags=["document-review"])

class ReviewDecision(BaseModel):
    action: str
    selected_asset_id: Optional[str] = None
    category: Optional[str] = None
    notes: Optional[str] = None
    operator_name: Optional[str] = None
    selected_user_id: Optional[str] = None

class OcrJobCreate(BaseModel):
    source_kind: str
    source_id: Optional[str] = None
    file_path: Optional[str] = None
    run_now: bool = False
    operator_name: Optional[str] = None
    selected_user_id: Optional[str] = None

async def _table_exists(db: AsyncSession, name: str) -> bool:
    try:
        return bool((await db.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"), {"name": name})).scalar())
    except Exception:
        return False


def _sha_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _serialize_review_item(item: FileReviewItem) -> dict[str, Any]:
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
        "possible_assets": json.loads(item.possible_assets_json or "[]"),
        "suggested_asset_id": item.suggested_asset_id,
        "selected_asset_id": item.selected_asset_id,
        "document_id": item.document_id,
        "resolved_by_name": item.resolved_by_name,
        "resolved_at": item.resolved_at.isoformat() if item.resolved_at else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }

@router.get("/summary")
async def review_summary(db: AsyncSession = Depends(get_db)):
    file_rows = []
    if await _table_exists(db, "file_review_items"):
        file_rows = (await db.execute(text("SELECT status, count(*) AS total FROM file_review_items GROUP BY status ORDER BY status"))).mappings().all()
    ocr_rows = []
    if await _table_exists(db, "document_ocr_jobs"):
        ocr_rows = (await db.execute(text("SELECT status, count(*) AS total FROM document_ocr_jobs GROUP BY status ORDER BY status"))).mappings().all()
    pending_docs = 0
    if await _table_exists(db, "asset_documents"):
        pending_docs = int((await db.execute(text("SELECT count(*) FROM asset_documents WHERE coalesce(review_status,'') IN ('','pending','review','conflict')"))).scalar() or 0)
    return {"file_review": [dict(r) for r in file_rows], "ocr_jobs": [dict(r) for r in ocr_rows], "asset_documents_pending_review": pending_docs}

@router.get("/items")
async def review_items(status: str = "pending", limit: int = 50, db: AsyncSession = Depends(get_db)):
    if not await _table_exists(db, "file_review_items"):
        return {"items": [], "total": 0, "schema_missing": True}
    q = select(FileReviewItem)
    if status != "all":
        q = q.where(FileReviewItem.status == status)
    rows = (await db.execute(q.order_by(FileReviewItem.created_at.desc()).limit(max(1, min(limit, 200))))).scalars().all()
    return {"items": [_serialize_review_item(i) for i in rows], "total": len(rows)}

@router.post("/items/{item_id}/decision")
async def decide_review_item(item_id: str, req: ReviewDecision, db: AsyncSession = Depends(get_db)):
    actor = await resolve_actor(db, selected_user_id=req.selected_user_id, operator_name=req.operator_name)
    require_permission(actor, "documents:review")
    item = (await db.execute(select(FileReviewItem).where(FileReviewItem.id == item_id))).scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="Item de revisão não encontrado.")
    action = req.action.strip().lower()
    now = utcnow_naive()

    if action in {"approve", "link", "approve_as_asset"}:
        asset_id = req.selected_asset_id or item.selected_asset_id or item.suggested_asset_id
        if not asset_id:
            raise HTTPException(status_code=400, detail="selected_asset_id é obrigatório para aprovar/vincular documento.")
        asset = (await db.execute(select(Asset).where(Asset.id == asset_id))).scalars().first()
        if not asset:
            raise HTTPException(status_code=404, detail="Ativo selecionado não encontrado.")
        doc = AssetDocument(
            id=str(uuid.uuid4()),
            asset_id=asset_id,
            name=item.file_name,
            file_path=item.source_path,
            original_name=item.file_name,
            extension=item.extension,
            mime_type=item.mime_type,
            file_size=item.file_size,
            file_hash=item.file_hash,
            category=req.category or "document",
            origin="review_queue",
            original_path=item.source_path,
            uploaded_by=actor.operator_name,
            uploaded_by_operator_id=actor.operator_id,
            status="active",
            review_status="approved",
            resolved_by_operator_id=actor.operator_id,
            resolved_at=now,
            review_reason=req.notes,
        )
        db.add(doc)
        item.document_id = doc.id
        item.selected_asset_id = asset_id
        item.status = "resolved"
    elif action in {"duplicate", "ignore", "conflict"}:
        item.status = action
    else:
        raise HTTPException(status_code=400, detail="Ação inválida. Use approve, duplicate, ignore ou conflict.")

    item.resolved_by_operator_id = actor.operator_id
    item.resolved_by_name = actor.operator_name
    item.resolved_at = now
    item.updated_at = now
    item.reason_message = req.notes or item.reason_message
    await db.commit()
    return {"updated": True, "item": _serialize_review_item(item)}

async def _resolve_file_for_job(db: AsyncSession, req: OcrJobCreate) -> tuple[str, str, Optional[str]]:
    if req.file_path:
        raise HTTPException(
            status_code=400,
            detail="OCR aceita apenas arquivos já registrados. Envie source_kind/source_id, não file_path.",
        )
    if req.source_kind == "file_review_item" and req.source_id:
        item = (await db.execute(select(FileReviewItem).where(FileReviewItem.id == req.source_id))).scalars().first()
        if not item:
            raise HTTPException(status_code=404, detail="Item de revisão não encontrado.")
        return req.source_kind, item.source_path, item.file_hash or _sha_file(Path(item.source_path))
    if req.source_kind == "asset_document" and req.source_id:
        doc = (await db.execute(select(AssetDocument).where(AssetDocument.id == req.source_id))).scalars().first()
        if not doc:
            raise HTTPException(status_code=404, detail="Documento não encontrado.")
        return req.source_kind, doc.file_path, doc.file_hash or _sha_file(Path(doc.file_path))
    raise HTTPException(status_code=400, detail="Informe source_kind/source_id válido.")

async def _run_ocr_job(db: AsyncSession, job: DocumentOcrJob) -> dict[str, Any]:
    job.status = "running"
    job.started_at = utcnow_naive()
    job.attempt = int(job.attempt or 0) + 1
    await db.flush()
    text_value, method, needs_review, error = extract_text(job.file_path)
    job.method = method
    job.extracted_text = text_value
    job.needs_review = bool(needs_review)
    job.error_message = error
    job.status = "completed" if text_value else ("needs_review" if needs_review else "failed")
    job.completed_at = utcnow_naive()

    if text_value and job.source_kind == "asset_document" and job.source_id:
        doc = (await db.execute(select(AssetDocument).where(AssetDocument.id == job.source_id))).scalars().first()
        if doc:
            # Espelha texto em índice legado para busca e futura busca semântica.
            existing = (await db.execute(select(AssetDocumentIndex).where(AssetDocumentIndex.file_hash == (doc.file_hash or job.file_hash)))).scalars().first() if (doc.file_hash or job.file_hash) else None
            if existing:
                existing.extracted_text = text_value
                existing.extraction_method = method
                existing.needs_review = bool(needs_review)
                existing.indexed_at = utcnow_naive()
            else:
                db.add(AssetDocumentIndex(
                    id=str(uuid.uuid4()),
                    asset_id=doc.asset_id,
                    file_path=doc.file_path,
                    file_name=doc.name or doc.original_name or Path(doc.file_path).name,
                    file_extension=(doc.extension or Path(doc.file_path).suffix or "").lower()[:10],
                    file_size=doc.file_size or 0,
                    file_hash=doc.file_hash or job.file_hash or "",
                    document_type=doc.category or "document",
                    extracted_text=text_value,
                    extraction_method=method,
                    needs_review=bool(needs_review),
                    indexed_at=utcnow_naive(),
                ))
    await db.commit()
    try:
        await rebuild_search_index(db)
    except Exception:
        pass
    return {"job_id": job.id, "status": job.status, "method": job.method, "has_text": bool(job.extracted_text), "needs_review": job.needs_review, "error": job.error_message}

@router.post("/ocr/jobs")
async def create_ocr_job(req: OcrJobCreate, db: AsyncSession = Depends(get_db)):
    actor = await resolve_actor(db, selected_user_id=req.selected_user_id, operator_name=req.operator_name)
    require_permission(actor, "documents:review")
    if not await _table_exists(db, "document_ocr_jobs"):
        return {"created": False, "schema_missing": True, "message": "Rode as migrations pendentes antes de revisar documentos."}
    source_kind, file_path, file_hash = await _resolve_file_for_job(db, req)
    job = DocumentOcrJob(
        id=str(uuid.uuid4()),
        source_kind=source_kind,
        source_id=req.source_id,
        file_path=file_path,
        file_hash=file_hash,
        status="pending",
        created_by=actor.operator_name,
        created_at=utcnow_naive(),
    )
    db.add(job)
    await db.commit()
    if req.run_now:
        return {
            "created": True,
            "job_id": job.id,
            "status": job.status,
            "queued": True,
            "message": "Job OCR criado. Execute pelo worker ou por /v2/document-review/ocr/jobs/{job_id}/run.",
        }
    return {"created": True, "job_id": job.id, "status": job.status}

@router.get("/ocr/jobs")
async def list_ocr_jobs(status: str = "all", limit: int = 50, db: AsyncSession = Depends(get_db)):
    if not await _table_exists(db, "document_ocr_jobs"):
        return {"items": [], "schema_missing": True}
    q = select(DocumentOcrJob)
    if status != "all":
        q = q.where(DocumentOcrJob.status == status)
    rows = (await db.execute(q.order_by(DocumentOcrJob.created_at.desc()).limit(max(1, min(limit, 200))))).scalars().all()
    return {"items": [
        {
            "id": j.id, "source_kind": j.source_kind, "source_id": j.source_id,
            "file_path": j.file_path, "status": j.status, "method": j.method,
            "needs_review": j.needs_review, "error_message": j.error_message,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "completed_at": j.completed_at.isoformat() if j.completed_at else None,
            "text_preview": (j.extracted_text or "")[:300],
        }
        for j in rows
    ]}

@router.post("/ocr/jobs/{job_id}/run")
async def run_ocr_job(job_id: str, operator_name: Optional[str] = None, selected_user_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    actor = await resolve_actor(db, selected_user_id=selected_user_id, operator_name=operator_name)
    require_permission(actor, "documents:review")
    job = (await db.execute(select(DocumentOcrJob).where(DocumentOcrJob.id == job_id))).scalars().first()
    if not job:
        raise HTTPException(status_code=404, detail="Job OCR não encontrado.")
    return await _run_ocr_job(db, job)
