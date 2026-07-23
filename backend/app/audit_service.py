import json
from typing import Optional

from app.clock import utcnow_naive
from app.models import AuditLog


def create_audit_log(
    *,
    action: str,
    entity_name: str,
    entity_id: str,
    operator_name: Optional[str] = None,
    selected_user_id: Optional[str] = None,
    actor_name_snapshot: Optional[str] = None,
    device_id: Optional[str] = None,
    session_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    origin: str = "web",
    old_values: Optional[dict] = None,
    new_values: Optional[dict] = None,
) -> AuditLog:
    return AuditLog(
        action=action,
        entity_name=entity_name,
        entity_id=entity_id,
        old_values=json.dumps(old_values, ensure_ascii=False, default=str) if old_values is not None else None,
        new_values=json.dumps(new_values, ensure_ascii=False, default=str) if new_values is not None else None,
        origin=origin,
        operator_name=operator_name,
        selected_user_id=selected_user_id,
        actor_name_snapshot=actor_name_snapshot or operator_name,
        device_id=device_id,
        session_id=session_id,
        correlation_id=correlation_id,
        created_at=utcnow_naive(),
    )
