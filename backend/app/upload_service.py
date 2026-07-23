import hashlib
import io
import os
from pathlib import Path

from fastapi import HTTPException
from PIL import Image, ImageOps

from app.config import THUMBNAILS_DIR


def evidence_absolute_path(file_path: str, uploads_dir: str) -> str:
    normalized = (file_path or "").replace("\\", "/").lstrip("/")
    filename = os.path.basename(normalized)
    return os.path.join(uploads_dir, filename)


def validate_and_save_image(contents: bytes, original_filename: str, content_type: str, uploads_dir: str) -> tuple[str, str]:
    max_size = 10 * 1024 * 1024
    if len(contents) > max_size:
        raise HTTPException(status_code=400, detail="Arquivo muito grande. Limite máximo de 10MB.")

    ext = Path(original_filename or "").suffix.lower()
    if ext not in [".jpg", ".jpeg", ".png", ".webp", ""]:
        raise HTTPException(status_code=400, detail="Extensão de imagem não permitida. Apenas JPG, JPEG, PNG e WEBP.")

    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime and mime not in ["image/jpeg", "image/jpg", "image/png", "image/webp", "application/octet-stream"]:
        raise HTTPException(status_code=400, detail="Tipo MIME de imagem inválido.")

    magic = contents[:16]
    is_jpeg = magic.startswith(b"\xFF\xD8\xFF")
    is_png = magic.startswith(b"\x89PNG\r\n\x1a\n")
    is_webp = magic.startswith(b"RIFF") and b"WEBP" in magic[8:16]
    if not (is_jpeg or is_png or is_webp):
        raise HTTPException(status_code=400, detail="Assinatura real de imagem inválida ou corrompida.")

    real_type = "image/jpeg" if is_jpeg else "image/png" if is_png else "image/webp"
    real_ext = ".jpg" if is_jpeg else ".png" if is_png else ".webp"
    real_format = "JPEG" if is_jpeg else "PNG" if is_png else "WEBP"
    allowed_by_extension = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    if ext and allowed_by_extension.get(ext) != real_type:
        raise HTTPException(status_code=400, detail="Extensão, MIME e assinatura real da imagem não conferem.")
    if mime and mime not in {real_type, "image/jpg", "application/octet-stream"}:
        raise HTTPException(status_code=400, detail="Extensão, MIME e assinatura real da imagem não conferem.")

    try:
        import uuid

        with Image.open(io.BytesIO(contents)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(contents)) as opened:
            image = ImageOps.exif_transpose(opened).copy()
        if real_format == "JPEG" and image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        clean_filename = f"{uuid.uuid4()}{real_ext}"
        os.makedirs(uploads_dir, exist_ok=True)
        os.makedirs(str(THUMBNAILS_DIR), exist_ok=True)
        save_path = os.path.join(uploads_dir, clean_filename)
        image.save(save_path, format=real_format)

        image.thumbnail((200, 200))
        thumb_filename = f"{os.path.splitext(clean_filename)[0]}_thumb{real_ext}"
        thumb_path = os.path.join(str(THUMBNAILS_DIR), thumb_filename)
        image.save(thumb_path, format=real_format)

        # A imagem é higienizada/regravada antes de persistir. O hash precisa
        # representar os bytes efetivamente guardados, para que cópias no NAS
        # e restaurações possam ser verificadas sem falso positivo.
        with open(save_path, "rb") as stored_file:
            file_hash = hashlib.sha256(stored_file.read()).hexdigest()
        return f"data/uploads/{clean_filename}", file_hash
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Erro ao higienizar imagem: {str(exc)}")
