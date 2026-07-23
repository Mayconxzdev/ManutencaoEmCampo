from __future__ import annotations

import hashlib
import mimetypes
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Optional

from fastapi import HTTPException, UploadFile, status
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import utcnow_naive
from app.config import DATA_ROOT
from app.file_limits import get_limit_for_name, get_limit_for_path
from app.models import Asset, AssetDocument

STORAGE_ROOT = DATA_ROOT / "storage"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".pptx", ".txt", ".csv"}
MEDIA_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".ogg", ".mp3", ".wav", ".m4a"}
ALLOWED_EXTENSIONS = IMAGE_EXTENSIONS | DOCUMENT_EXTENSIONS | MEDIA_EXTENSIONS


def gen_id() -> str:
    return str(uuid.uuid4())


def safe_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(DATA_ROOT.resolve()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Arquivo fora do armazenamento controlado.") from exc


def resolve_internal_path(relative_path: str) -> Path:
    if not relative_path or Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
        raise HTTPException(status_code=400, detail="Caminho interno inválido.")
    path = (DATA_ROOT / relative_path).resolve()
    try:
        path.relative_to(DATA_ROOT.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Caminho interno fora do armazenamento.") from exc
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado no armazenamento.")
    return path


def sniff_file(path: Path) -> tuple[str, str, Optional[int], Optional[int]]:
    suffix = path.suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Tipo de arquivo não permitido.")

    with path.open("rb") as fh:
        header = fh.read(16)

    if suffix in {".jpg", ".jpeg"} and not header.startswith(b"\xff\xd8\xff"):
        raise HTTPException(status_code=400, detail="Imagem JPG inválida ou corrompida.")
    if suffix == ".png" and not header.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=400, detail="Imagem PNG inválida ou corrompida.")
    if suffix == ".pdf" and not header.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="PDF inválido ou corrompido.")
    if suffix in {".docx", ".xlsx", ".pptx"} and not header.startswith(b"PK"):
        raise HTTPException(status_code=400, detail="Documento Office inválido ou corrompido.")
    if suffix == ".mp4" and b"ftyp" not in header:
        raise HTTPException(status_code=400, detail="Vídeo MP4 inválido ou corrompido.")
    if suffix in {".webm", ".mkv"} and not header.startswith(b"\x1aE\xdf\xa3"):
        raise HTTPException(status_code=400, detail="Mídia WEBM/MKV inválida ou corrompida.")
    if suffix == ".ogg" and not header.startswith(b"OggS"):
        raise HTTPException(status_code=400, detail="Áudio OGG inválido ou corrompido.")
    if suffix == ".wav" and not (header.startswith(b"RIFF") and header[8:12] == b"WAVE"):
        raise HTTPException(status_code=400, detail="Áudio WAV inválido ou corrompido.")
    if suffix == ".mp3" and not (header.startswith(b"ID3") or (len(header) > 1 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0)):
        raise HTTPException(status_code=400, detail="Áudio MP3 inválido ou corrompido.")
    if suffix == ".m4a" and b"ftyp" not in header:
        raise HTTPException(status_code=400, detail="Áudio M4A inválido ou corrompido.")

    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    width = height = None
    if suffix in IMAGE_EXTENSIONS:
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                width, height = image.size
                mime_type = Image.MIME.get(image.format, mime_type)
        except UnidentifiedImageError as exc:
            raise HTTPException(status_code=400, detail="Imagem inválida ou corrompida.") from exc
    return mime_type, suffix, width, height


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def category_for(path: Path, mime_type: str, requested: Optional[str] = None) -> str:
    if requested:
        return requested
    suffix = path.suffix.lower()
    name = path.name.lower()
    if suffix in IMAGE_EXTENSIONS or mime_type.startswith("image/"):
        return "photo"
    if "manual" in name:
        return "manual"
    if "garantia" in name:
        return "warranty"
    if "laudo" in name or "certificado" in name:
        return "certificate"
    if "nota" in name or "comprovante" in name:
        return "receipt"
    return "other"


def copy_stream_to_temp(stream: BinaryIO, original_name: str, temp_dir: Path) -> Path:
    temp_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(original_name).suffix.lower()
    temp_path = temp_dir / f"{gen_id()}{suffix}"
    max_file_size = get_limit_for_name(original_name)
    total = 0
    with temp_path.open("wb") as out:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            total += len(chunk)
            if total > max_file_size:
                temp_path.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail=f"Arquivo excede o limite configurado para este tipo ({max_file_size} bytes).")
            out.write(chunk)
    return temp_path


def make_thumbnail(original: Path, destination: Path) -> tuple[Optional[str], Optional[int], Optional[int]]:
    if original.suffix.lower() not in IMAGE_EXTENSIONS:
        return None, None, None
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(original) as image:
        image.thumbnail((360, 360))
        if image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        image.save(destination, "JPEG", quality=82)
    with Image.open(original) as source:
        width, height = source.size
    return safe_relative(destination), width, height


async def ensure_asset(db: AsyncSession, asset_id: str) -> Asset:
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalars().first()
    if not asset:
        raise HTTPException(status_code=404, detail="Ativo não encontrado.")
    return asset


