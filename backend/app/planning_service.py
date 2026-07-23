from __future__ import annotations

import secrets
from datetime import date

from dateutil.relativedelta import relativedelta
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clock import local_today, utcnow_naive
from app.models import ChecklistItem, MaintenanceOrder, MaintenanceOrderItem, MaintenancePlan, WorkOrderSequence


async def plan_anchor_month_index(db: AsyncSession, plan: MaintenancePlan) -> int:
    result = await db.execute(
        select(MaintenanceOrder.planned_year, MaintenanceOrder.planned_month)
        .where(
            MaintenanceOrder.plan_id == plan.id,
            MaintenanceOrder.planned_year.isnot(None),
            MaintenanceOrder.planned_month.isnot(None),
        )
        .order_by(MaintenanceOrder.planned_year.asc(), MaintenanceOrder.planned_month.asc())
        .limit(1)
    )
    row = result.first()
    if row and row[0] and row[1]:
        return int(row[0]) * 12 + int(row[1]) - 1
    if plan.next_due_date:
        return plan.next_due_date.year * 12 + plan.next_due_date.month - 1
    if plan.planned_month:
        return local_today().year * 12 + int(plan.planned_month) - 1
    return local_today().year * 12 + local_today().month - 1


def plan_applies_to_month(plan: MaintenancePlan, year: int, month: int, anchor_month_index: int) -> bool:
    if plan.plan_type == "fixed_calendar" or plan.calculation_basis == "fixed_calendar":
        if plan.fixed_months:
            fixed_list = [int(item) for item in plan.fixed_months.split(",") if item.strip().isdigit()]
            return month in fixed_list
        frequency = int(plan.frequency_months or 1)
        if frequency <= 1:
            return True
        target_index = year * 12 + month - 1
        return (target_index - anchor_month_index) % frequency == 0
    if plan.plan_type == "interval":
        target_index = year * 12 + month - 1
        return target_index >= anchor_month_index and (target_index - anchor_month_index) % max(int(plan.frequency_months or 1), 1) == 0
    return False


async def next_friendly_number(db: AsyncSession) -> int:
    """Atomically reserve the next global OM number.

    The `work_order_sequence` row is seeded by migrations/update scripts. Runtime
    code must not derive the next number from existing orders, because concurrent
    generators can race and create duplicate friendly numbers.
    """

    result = await db.execute(
        text(
            """
            UPDATE work_order_sequence
               SET next_value = next_value + 1,
                   updated_at = CURRENT_TIMESTAMP
             WHERE name = 'maintenance_order'
            RETURNING next_value - 1
            """
        )
    )
    value = result.scalar_one_or_none()
    if value is None:
        raise RuntimeError(
            "Sequência de OMs não inicializada. Execute as migrations antes de gerar ordens."
        )
    return int(value)


async def create_order_items_from_checklist(db: AsyncSession, order: MaintenanceOrder) -> int:
    if not order.checklist_version_id:
        return 0
    items_result = await db.execute(select(ChecklistItem).where(ChecklistItem.version_id == order.checklist_version_id))
    count = 0
    for checklist_item in items_result.scalars().all():
        db.add(MaintenanceOrderItem(order_id=order.id, item_id=checklist_item.id, status="unanswered"))
        count += 1
    await db.flush()
    return count


async def order_exists_for_competence(db: AsyncSession, plan_id: str, year: int, month: int) -> bool:
    result = await db.execute(
        select(MaintenanceOrder.id).where(
            MaintenanceOrder.plan_id == plan_id,
            MaintenanceOrder.planned_year == year,
            MaintenanceOrder.planned_month == month,
        )
    )
    return result.scalars().first() is not None


async def create_monthly_order_if_missing(
    db: AsyncSession,
    *,
    plan: MaintenancePlan,
    competence_date: date,
) -> MaintenanceOrder | None:
    year = competence_date.year
    month = competence_date.month
    if await order_exists_for_competence(db, plan.id, year, month):
        return None

    for _attempt in range(5):
        order = MaintenanceOrder(
            friendly_number=await next_friendly_number(db),
            asset_id=plan.asset_id,
            plan_id=plan.id,
            checklist_version_id=plan.checklist_template_version_id,
            planned_date=None,
            planned_year=year,
            planned_month=month,
            original_competence=f"{year:04d}-{month:02d}",
            scheduled_day_is_explicit=False,
            status="scheduled",
            execution_status="not_started",
            needs_review=False,
            is_monthly_competency=True,
            order_type="preventive",
            opaque_token=secrets.token_urlsafe(32),
        )
        try:
            async with db.begin_nested():
                db.add(order)
                await db.flush()
                await create_order_items_from_checklist(db, order)
            return order
        except IntegrityError:
            if await order_exists_for_competence(db, plan.id, year, month):
                return None
    raise RuntimeError(f"Não foi possível gerar número único para plano {plan.id} em {year:04d}-{month:02d}.")


async def generate_future_maintenance_orders(
    db: AsyncSession,
    *,
    start: date | None = None,
    horizon_months: int = 12,
) -> dict:
    today = start or local_today()
    plans_result = await db.execute(
        select(MaintenancePlan)
        .where(
            MaintenancePlan.is_active == 1,
            MaintenancePlan.recurrence_status == "confirmed",
        )
        .options(selectinload(MaintenancePlan.asset))
    )
    plans = plans_result.scalars().all()
    summary = {
        "plans_analyzed": 0,
        "orders_created": 0,
        "orders_existing": 0,
        "plans_skipped": 0,
        "horizon_months": horizon_months,
    }
    for plan in plans:
        summary["plans_analyzed"] += 1
        if not plan.asset or plan.asset.status == "inactive":
            summary["plans_skipped"] += 1
            continue
        anchor_index = await plan_anchor_month_index(db, plan)
        created_for_plan = 0
        for offset in range(0, horizon_months):
            future_date = today + relativedelta(months=offset)
            if not plan_applies_to_month(plan, future_date.year, future_date.month, anchor_index):
                continue
            before_exists = await order_exists_for_competence(db, plan.id, future_date.year, future_date.month)
            order = await create_monthly_order_if_missing(db, plan=plan, competence_date=future_date)
            if order:
                created_for_plan += 1
                summary["orders_created"] += 1
            elif before_exists:
                summary["orders_existing"] += 1
        if created_for_plan:
            plan.last_auto_generated_at = utcnow_naive()
    await db.flush()
    return summary
