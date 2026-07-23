from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.search_service import rebuild_search_index, search_global
from app.data_integrity_service import search_index_status

router = APIRouter(prefix="/v2/search", tags=["search"])


@router.get("/global")
async def global_search(
    q: str = Query(..., min_length=2, max_length=120),
    entity_type: Optional[str] = Query(None, description="asset, asset_file, legacy_document, plan, order, checklist_item"),
    limit: int = Query(30, ge=1, le=100),
    rebuild_if_empty: bool = True,
    db: AsyncSession = Depends(get_db),
):
    return await search_global(db, q, entity_type=entity_type, limit=limit, rebuild_if_empty=rebuild_if_empty)


@router.post("/rebuild")
async def rebuild_global_search(db: AsyncSession = Depends(get_db)):
    return await rebuild_search_index(db)


@router.get("/status")
async def global_search_status(db: AsyncSession = Depends(get_db)):
    return await search_index_status(db)
