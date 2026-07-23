"""Identidade operacional do Manutenção em Campo.

Decisão operacional vigente: a aplicação não usa senha, PIN ou perfil para
bloquear ações. A pessoa selecionada serve para rastreabilidade e auditoria.
As colunas legadas ``role`` e ``pin_hash`` permanecem no banco apenas por
compatibilidade com instalações já migradas.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models import Operator

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "operator": {
        "orders:read", "orders:execute", "assets:read", "documents:read", "offline:sync"
    },
    "maintenance": {
        "orders:read", "orders:execute", "assets:read", "assets:write",
        "documents:read", "documents:review", "offline:sync", "indicators:read"
    },
    "quality": {
        "orders:read", "assets:read", "documents:read", "documents:review",
        "indicators:read", "quality:review", "reports:export", "system:read"
    },
    "admin": {
        "*"
    },
}

ALL_OPERATIONAL_PERMISSIONS = sorted({p for perms in ROLE_PERMISSIONS.values() for p in perms} | {"*"})

ROLE_LABELS = {
    "operator": "Operador",
    "maintenance": "Manutenção",
    "quality": "Qualidade",
    "admin": "Administrador",
}

@dataclass(slots=True)
class Actor:
    operator_id: Optional[str]
    operator_name: Optional[str]
    role: str
    permissions: set[str]
    legacy_mode: bool = False

    def can(self, permission: str) -> bool:
        return True


def normalize_role(role: Optional[str]) -> str:
    value = (role or "operator").strip().lower()
    return value if value in ROLE_PERMISSIONS else "operator"


async def _operator_role_column_exists(db: AsyncSession) -> bool:
    try:
        rows = (await db.execute(text("PRAGMA table_info(operators)"))).mappings().all()
        return any(row.get("name") == "role" for row in rows)
    except Exception:
        return False


async def _privileged_operator_exists(db: AsyncSession) -> bool:
    try:
        value = (await db.execute(text("""
            SELECT 1
            FROM operators
            WHERE coalesce(is_active, 1) != 0
              AND lower(coalesce(role, 'operator')) IN ('maintenance', 'quality', 'admin')
            LIMIT 1
        """))).scalar()
        return bool(value)
    except Exception:
        return False


async def resolve_actor(
    db: AsyncSession,
    *,
    selected_user_id: Optional[str] = None,
    operator_name: Optional[str] = None,
    default_legacy_admin: bool = True,
) -> Actor:
    """Resolve a pessoa selecionada para rastreabilidade.

    Este método nunca bloqueia por perfil. Quando ``selected_user_id`` aponta
    para uma pessoa inativa/inexistente, a validação forte fica no
    ``operator_service.resolve_actor_context`` das rotas operacionais. Aqui o
    objetivo é compatibilidade para telas de diagnóstico/permissões antigas.
    """
    has_role = await _operator_role_column_exists(db)
    operator: Optional[Operator] = None
    if selected_user_id:
        operator = (await db.execute(select(Operator).where(Operator.id == selected_user_id))).scalars().first()
    if not operator and operator_name:
        operator = (await db.execute(select(Operator).where(Operator.name == operator_name))).scalars().first()

    role = normalize_role(getattr(operator, "role", None) if operator else None)
    return Actor(
        operator_id=getattr(operator, "id", selected_user_id),
        operator_name=getattr(operator, "name", operator_name),
        role=role,
        permissions={"*"},
        legacy_mode=not bool(operator),
    )


def require_permission(actor: Actor, permission: str) -> None:
    """Compatibilidade: não há bloqueio por RBAC nesta instalação."""
    return


def permission_matrix() -> dict[str, object]:
    return {
        "roles": [
            {"role": role, "label": ROLE_LABELS.get(role, role), "permissions": ALL_OPERATIONAL_PERMISSIONS, "blocks_actions": False}
            for role, perms in ROLE_PERMISSIONS.items()
        ],
        "permissions": ALL_OPERATIONAL_PERMISSIONS,
        "mode": "traceability_only_no_rbac",
        "note": "Sem senha, sem PIN e sem bloqueio por perfil. A pessoa selecionada é usada somente para rastreabilidade.",
    }
