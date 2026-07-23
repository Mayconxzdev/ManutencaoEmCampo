from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app import schemas
from app.audit_service import create_audit_log
from app.clock import utcnow_naive
from app.database import get_db
from app.models import Operator
from app.operator_service import normalize_operator_name, operator_photo_response, save_operator_photo_file


router = APIRouter()


@router.get("/operators", response_model=List[schemas.Operator])
async def list_operators(
    include_archived: bool = False,
    selection: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Lista pessoas ativas ou a lista simples necessária em cada tela.

    ``selection`` não é controle de permissão: apenas evita que a tela inicial
    do tablet mostre executantes que não registram checklist.
    """
    query = select(Operator)
    if not include_archived:
        query = query.where(or_(Operator.is_active != False, Operator.is_active.is_(None)))  # noqa: E712
    if selection == "checklist_reviewer":
        query = query.where(Operator.can_record_checklist.is_(True))
    elif selection == "maintenance_executor":
        query = query.where(Operator.can_execute_maintenance.is_(True))
    elif selection is not None:
        raise HTTPException(status_code=400, detail="Lista de pessoas inválida.")
    result = await db.execute(query.order_by(Operator.name))
    return result.scalars().all()


@router.post("/operators", response_model=schemas.Operator, status_code=status.HTTP_201_CREATED)
async def create_operator(op: schemas.OperatorCreate, self_registration: bool = False, db: AsyncSession = Depends(get_db)):
    if not op.name or not op.name.strip():
        raise HTTPException(status_code=400, detail="Nome do responsável é obrigatório")
    db_op = Operator(
        name=op.name.strip(),
        normalized_name=normalize_operator_name(op.name),
        nickname=op.nickname,
        sector_id=op.sector_id,
        origin=op.origin or ("self_registration" if self_registration else "manual"),
        role=(op.role or "operator"),
        can_record_checklist=bool(op.can_record_checklist),
        can_execute_maintenance=True if op.can_execute_maintenance is None else bool(op.can_execute_maintenance),
        is_active=True,
        created_at=utcnow_naive(),
    )
    db.add(db_op)
    await db.flush()
    db.add(create_audit_log(
        action="operator_self_registered" if self_registration else "operator_created",
        entity_name="operator",
        entity_id=db_op.id,
        new_values={"name": db_op.name, "normalized_name": db_op.normalized_name, "is_active": db_op.is_active, "origin": db_op.origin, "can_record_checklist": db_op.can_record_checklist, "can_execute_maintenance": db_op.can_execute_maintenance},
    ))
    return db_op


@router.put("/operators/{op_id}", response_model=schemas.Operator)
async def update_operator(op_id: str, op: schemas.OperatorCreate, operator_name: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Operator).where(Operator.id == op_id))
    db_op = result.scalars().first()
    if not db_op:
        raise HTTPException(status_code=404, detail="Responsável não encontrado")

    if not op.name or not op.name.strip():
        raise HTTPException(status_code=400, detail="Nome do responsável é obrigatório")
    old_values = {"name": db_op.name, "nickname": db_op.nickname, "sector_id": db_op.sector_id, "is_active": db_op.is_active, "role": getattr(db_op, "role", None), "can_record_checklist": db_op.can_record_checklist, "can_execute_maintenance": db_op.can_execute_maintenance}
    db_op.name = op.name.strip()
    db_op.normalized_name = normalize_operator_name(op.name)
    db_op.nickname = op.nickname
    db_op.sector_id = op.sector_id
    db_op.origin = op.origin or db_op.origin or "manual"
    if op.role:
        db_op.role = op.role
    if op.can_record_checklist is not None:
        db_op.can_record_checklist = bool(op.can_record_checklist)
    if op.can_execute_maintenance is not None:
        db_op.can_execute_maintenance = bool(op.can_execute_maintenance)
    db_op.updated_at = utcnow_naive()
    db.add(create_audit_log(
        action="operator_updated",
        entity_name="operator",
        entity_id=db_op.id,
        operator_name=operator_name,
        old_values=old_values,
        new_values={"name": db_op.name, "nickname": db_op.nickname, "sector_id": db_op.sector_id, "is_active": db_op.is_active, "role": getattr(db_op, "role", None), "can_record_checklist": db_op.can_record_checklist, "can_execute_maintenance": db_op.can_execute_maintenance},
    ))
    await db.flush()
    return db_op


@router.delete("/operators/{op_id}")
async def delete_operator(op_id: str, archived_by: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Operator).where(Operator.id == op_id))
    db_op = result.scalars().first()
    if not db_op:
        raise HTTPException(status_code=404, detail="Responsável não encontrado")

    old_values = {"name": db_op.name, "is_active": db_op.is_active}
    db_op.is_active = False
    db_op.archived_at = utcnow_naive()
    db_op.archived_by = archived_by
    db_op.updated_at = db_op.archived_at
    db.add(create_audit_log(
        action="operator_archived",
        entity_name="operator",
        entity_id=db_op.id,
        operator_name=archived_by,
        old_values=old_values,
        new_values={"name": db_op.name, "is_active": db_op.is_active, "archived_by": archived_by},
    ))
    await db.flush()
    return {"status": "archived", "message": "Pessoa arquivada sem apagar o histórico."}


@router.post("/operators/{op_id}/reactivate", response_model=schemas.Operator)
async def reactivate_operator(op_id: str, operator_name: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Operator).where(Operator.id == op_id))
    db_op = result.scalars().first()
    if not db_op:
        raise HTTPException(status_code=404, detail="Responsável não encontrado")
    old_values = {"name": db_op.name, "is_active": db_op.is_active, "archived_at": db_op.archived_at}
    db_op.is_active = True
    db_op.archived_at = None
    db_op.archived_by = None
    db_op.updated_at = utcnow_naive()
    db.add(create_audit_log(
        action="operator_reactivated",
        entity_name="operator",
        entity_id=db_op.id,
        operator_name=operator_name,
        old_values=old_values,
        new_values={"name": db_op.name, "is_active": db_op.is_active},
    ))
    await db.flush()
    return db_op


@router.post("/operators/{op_id}/photo", response_model=schemas.Operator)
async def upload_operator_photo(op_id: str, file: UploadFile = File(...), operator_name: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Operator).where(Operator.id == op_id))
    db_op = result.scalars().first()
    if not db_op:
        raise HTTPException(status_code=404, detail="Responsável não encontrado")
    old_values = {"photo_hash": db_op.photo_hash}
    await save_operator_photo_file(db_op, file)
    db.add(create_audit_log(
        action="operator_photo_updated",
        entity_name="operator",
        entity_id=db_op.id,
        operator_name=operator_name,
        old_values=old_values,
        new_values={"photo_hash": db_op.photo_hash},
    ))
    await db.flush()
    return db_op


@router.get("/operators/{op_id}/photo")
async def get_operator_photo(op_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Operator).where(Operator.id == op_id))
    db_op = result.scalars().first()
    if not db_op or not db_op.photo_path:
        raise HTTPException(status_code=404, detail="Foto não encontrada")
    return FileResponse(operator_photo_response(db_op.photo_path))


@router.get("/operators/{op_id}/photo/thumbnail")
async def get_operator_photo_thumbnail(op_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Operator).where(Operator.id == op_id))
    db_op = result.scalars().first()
    if not db_op or not db_op.photo_thumbnail_path:
        raise HTTPException(status_code=404, detail="Miniatura não encontrada")
    return FileResponse(operator_photo_response(db_op.photo_thumbnail_path))
