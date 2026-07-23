from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.security_service import permission_matrix, resolve_actor

router = APIRouter(prefix="/v2/permissions", tags=["permissions"])

class RoleUpdate(BaseModel):
    role: str
    selected_user_id: Optional[str] = None
    operator_name: Optional[str] = None

@router.get("/matrix")
async def matrix():
    return permission_matrix()

@router.get("/me")
async def me(selected_user_id: Optional[str] = None, operator_name: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    actor = await resolve_actor(db, selected_user_id=selected_user_id, operator_name=operator_name)
    return {
        "operator_id": actor.operator_id,
        "operator_name": actor.operator_name,
        "role": actor.role,
        "permissions": sorted(actor.permissions),
        "legacy_mode": actor.legacy_mode,
    }

@router.post("/operators/{operator_id}/role")
async def update_operator_role(operator_id: str, req: RoleUpdate, db: AsyncSession = Depends(get_db)):
    """Compatibilidade com telas antigas.

    A instalação oficial não usa perfil, PIN ou senha para bloquear ações.
    Por isso este endpoint não altera regra operacional; ele apenas informa que
    ``role`` é legado/diagnóstico.
    """
    actor = await resolve_actor(db, selected_user_id=req.selected_user_id, operator_name=req.operator_name)
    return {
        "updated": False,
        "operator_id": operator_id,
        "requested_role": req.role,
        "mode": "traceability_only_no_rbac",
        "blocks_actions": False,
        "actor": {"operator_id": actor.operator_id, "operator_name": actor.operator_name},
        "message": "Perfis foram mantidos apenas como compatibilidade; nenhuma ação é bloqueada por role/PIN.",
    }
