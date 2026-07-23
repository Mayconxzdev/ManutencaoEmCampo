from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app import schemas
from app.clock import utcnow_naive
from app.database import get_db
from app.models import Asset, MaintenanceIssue


router = APIRouter()


@router.get("/issues", response_model=List[schemas.MaintenanceIssue])
async def list_issues(status: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    query = select(MaintenanceIssue)
    if status:
        query = query.where(MaintenanceIssue.status == status)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/issues", response_model=schemas.MaintenanceIssue, status_code=status.HTTP_201_CREATED)
async def create_issue(issue: schemas.MaintenanceIssueCreate, db: AsyncSession = Depends(get_db)):
    db_issue = MaintenanceIssue(
        asset_id=issue.asset_id,
        order_id=issue.order_id,
        description=issue.description,
        priority=issue.priority,
        is_operable_affected=issue.is_operable_affected,
        status=issue.status,
        operator_name=issue.operator_name,
    )
    db.add(db_issue)

    if issue.is_operable_affected:
        asset_result = await db.execute(select(Asset).where(Asset.id == issue.asset_id))
        asset = asset_result.scalars().first()
        if asset:
            asset.is_operable = False

    await db.flush()
    return db_issue


@router.post("/issues/{issue_id}/resolve", response_model=schemas.MaintenanceIssue)
async def resolve_issue(issue_id: str, operator_name: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    query = select(MaintenanceIssue).where(MaintenanceIssue.id == issue_id)
    result = await db.execute(query)
    issue = result.scalars().first()
    if not issue:
        raise HTTPException(status_code=404, detail="Ocorrência não encontrada")

    issue.status = "resolved"
    issue.resolved_at = utcnow_naive()

    if issue.is_operable_affected:
        open_issues = await db.execute(
            select(MaintenanceIssue).where(
                MaintenanceIssue.asset_id == issue.asset_id,
                MaintenanceIssue.status == "open",
                MaintenanceIssue.is_operable_affected == True,  # noqa: E712
                MaintenanceIssue.id != issue_id,
            )
        )
        if not open_issues.scalars().first():
            asset_result = await db.execute(select(Asset).where(Asset.id == issue.asset_id))
            asset = asset_result.scalars().first()
            if asset:
                asset.is_operable = True

    await db.flush()
    return issue
