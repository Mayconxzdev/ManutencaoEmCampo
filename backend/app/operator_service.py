from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.asset_file_service import (
    IMAGE_EXTENSIONS,
    copy_stream_to_temp,
    make_thumbnail,
    resolve_internal_path,
    safe_relative,
    sha256_path,
    sniff_file,
)
from app.clock import utcnow_naive
from app.config import DATA_ROOT
from app.models import Operator


@dataclass(frozen=True)
class ActorContext:
    selected_user_id: Optional[str]
    operator_name: str
    compatibility_name_used: bool = False


def normalize_operator_name(name: str) -> str:
    return " ".join((name or "").strip().upper().split())


async def resolve_selected_operator(db: AsyncSession, selected_user_id: Optional[str]) -> Optional[Operator]:
    if not selected_user_id:
        return None
    result = await db.execute(select(Operator).where(Operator.id == selected_user_id))
    operator = result.scalars().first()
    if not operator:
        raise HTTPException(status_code=400, detail="Pessoa selecionada não encontrada.")
    if operator.is_active is False:
        raise HTTPException(status_code=400, detail="Pessoa selecionada está arquivada.")
    return operator


async def resolve_actor_context(
    db: AsyncSession,
    *,
    selected_user_id: Optional[str],
    operator_name: Optional[str] = None,
    default_name: str = "Operador Padrão",
) -> ActorContext:
    operator = await resolve_selected_operator(db, selected_user_id)
    if operator:
        return ActorContext(
            selected_user_id=operator.id,
            operator_name=operator.name,
            compatibility_name_used=False,
        )
    fallback = (operator_name or "").strip() or default_name
    return ActorContext(
        selected_user_id=None,
        operator_name=fallback,
        compatibility_name_used=bool(operator_name),
    )


async def resolve_maintenance_executor(db: AsyncSession, operator_id: str) -> Operator:
    """Resolve quem realizou o serviço físico, separado de quem conferiu.

    A pessoa precisa estar ativa e marcada na Gestão como executante. Isso não
    cria perfil de acesso: só evita apontar acidentalmente um supervisor como
    executor no fechamento da OM.
    """
    operator = await resolve_selected_operator(db, operator_id)
    if not operator:
        raise HTTPException(status_code=400, detail="Selecione quem executou a manutenção.")
    if not bool(getattr(operator, "can_execute_maintenance", False)):
        raise HTTPException(status_code=400, detail="A pessoa selecionada não está disponível como executante de manutenção.")
    return operator


async def resolve_checklist_reviewer(db: AsyncSession, operator_id: str) -> Operator:
    """Garante que a confirmação de rascunho/correção venha de Camila ou Rafael.

    Isto não é login, PIN nem bloqueio do tablet: é apenas a assinatura de quem
    conferiu a decisão, para a qualidade conseguir localizar a responsabilidade.
    """
    operator = await resolve_selected_operator(db, operator_id)
    if not operator or not bool(getattr(operator, "can_record_checklist", False)):
        raise HTTPException(status_code=400, detail="Selecione Camila ou Rafael para confirmar esta revisão.")
    return operator


async def save_operator_photo_file(operator: Operator, upload: UploadFile) -> None:
    original_name = Path(upload.filename or "foto").name
    if not original_name or original_name in {".", ".."}:
        raise HTTPException(status_code=400, detail="Nome de arquivo inválido.")
    temp_path = copy_stream_to_temp(upload.file, original_name, DATA_ROOT / "temp" / "operator_uploads")
    try:
        mime_type, extension, _width, _height = sniff_file(temp_path)
        if extension not in IMAGE_EXTENSIONS or not mime_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="A foto da pessoa deve ser uma imagem JPG, PNG ou WEBP válida.")
        file_hash = sha256_path(temp_path)
        base_dir = DATA_ROOT / "storage" / "operators" / operator.id
        original_dir = base_dir / "originals"
        thumb_dir = base_dir / "thumbnails"
        original_dir.mkdir(parents=True, exist_ok=True)
        thumb_dir.mkdir(parents=True, exist_ok=True)
        internal = original_dir / f"{file_hash}{extension}"
        if not internal.exists():
            temp_path.replace(internal)
        thumbnail = thumb_dir / f"{file_hash}.jpg"
        thumbnail_rel, _width, _height = make_thumbnail(internal, thumbnail)
        operator.photo_path = safe_relative(internal)
        operator.photo_thumbnail_path = thumbnail_rel
        operator.photo_hash = file_hash
        operator.updated_at = utcnow_naive()
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def operator_photo_response(path: Optional[str]):
    if not path:
        raise HTTPException(status_code=404, detail="Foto não encontrada")
    return resolve_internal_path(path)
