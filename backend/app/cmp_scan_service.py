"""Registro e fila de conferência de CMP fotografado.

O fluxo salva arquivos em storage controlado e cria um manifesto auditável.
OCR/visão pesada não rodam dentro da requisição HTTP; quando indisponíveis, o
registro fica como needs_review para conferência humana.
"""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Iterable, Optional

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageStat, UnidentifiedImageError

from app.asset_file_service import copy_stream_to_temp, safe_relative, sha256_path, sniff_file, resolve_internal_path
from app.clock import utcnow_naive
from app.config import DATA_ROOT

CMP_ROOT = DATA_ROOT / "storage" / "cmp_scans"
INDEX_PATH = CMP_ROOT / "index.json"
ALLOWED_CMP_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}


def _read_index() -> list[dict[str, Any]]:
    CMP_ROOT.mkdir(parents=True, exist_ok=True)
    if not INDEX_PATH.exists():
        return []
    try:
        data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _write_index(items: list[dict[str, Any]]) -> None:
    CMP_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = INDEX_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(INDEX_PATH)


def _analyze_image(path: Path) -> dict[str, Any]:
    try:
        with Image.open(path) as image:
            image.load()
            gray = image.convert("L")
            stat = ImageStat.Stat(gray)
            contrast = float(stat.stddev[0])
            width, height = image.size
            return {
                "kind": "image",
                "width": width,
                "height": height,
                "contrast": round(contrast, 2),
                "focus_status": "acceptable" if width >= 900 and height >= 900 and contrast >= 22 else "needs_review",
                "sheet_structure": "candidate_cmp" if width >= 900 and height >= 900 else "unknown",
            }
    except (UnidentifiedImageError, OSError):
        return {"kind": "image", "sheet_structure": "unknown", "focus_status": "needs_review"}


def _analyze_file(path: Path, mime_type: str) -> dict[str, Any]:
    if mime_type.startswith("image/"):
        return _analyze_image(path)
    if mime_type == "application/pdf":
        return {"kind": "pdf", "sheet_structure": "candidate_cmp", "focus_status": "not_applicable"}
    return {"kind": "file", "sheet_structure": "unknown", "focus_status": "needs_review"}


