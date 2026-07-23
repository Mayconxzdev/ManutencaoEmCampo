"""Cria uma base inteiramente fictícia para a demonstração pública.

Uso, a partir de ``backend``::

    python scripts/seed_demo.py --reset

O script só permite a opção ``--reset`` quando o banco está dentro da pasta
``data/`` deste repositório. Assim, ele não pode apagar por engano uma base
configurada fora do projeto de portfólio.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import secrets
import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from PIL import Image

# Allows ``python scripts/seed_demo.py`` from a fresh clone without an
# editable installation. The path is the local backend directory only.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.clock import local_today, utcnow_naive
from app.config import DATABASE_PATH, PROJECT_ROOT, ensure_data_dirs
from app.database import Base, SessionLocal, engine
from app.models import (
    Asset,
    ChecklistItem,
    ChecklistTemplate,
    ChecklistTemplateVersion,
    MaintenanceOrder,
    MaintenanceOrderItem,
    MaintenancePlan,
    Operator,
    Sector,
    WorkOrderEvent,
    WorkOrderSequence,
)
from app.order_execution_service import answer_item, attach_item_photo, complete_order, start_order


DEMO_DISCLAIMER = "Dados fictícios gerados localmente para demonstração pública."


def _demo_evidence_png() -> bytes:
    """Gera uma foto sintética válida, sem depender de arquivo externo."""
    buffer = io.BytesIO()
    Image.new("RGB", (48, 32), color=(37, 99, 235)).save(buffer, format="PNG")
    return buffer.getvalue()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cria dados fictícios do Manutenção em Campo.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Recria somente o banco localizado na pasta data/ deste repositório.",
    )
    return parser.parse_args()


def _is_safe_demo_database() -> bool:
    """Permit only local demo roots, never an arbitrary configured database."""
    for safe_root in ((PROJECT_ROOT / "data").resolve(), (PROJECT_ROOT / ".e2e_data").resolve()):
        try:
            DATABASE_PATH.resolve().relative_to(safe_root)
            return True
        except ValueError:
            continue
    return False


async def _create_asset_with_plan(
    db,
    *,
    sector: Sector,
    patrimonio: str,
    description: str,
    manufacturer: str,
    model: str,
    checklist_items: list[str],
) -> tuple[Asset, ChecklistTemplateVersion, MaintenancePlan]:
    asset = Asset(
        patrimonio=patrimonio,
        controlled_code=patrimonio,
        legacy_patrimonio=patrimonio,
        type="machine",
        description=description,
        manufacturer=manufacturer,
        model=model,
        sector_id=sector.id,
        status="active",
        is_operable=True,
        asset_class="maintainable_asset",
        maintenance_strategy="preventive",
        show_in_daily_list=True,
        opaque_token=secrets.token_urlsafe(24),
        notes=DEMO_DISCLAIMER,
    )
    db.add(asset)
    await db.flush()

    template = ChecklistTemplate(
        name=f"Checklist demonstrativo — {description}",
        code_reference=f"CHK-{patrimonio}",
        asset_type="machine",
        asset_patrimonio=patrimonio,
        asset_manufacturer=manufacturer,
        asset_model_ref=model,
        maintenance_type="preventive",
        rq_cmp_reference="DEMO",
        is_active=True,
    )
    db.add(template)
    await db.flush()

    version = ChecklistTemplateVersion(
        template_id=template.id,
        version=1,
        created_by="Seed demonstrativo",
        source_document="Dados sintéticos do repositório público",
        notes=DEMO_DISCLAIMER,
    )
    db.add(version)
    await db.flush()

    for index, description_item in enumerate(checklist_items, start=1):
        db.add(
            ChecklistItem(
                version_id=version.id,
                item_number=f"{index}.0",
                description=description_item,
                is_mandatory=True,
                allow_photo=True,
                is_critical=index <= 2,
                suggested_materials="Inspeção visual e instrumentos adequados",
                item_type="inspection",
            )
        )

    plan = MaintenancePlan(
        name=f"Plano demonstrativo — {description}",
        asset_id=asset.id,
        periodicity="custom",
        checklist_template_version_id=version.id,
        estimated_duration_mins=35,
        calculation_basis="manual",
        plan_type="manual",
        generation_horizon_months=0,
        confidence="high",
        source_document="Modelo público demonstrativo",
        confirmed_by="Seed demonstrativo",
        confirmed_at=utcnow_naive(),
        recurrence_status="confirmed",
        recurrence_confirmed_by="Seed demonstrativo",
        recurrence_confirmed_at=utcnow_naive(),
        safety_instructions="Confirme que o equipamento está em condição segura antes de iniciar a inspeção.",
        is_active=True,
        is_monthly_competency=False,
    )
    db.add(plan)
    await db.flush()
    return asset, version, plan


async def _create_order(
    db,
    *,
    number: int,
    asset: Asset,
    version: ChecklistTemplateVersion,
    plan: MaintenancePlan,
    reviewer: Operator,
    executor: Operator,
    status: str,
    execution_status: str,
    planned_offset_days: int,
    completed: bool = False,
) -> MaintenanceOrder:
    today = local_today()
    now = utcnow_naive()
    order = MaintenanceOrder(
        friendly_number=number,
        asset_id=asset.id,
        plan_id=plan.id,
        checklist_version_id=version.id,
        planned_date=today + timedelta(days=planned_offset_days),
        planned_year=today.year,
        planned_month=today.month,
        scheduled_day_is_explicit=True,
        priority="medium",
        status=status,
        execution_status=execution_status,
        order_type="inspection",
        source_status="demo_seed",
        source_note=DEMO_DISCLAIMER,
        operator_name=reviewer.name,
        operator_id=reviewer.id,
        performed_by_name=executor.name if completed else None,
        performed_by_operator_id=executor.id if completed else None,
        performed_by_snapshot=executor.name if completed else None,
        final_condition="released" if completed else "released",
        opaque_token=secrets.token_urlsafe(24),
        started_at=now - timedelta(minutes=42) if execution_status == "in_progress" else None,
        completed_at=now - timedelta(days=1) if completed else None,
        duration_mins=42 if completed else None,
        notes="Registro fictício para demonstrar a linha do tempo e a rastreabilidade." if completed else None,
        record_kind="demo_test",
        record_kind_reason="Base pública demonstrativa",
    )
    db.add(order)
    await db.flush()

    items_result = await db.execute(select(ChecklistItem).where(ChecklistItem.version_id == version.id))
    for item in items_result.scalars().all():
        db.add(
            MaintenanceOrderItem(
                order_id=order.id,
                item_id=item.id,
                status="ok" if completed else "unanswered",
                operator_name=reviewer.name if completed else None,
                operator_id=reviewer.id if completed else None,
                answered_at=now - timedelta(days=1) if completed else None,
            )
        )
    db.add(
        WorkOrderEvent(
            order_id=order.id,
            event_type="completed" if completed else "created",
            operator_name=reviewer.name,
            operator_id=reviewer.id,
            payload=json.dumps({"source": "demo_seed", "disclaimer": DEMO_DISCLAIMER}, ensure_ascii=False),
            created_at=now - timedelta(days=1) if completed else now,
        )
    )
    return order


async def _complete_demo_order(
    db,
    *,
    order: MaintenanceOrder,
    reviewer: Operator,
    executor: Operator,
) -> None:
    """Percorre o mesmo serviço de execução usado pelo aplicativo.

    A base pública não simula uma conclusão alterando colunas diretamente:
    ela cria respostas, uma evidência, o PDF final e o dossiê local por meio
    da regra real. Assim o README, os testes e as capturas exibem evidência
    reproduzível do fluxo que o portfólio descreve.
    """
    device_id = "demo-seed-tablet"
    await start_order(
        db,
        order.id,
        reviewer.name,
        operator_id=reviewer.id,
        device_id=device_id,
        record_kind="demo_test",
    )
    items_res = await db.execute(
        select(MaintenanceOrderItem)
        .where(MaintenanceOrderItem.order_id == order.id)
        .order_by(MaintenanceOrderItem.id)
    )
    items = items_res.scalars().all()
    if not items:
        raise RuntimeError("A execução demonstrativa não recebeu itens de checklist.")

    await attach_item_photo(
        db,
        order.id,
        item_id=items[0].item_id,
        contents=_demo_evidence_png(),
        filename="evidencia-demonstrativa.png",
        content_type="image/png",
        operator_name=reviewer.name,
        operator_id=reviewer.id,
        device_id=device_id,
    )
    for index, item in enumerate(items):
        await answer_item(
            db,
            order.id,
            item_id=item.item_id,
            result="ok",
            operator_name=reviewer.name,
            operator_id=reviewer.id,
            notes="Verificação demonstrativa concluída com resultado normal." if index == 0 else None,
            device_id=device_id,
        )
    result = await complete_order(
        db,
        order.id,
        reviewer.name,
        operator_id=reviewer.id,
        final_condition="released",
        notes="Execução sintética concluída para demonstrar histórico, PDF e evidências.",
        idempotency_key=f"demo-seed-{order.id}",
        device_id=device_id,
        performed_by_name=executor.name,
        performed_by_operator_id=executor.id,
    )
    if not result.get("pdf_path"):
        raise RuntimeError("A execução demonstrativa foi concluída sem PDF final.")


async def seed(*, reset: bool) -> None:
    ensure_data_dirs()
    if reset and not _is_safe_demo_database():
        raise RuntimeError(
            f"Recusa de segurança: {DATABASE_PATH} não está dentro da pasta data/ deste repositório."
        )

    async with engine.begin() as connection:
        if reset:
            await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    async with SessionLocal() as db:
        existing = (await db.execute(select(Asset.id).limit(1))).scalar_one_or_none()
        if existing and not reset:
            raise RuntimeError("Já existe uma base local. Use --reset apenas para recriar a demonstração pública.")

        usinagem = Sector(name="Usinagem demonstrativa", description=DEMO_DISCLAIMER)
        montagem = Sector(name="Montagem piloto", description=DEMO_DISCLAIMER)
        db.add_all([usinagem, montagem])
        await db.flush()

        reviewers = [
            Operator(name="Camila Duarte", normalized_name="camila duarte", role="supervisor", can_record_checklist=True, can_execute_maintenance=False, sector_id=usinagem.id, origin="demo_seed"),
            Operator(name="Rafael Moreira", normalized_name="rafael moreira", role="supervisor", can_record_checklist=True, can_execute_maintenance=False, sector_id=montagem.id, origin="demo_seed"),
        ]
        executors = [
            Operator(name="Joana Lima", normalized_name="joana lima", role="technician", can_record_checklist=False, can_execute_maintenance=True, sector_id=usinagem.id, origin="demo_seed"),
            Operator(name="Diego Farias", normalized_name="diego farias", role="technician", can_record_checklist=False, can_execute_maintenance=True, sector_id=montagem.id, origin="demo_seed"),
        ]
        db.add_all([*reviewers, *executors])
        await db.flush()

        common_items = [
            "Verificar integridade visual, identificação e limpeza do ativo.",
            "Confirmar proteções, comandos e condição segura para operação.",
            "Executar teste funcional autorizado e registrar qualquer anomalia.",
            "Registrar observações, evidências e condição final de liberação.",
        ]
        asset_1, version_1, plan_1 = await _create_asset_with_plan(db, sector=usinagem, patrimonio="MEC-101", description="Prensa hidráulica de bancada", manufacturer="Atlas Demo", model="PH-40", checklist_items=common_items)
        asset_2, version_2, plan_2 = await _create_asset_with_plan(db, sector=usinagem, patrimonio="MEC-102", description="Torno mecânico didático", manufacturer="Oficina Demo", model="TM-220", checklist_items=common_items)
        asset_3, version_3, plan_3 = await _create_asset_with_plan(db, sector=montagem, patrimonio="MEC-103", description="Compressor de ar da linha piloto", manufacturer="Campo Industrial", model="CA-15", checklist_items=common_items)
        asset_4, version_4, plan_4 = await _create_asset_with_plan(db, sector=montagem, patrimonio="MEC-104", description="Impressora 3D de protótipos", manufacturer="Laboratório Demo", model="FD-1", checklist_items=common_items)

        await _create_order(db, number=1001, asset=asset_1, version=version_1, plan=plan_1, reviewer=reviewers[0], executor=executors[0], status="today", execution_status="not_started", planned_offset_days=0)
        await _create_order(db, number=1002, asset=asset_2, version=version_2, plan=plan_2, reviewer=reviewers[0], executor=executors[0], status="overdue", execution_status="not_started", planned_offset_days=-3)
        await _create_order(db, number=1003, asset=asset_3, version=version_3, plan=plan_3, reviewer=reviewers[1], executor=executors[1], status="in_progress", execution_status="in_progress", planned_offset_days=0)
        completed_demo_order = await _create_order(db, number=1004, asset=asset_4, version=version_4, plan=plan_4, reviewer=reviewers[1], executor=executors[1], status="today", execution_status="not_started", planned_offset_days=-1)
        db.add(WorkOrderSequence(name="maintenance_order", next_value=1005))
        await db.commit()
        await _complete_demo_order(db, order=completed_demo_order, reviewer=reviewers[1], executor=executors[1])

    print(f"Base demonstrativa criada em: {DATABASE_PATH}")
    print("4 ativos, 4 pessoas, 4 planos e 4 OMs fictícias foram gerados.")
    print("A OM demonstrativa concluída possui respostas, evidência, PDF e dossiê local recriáveis.")


if __name__ == "__main__":
    arguments = parse_args()
    asyncio.run(seed(reset=arguments.reset))