async def store_asset_file(
    db: AsyncSession,
    *,
    asset_id: str,
    source_path: Path,
    original_name: Optional[str] = None,
    category: Optional[str] = None,
    origin: str = "upload",
    uploaded_by: Optional[str] = None,
    uploaded_by_operator_id: Optional[str] = None,
    source_index_id: Optional[str] = None,
    review_status: str = "linked",
    suggested_asset_id: Optional[str] = None,
    set_primary_if_first: bool = True,
) -> AssetDocument:
    await ensure_asset(db, asset_id)
    source_path = source_path.resolve()
    if not source_path.exists() or not source_path.is_file():
        raise HTTPException(status_code=404, detail="Arquivo de origem não encontrado.")
    max_file_size = get_limit_for_path(source_path)
    if source_path.stat().st_size > max_file_size:
        raise HTTPException(status_code=400, detail=f"Arquivo excede o limite configurado para este tipo ({max_file_size} bytes).")

    mime_type, extension, width, height = sniff_file(source_path)
    file_hash = sha256_path(source_path)
    original_name = original_name or source_path.name
    doc_category = category_for(source_path, mime_type, category)

    duplicate_res = await db.execute(
        select(AssetDocument).where(
            AssetDocument.file_hash == file_hash,
            AssetDocument.internal_path.isnot(None),
        )
    )
    duplicate = duplicate_res.scalars().first()
    if duplicate and duplicate.internal_path:
        internal_rel = duplicate.internal_path
        thumbnail_rel = duplicate.thumbnail_path
    else:
        base = STORAGE_ROOT / "assets" / asset_id
        subdir = "originals" if doc_category == "photo" else "documents"
        target_dir = base / subdir
        target_dir.mkdir(parents=True, exist_ok=True)
        internal = target_dir / f"{file_hash}{extension}"
        if not internal.exists():
            shutil.copy2(source_path, internal)
        internal_rel = safe_relative(internal)
        thumbnail_rel = None
        if doc_category == "photo":
            thumbnail = base / "thumbnails" / f"{file_hash}.jpg"
            thumbnail_rel, width, height = make_thumbnail(internal, thumbnail)

    primary_count = await db.execute(
        select(AssetDocument.id).where(
            AssetDocument.asset_id == asset_id,
            AssetDocument.status == "active",
            AssetDocument.is_primary_photo == True,  # noqa: E712
        )
    )
    should_primary = (
        set_primary_if_first
        and doc_category == "photo"
        and primary_count.scalars().first() is None
    )

    now = utcnow_naive()
    doc = AssetDocument(
        id=gen_id(),
        asset_id=asset_id,
        name=original_name,
        file_path=internal_rel,
        file_type=mime_type,
        original_name=original_name,
        extension=extension,
        mime_type=mime_type,
        file_size=source_path.stat().st_size,
        file_hash=file_hash,
        category=doc_category,
        origin=origin,
        original_path=str(source_path),
        internal_path=internal_rel,
        thumbnail_path=thumbnail_rel,
        width=width,
        height=height,
        created_at=datetime.fromtimestamp(source_path.stat().st_mtime),
        imported_at=now,
        uploaded_at=now,
        uploaded_by=uploaded_by,
        uploaded_by_operator_id=uploaded_by_operator_id,
        status="active",
        is_primary_photo=should_primary,
        review_status=review_status,
        suggested_asset_id=suggested_asset_id,
        source_index_id=source_index_id,
    )
    db.add(doc)
    await db.flush()
    return doc


async def store_upload(
    db: AsyncSession,
    *,
    asset_id: str,
    upload: UploadFile,
    category: Optional[str],
    uploaded_by: Optional[str],
    uploaded_by_operator_id: Optional[str] = None,
) -> AssetDocument:
    original_name = Path(upload.filename or "arquivo").name
    if not original_name or original_name in {".", ".."}:
        raise HTTPException(status_code=400, detail="Nome de arquivo inválido.")
    temp_path = copy_stream_to_temp(upload.file, original_name, DATA_ROOT / "temp" / "asset_uploads")
    try:
        return await store_asset_file(
            db,
            asset_id=asset_id,
            source_path=temp_path,
            original_name=original_name,
            category=category,
            origin="upload",
            uploaded_by=uploaded_by,
            uploaded_by_operator_id=uploaded_by_operator_id,
        )
    finally:
        temp_path.unlink(missing_ok=True)


def serialize_asset_file(doc: AssetDocument) -> dict[str, Any]:
    return {
        "id": doc.id,
        "asset_id": doc.asset_id,
        "name": doc.name,
        "original_name": doc.original_name or doc.name,
        "extension": doc.extension,
        "mime_type": doc.mime_type or doc.file_type,
        "file_size": doc.file_size,
        "file_hash": doc.file_hash,
        "category": doc.category or "other",
        "origin": doc.origin,
        "thumbnail_url": f"/v2/files/{doc.id}/thumbnail" if doc.thumbnail_path else None,
        "content_url": f"/v2/files/{doc.id}/content",
        "download_url": f"/v2/files/{doc.id}/content?download=1",
        "width": doc.width,
        "height": doc.height,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "imported_at": doc.imported_at.isoformat() if doc.imported_at else None,
        "uploaded_by": doc.uploaded_by,
        "uploaded_by_operator_id": doc.uploaded_by_operator_id,
        "status": doc.status or "active",
        "is_primary_photo": bool(doc.is_primary_photo),
        "archived_at": doc.archived_at.isoformat() if doc.archived_at else None,
        "archived_by": doc.archived_by,
        "archived_by_operator_id": doc.archived_by_operator_id,
        "review_status": doc.review_status,
        "suggested_asset_id": doc.suggested_asset_id,
        "review_reason": doc.review_reason,
        "details": {
            "origin": doc.origin,
            "original_path": doc.original_path,
        },
    }


async def get_asset_file_or_404(db: AsyncSession, file_id: str) -> AssetDocument:
    result = await db.execute(select(AssetDocument).where(AssetDocument.id == file_id))
    doc = result.scalars().first()
    if not doc:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    return doc
