from __future__ import annotations

from fastapi import APIRouter

from app.observability import recent_requests

router = APIRouter(prefix="/v2/observability", tags=["observability"])

@router.get("/requests")
async def requests(limit: int = 100):
    return {"items": recent_requests(limit), "total": len(recent_requests(500))}