async def create_cmp_scan(
    *,
    uploads: Iterable[UploadFile],
    order_id: Optional[str],
    operator_name: Optional[str],
    selected_user_id: Optional[str],
    device_id: Optional[str],
    expected_responsible: Optional[str] = None,
    expected_execution_date: Optional[str] = None,
    db: Any = None,
) -> dict[str, Any]:
    upload_list = list(uploads)
    if not upload_list:
        raise HTTPException(status_code=400, detail="Nenhum arquivo enviado.")

    scan_id = str(uuid.uuid4())
    now = utcnow_naive().isoformat()
    target_dir = CMP_ROOT / scan_id
    target_dir.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, Any]] = []
    analyses: list[dict[str, Any]] = []
    extraction_items: list[dict[str, Any]] = []
    extraction_fields: dict[str, Any] = {}
    extraction_warnings: list[str] = []
    qr_status = "not_detected"
    vision_status = "not_run"
    suggested_order_id = order_id
    suggested_asset_id: Optional[str] = None

    for idx, upload in enumerate(upload_list):
        original_name = Path(upload.filename or f"cmp_{idx + 1}.jpg").name
        if not original_name or original_name in {".", ".."} or Path(original_name).is_absolute():
            raise HTTPException(status_code=400, detail="Nome de arquivo inválido.")
        temp_path = copy_stream_to_temp(upload.file, original_name, DATA_ROOT / "temp" / "cmp_uploads")
        try:
            mime_type, extension, width, height = sniff_file(temp_path)
            if extension not in ALLOWED_CMP_EXTENSIONS:
                raise HTTPException(status_code=400, detail="CMP fotografado aceita somente imagem ou PDF.")
            digest = sha256_path(temp_path)
            stored = target_dir / f"{idx + 1:02d}_{digest}{extension}"
            shutil.copy2(temp_path, stored)
            relative = safe_relative(stored)
            analysis = _analyze_file(stored, mime_type)
            if db is not None and mime_type.startswith("image/"):
                try:
                    from app.vision import process_sheet_photo

                    vision_result = await process_sheet_photo(stored.read_bytes(), original_name, db)
                    vision_status = "completed"
                    if vision_result.get("qr_detected"):
                        qr_status = "detected"
                    if vision_result.get("order_id"):
                        suggested_order_id = vision_result.get("order_id")
                    if vision_result.get("asset_id"):
                        suggested_asset_id = vision_result.get("asset_id")
                    extraction_fields.update({
                        "order_id": vision_result.get("order_id"),
                        "patrimonio": vision_result.get("patrimonio"),
                        "asset_description": vision_result.get("asset_description"),
                        "date": vision_result.get("date"),
                        "operator_name": vision_result.get("operator_name"),
                        "materials": vision_result.get("materials"),
                        "final_condition": vision_result.get("final_condition"),
                        "provider": vision_result.get("provider"),
                        "opencv_used": vision_result.get("opencv_used"),
                        "ia_used": vision_result.get("ia_used"),
                        "qr_data": vision_result.get("qr_data"),
                        "ocr_method": vision_result.get("ocr_method"),
                        "ocr_text": vision_result.get("ocr_text"),
                        "friendly_number_detected": vision_result.get("friendly_number_detected"),
                    })
                    extraction_items = vision_result.get("items") or extraction_items
                    extraction_warnings.extend(vision_result.get("warnings") or [])
                    analysis["vision_provider"] = vision_result.get("provider")
                    analysis["qr_detected"] = bool(vision_result.get("qr_detected"))
                    analysis["perspective_or_omr"] = "attempted"
                except Exception as exc:
                    vision_status = "failed"
                    extraction_warnings.append(f"Visão local falhou: {exc}")
            analyses.append(analysis)
            files.append({
                "name": original_name,
                "internal_path": relative,
                "sha256": digest,
                "mime_type": mime_type,
                "extension": extension,
                "size_bytes": stored.stat().st_size,
                "width": width,
                "height": height,
                "content_url": f"/v2/cmp/scans/{scan_id}/files/{idx}",
            })
        finally:
            temp_path.unlink(missing_ok=True)

    record = {
        "id": scan_id,
        "status": "needs_review",
        "created_at": now,
        "updated_at": now,
        "order_id": order_id,
        "suggested_order_id": suggested_order_id,
        "suggested_asset_id": suggested_asset_id,
        "operator_name": operator_name,
        "selected_user_id": selected_user_id,
        "device_id": device_id,
        "expected_responsible": expected_responsible,
        "expected_execution_date": expected_execution_date,
        "original_name": files[0]["name"] if len(files) == 1 else f"{len(files)} arquivos CMP",
        "confidence": 0.55 if extraction_items or qr_status == "detected" else (0.25 if any(a.get("sheet_structure") == "candidate_cmp" for a in analyses) else 0.05),
        "files": files,
        "extraction": {
            "qr_status": qr_status,
            "vision_status": vision_status,
            "ocr_status": "not_run_in_http_request",
            "image_analysis": analyses,
            "raw_fields": extraction_fields,
            "items": extraction_items,
            "human_corrections": {},
            "warnings": extraction_warnings,
            "message": "Imagem salva para conferência. O sistema tenta identificar OM, ativo e marcações; confira antes de aplicar.",
        },
        "audit": [
            {
                "at": now,
                "event": "created",
                "operator_name": operator_name,
                "selected_user_id": selected_user_id,
                "device_id": device_id,
            }
        ],
    }
    index = _read_index()
    index.insert(0, record)
    _write_index(index)
    return record


def list_cmp_scans(*, order_id: Optional[str] = None, status: Optional[str] = None, limit: int = 50) -> dict[str, Any]:
    items = _read_index()
    if order_id:
        items = [item for item in items if item.get("order_id") == order_id or item.get("suggested_order_id") == order_id]
    if status:
        items = [item for item in items if item.get("status") == status]
    return {"items": items[: max(1, min(limit, 200))], "total": len(items)}


def get_cmp_scan(scan_id: str) -> dict[str, Any]:
    for item in _read_index():
        if item.get("id") == scan_id:
            return item
    raise HTTPException(status_code=404, detail="CMP digitalizado não encontrado.")


def update_cmp_scan_review(
    scan_id: str,
    *,
    status: str,
    selected_user_id: Optional[str],
    operator_name: Optional[str],
    corrections: Optional[dict[str, Any]] = None,
    notes: Optional[str] = None,
) -> dict[str, Any]:
    if status not in {"needs_review", "draft_saved", "approved", "rejected"}:
        raise HTTPException(status_code=400, detail="Status de revisão inválido.")
    index = _read_index()
    now = utcnow_naive().isoformat()
    for item in index:
        if item.get("id") == scan_id:
            item["status"] = status
            item["updated_at"] = now
            item.setdefault("extraction", {}).setdefault("human_corrections", {}).update(corrections or {})
            item["review_notes"] = notes
            item["reviewed_at"] = now
            item["reviewed_by_operator_id"] = selected_user_id
            item["reviewed_by_name"] = operator_name
            item.setdefault("audit", []).append({
                "at": now,
                "event": f"review_{status}",
                "operator_name": operator_name,
                "selected_user_id": selected_user_id,
            })
            _write_index(index)
            return item
    raise HTTPException(status_code=404, detail="CMP digitalizado não encontrado.")


def resolve_cmp_scan_file(scan_id: str, file_index: int) -> Path:
    item = get_cmp_scan(scan_id)
    files = item.get("files") or []
    if file_index < 0 or file_index >= len(files):
        raise HTTPException(status_code=404, detail="Arquivo do CMP não encontrado.")
    return resolve_internal_path(files[file_index]["internal_path"])
