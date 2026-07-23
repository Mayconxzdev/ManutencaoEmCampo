from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from typing import Optional
from contextlib import asynccontextmanager, suppress
import asyncio
import os

from app.database import get_db
from app.config import PROJECT_ROOT, DATABASE_PATH, UPLOADS_DIR as CONFIG_UPLOADS_DIR, THUMBNAILS_DIR, APP_VERSION, ensure_data_dirs
from app.clock import utcnow_naive, local_today
from app.models import Asset, MaintenancePlan, MaintenanceOrder, MaintenanceEvidence
from app.upload_service import evidence_absolute_path as resolve_evidence_path
from app.order_execution_service import calculate_next_date, effective_open_status


BASE_DIR = str(PROJECT_ROOT)
UPLOADS_DIR = str(CONFIG_UPLOADS_DIR)
ensure_data_dirs()


def evidence_absolute_path(file_path: str) -> str:
    return resolve_evidence_path(file_path, UPLOADS_DIR)


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """Inicialização sem exclusão automática de evidências."""
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    try:
        from datetime import timedelta
        from app.database import SessionLocal
        async with SessionLocal() as db:
            print("[STARTUP] Evidências temporárias antigas são preservadas para revisão; nenhuma exclusão automática será executada.")

            print("[STARTUP] Iniciando geração idempotente de ordens futuras (planejamento)...")
            from app.planning_service import generate_future_maintenance_orders
            planning_summary = await generate_future_maintenance_orders(db, horizon_months=12)
            if planning_summary["orders_created"] > 0:
                await db.commit()
            print(f"[STARTUP] Planejamento futuro processado: {planning_summary}")
            from app.document_worker import start_file_organization_worker_background
            start_file_organization_worker_background()
            try:
                from app.search_service import ensure_search_schema
                await ensure_search_schema(db)
            except Exception as search_exc:
                print(f"[STARTUP WARN] Busca global FTS não inicializada: {search_exc}")
            try:
                from app.dossier_service import sync_pending_jobs
                reports = await sync_pending_jobs(db, limit=10)
                if reports:
                    print(f"[STARTUP] Sincronização de dossiês processada: {len(reports)} item(ns).")
            except Exception as dossier_exc:
                print(f"[STARTUP WARN] Fila de dossiês não processada: {dossier_exc}")
    except Exception as e:
        print(f"[STARTUP ERROR] Falha no startup: {e}")
    async def retry_dossier_queue() -> None:
        """Tenta novamente a fila do NAS sem exigir que alguém saiba usar TI."""
        from app.database import SessionLocal
        while True:
            await asyncio.sleep(300)
            try:
                async with SessionLocal() as retry_db:
                    from app.dossier_service import sync_pending_jobs
                    reports = await sync_pending_jobs(retry_db, limit=20)
                    if reports:
                        print(f"[DOSSIE] Nova tentativa automática: {len(reports)} item(ns).")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"[DOSSIE WARN] Tentativa automática não concluída: {exc}")

    retry_task = asyncio.create_task(retry_dossier_queue(), name="mec-dossier-retry")
    try:
        yield  # Aqui a aplicação fica rodando
    finally:
        retry_task.cancel()
        with suppress(asyncio.CancelledError):
            await retry_task
    # (shutdown logic, se necessário, viria aqui)


app = FastAPI(
    title="Manutenção em Campo API",
    description="API simplificada para gestão da manutenção industrial",
    version=APP_VERSION,
    lifespan=lifespan
)

from app.observability import request_logging_middleware
app.middleware("http")(request_logging_middleware)

# Integrar rotas v2.
from app.routes_v2 import router as routes_v2_router
app.include_router(routes_v2_router)
from app.routes_backup import router as backup_router
app.include_router(backup_router)
from app.routes_reports import router as reports_router
app.include_router(reports_router)
from app.routes_operators import router as operators_router
app.include_router(operators_router)
from app.routes_assets import router as assets_router
app.include_router(assets_router)
from app.routes_issues import router as issues_router
app.include_router(issues_router)
from app.routes_orders import router as orders_router
app.include_router(orders_router)
from app.routes_search import router as search_router
app.include_router(search_router)
from app.routes_system import router as system_router
app.include_router(system_router)
from app.routes_observability import router as observability_router
app.include_router(observability_router)
from app.routes_ai import router as ai_router
app.include_router(ai_router)
from app.routes_permissions import router as permissions_router
app.include_router(permissions_router)
from app.routes_document_review import router as document_review_router
app.include_router(document_review_router)
from app.routes_offline import router as offline_router
app.include_router(offline_router)
from app.routes_traceability import router as traceability_router
app.include_router(traceability_router)

from app.routes_v2 import ApproveBatchRequest, approve_suggestions_batch

@app.post("/quality/suggestions/approve-batch")
async def approve_suggestions_batch_compat(req: ApproveBatchRequest, request: Request, db: AsyncSession = Depends(get_db)):
    return await approve_suggestions_batch(req, request, db)

@app.get("/health")
async def health_check():
    return {"status": "ok", "version": APP_VERSION, "database": str(DATABASE_PATH)}

# Configurando CORS para comunicação com o frontend Vite (geralmente porta 5173 ou rede local)
allowed_origins = [origin.strip() for origin in os.getenv(
    "MEC_CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000"
).split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/ping")
async def ping():
    return {"status": "ok"}

# --- ROTEAMENTO SPA PARA TOKENS OPACOS ---
@app.get("/o/{token}")
@app.get("/a/{token}")
@app.get("/ordens/{token}/executar")
async def serve_spa_for_token(token: str):
    index_path = os.path.join(frontend_dist, "index.html")
    if os.path.exists(index_path):
        return frontend_shell_response(index_path)
    # Fallback útil em testes e desenvolvimento; a versão distribuída inclui o dist.
    return HTMLResponse("<!doctype html><html><body><div id='root'>Manutenção em Campo</div></body></html>")

@app.get("/resolve-token/{token}")
async def resolve_token(token: str, db: AsyncSession = Depends(get_db)):
    order_res = await db.execute(select(MaintenanceOrder).where(MaintenanceOrder.opaque_token == token))
    db_order = order_res.scalars().first()
    if db_order:
        return {"type": "order", "id": db_order.id, "friendly_number": db_order.friendly_number}

    asset_res = await db.execute(select(Asset).where(Asset.opaque_token == token))
    db_asset = asset_res.scalars().first()
    if db_asset:
        return {"type": "asset", "id": db_asset.id, "patrimonio": db_asset.patrimonio}

    raise HTTPException(status_code=404, detail="Token inválido ou não encontrado.")

@app.get("/planning")
async def get_planning_data(year: int, month: Optional[int] = None, type: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    from app.models import LegacyHistory
    # A agenda operacional não deve misturar máquinas/equipamentos produtivos
    # com ferramentas, peças de reposição ou instrumentos de medição. Esses
    # registros continuam preservados no inventário e na rastreabilidade.
    query = select(Asset).where(
        Asset.status == "active",
        Asset.show_in_daily_list.is_(True),
    )
    if type:
        query = query.where(Asset.type == type)
    result = await db.execute(query)
    assets_list = result.scalars().all()

    orders_query = select(MaintenanceOrder).where(MaintenanceOrder.planned_year == year)
    if month:
        orders_query = orders_query.where(MaintenanceOrder.planned_month == month)
    orders_result = await db.execute(orders_query)
    orders_list = orders_result.scalars().all()

    orders_map = {}
    for o in orders_list:
        if o.asset_id not in orders_map:
            orders_map[o.asset_id] = {}
        orders_map[o.asset_id][o.planned_month] = {
            "id": o.id,
            "friendly_number": o.friendly_number,
            "status": o.status,
            "execution_status": o.execution_status,
            "needs_review": o.needs_review
        }

    legacy_query = select(LegacyHistory).where(LegacyHistory.planned_year == year)
    if month:
        legacy_query = legacy_query.where(LegacyHistory.planned_month == month)
    legacy_result = await db.execute(legacy_query)
    legacy_list = legacy_result.scalars().all()

    legacy_map = {}
    for l in legacy_list:
        if l.asset_id not in legacy_map:
            legacy_map[l.asset_id] = {}
        legacy_map[l.asset_id][l.planned_month] = {
            "id": l.id,
            "source_value": l.source_value,
            "interpretation": l.interpretation,
            "needs_review": True
        }

    response_data = []
    for asset in assets_list:
        months_data = {}
        for m in range(1, 13):
            o_data = orders_map.get(asset.id, {}).get(m)
            l_data = legacy_map.get(asset.id, {}).get(m)
            if o_data:
                months_data[m] = o_data
            elif l_data:
                months_data[m] = l_data
            else:
                months_data[m] = None

        response_data.append({
            "asset_id": asset.id,
            "patrimonio": asset.patrimonio,
            "description": asset.description,
            "type": asset.type,
            "months": months_data
        })

    return response_data

@app.post("/planning/generate-orders")
async def generate_future_orders(horizon_months: int = 3, db: AsyncSession = Depends(get_db)):
    from app.planning_service import generate_future_maintenance_orders

    summary = await generate_future_maintenance_orders(db, horizon_months=horizon_months)
    await db.commit()
    return {
        **summary,
        "message": (
            "Planejamento processado pelo serviço oficial. "
            f"{summary['orders_created']} ordens geradas para os próximos {horizon_months} meses."
        ),
    }

@app.get("/quality/indicators")
async def get_quality_indicators(year: int, consolidado: bool = False, type: Optional[str] = None, sector_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    from app.models import DowntimeRecord, MaintenanceIssue, MaintenanceOrderItem, MaterialRequest, QualityConfig

    # Obter meta
    meta_result = await db.execute(select(QualityConfig).where(QualityConfig.key == "maintenance_target_pct"))
    meta_val = meta_result.scalars().first()
    meta = int(meta_val.value) if meta_val else 90

    # Query de ordens do ano
    q = select(MaintenanceOrder).join(Asset).where(MaintenanceOrder.planned_year == year)
    if type:
        q = q.where(Asset.type == type)
    if sector_id:
        q = q.where(Asset.sector_id == sector_id)

    res = await db.execute(q)
    orders = res.scalars().all()
    order_ids = [o.id for o in orders]

    today = local_today()

    def _confirmed(order: MaintenanceOrder) -> bool:
        return not bool(order.needs_review)

    def _ids(items):
        return [item.id for item in items]

    def _completion_deadline(order: MaintenanceOrder):
        if order.planned_date:
            return order.planned_date
        if order.planned_year and order.planned_month:
            import calendar
            from datetime import date as date_cls

            last_day = calendar.monthrange(order.planned_year, order.planned_month)[1]
            return date_cls(order.planned_year, order.planned_month, last_day)
        return None

    def _completed_on_time(order: MaintenanceOrder) -> bool:
        if order.execution_status != "completed" or not order.completed_at:
            return False
        deadline = _completion_deadline(order)
        if not deadline:
            return True
        return order.completed_at.date() <= deadline

    confirmed_orders = [o for o in orders if _confirmed(o)]
    planned_orders = [o for o in confirmed_orders if o.execution_status != "cancelled"]
    completed_orders = [o for o in confirmed_orders if o.execution_status == "completed"]
    on_time_orders = [o for o in completed_orders if _completed_on_time(o)]
    late_completed_orders = [o for o in completed_orders if not _completed_on_time(o)]
    overdue_orders = [
        o for o in confirmed_orders
        if o.execution_status not in {"completed", "cancelled"}
        and effective_open_status(o, today) == "overdue"
    ]
    cancelled_orders = [o for o in confirmed_orders if o.execution_status == "cancelled"]
    review_orders = [o for o in orders if bool(o.needs_review)]

    planejado = len(planned_orders)
    realizado_no_prazo = len(on_time_orders)
    realizado_com_atraso = len(late_completed_orders)
    atrasado_atual_confirmado = len(overdue_orders)
    cancelado = len(cancelled_orders)
    a_conferir = len(review_orders)

    # Calcular cumprimento
    cumprimento_anual = 0.0
    if planejado > 0:
        cumprimento_anual = (realizado_no_prazo / planejado) * 100

    # Cumprimento mensal
    cumprimento_mensal = {}
    for m in range(1, 13):
        m_orders = [o for o in planned_orders if o.planned_month == m]
        m_on_time = [o for o in m_orders if _completed_on_time(o)]
        m_plan = len(m_orders)
        m_real = len(m_on_time)
        cumprimento_mensal[m] = {
            "planejado": m_plan,
            "realizado": m_real,
            "pct": (m_real / m_plan * 100) if m_plan > 0 else 100.0,
            "order_ids": _ids(m_orders),
            "realizado_order_ids": _ids(m_on_time),
        }

    # Ativos sem plano
    all_assets_res = await db.execute(select(Asset).where(Asset.status == "active"))
    all_assets = all_assets_res.scalars().all()
    sem_plano_count = 0
    for asset in all_assets:
        plan_res = await db.execute(select(MaintenancePlan).where(MaintenancePlan.asset_id == asset.id))
        if not plan_res.scalars().first():
            sem_plano_count += 1

    # Máquinas paradas
    paradas_query = select(Asset).where(Asset.is_operable == 0)
    if type:
        paradas_query = paradas_query.where(Asset.type == type)
    if sector_id:
        paradas_query = paradas_query.where(Asset.sector_id == sector_id)
    paradas_res = await db.execute(paradas_query)
    paradas_count = len(paradas_res.scalars().all())
    open_orders = [o for o in confirmed_orders if o.execution_status in (None, "not_started") and effective_open_status(o, today) in ("scheduled", "today", "overdue")]
    in_progress_orders = [o for o in confirmed_orders if o.execution_status == "in_progress"]
    issue_completed_orders = [o for o in completed_orders if o.status == "completed_with_issues"]
    abertas = len(open_orders)
    em_execucao = len(in_progress_orders)
    concluidas = len(completed_orders)
    concluidas_com_pendencia = len(issue_completed_orders)

    itens_total = 0
    itens_respondidos = 0
    pendencias_material = 0
    corretivas_abertas = 0
    paradas_abertas = 0
    if order_ids:
        items_res = await db.execute(
            select(MaintenanceOrderItem).where(MaintenanceOrderItem.order_id.in_(order_ids))
        )
        order_items = items_res.scalars().all()
        itens_total = len(order_items)
        itens_respondidos = len([item for item in order_items if item.status and item.status != "unanswered"])

        material_res = await db.execute(
            select(MaterialRequest).where(
                MaterialRequest.order_id.in_(order_ids),
                MaterialRequest.status.notin_(["applied", "cancelled"]),
            )
        )
        pendencias_material = len(material_res.scalars().all())

        issue_res = await db.execute(
            select(MaintenanceIssue).where(
                MaintenanceIssue.order_id.in_(order_ids),
                MaintenanceIssue.status == "open",
            )
        )
        corretivas_abertas = len(issue_res.scalars().all())

        downtime_res = await db.execute(
            select(DowntimeRecord).where(
                DowntimeRecord.order_id.in_(order_ids),
                DowntimeRecord.ended_at == None,
            )
        )
        paradas_abertas = len(downtime_res.scalars().all())

    preenchimento_pct = (itens_respondidos / itens_total * 100) if itens_total else 100.0

    composition = {
        "filters": {"year": year, "type": type, "sector_id": sector_id, "consolidado": consolidado},
        "rules": {
            "planned_base": "OMs do ano filtrado sem needs_review e não canceladas.",
            "on_time": "OM concluída com completed_at até planned_date; para competência mensal, até o último dia do mês.",
            "overdue": "Calculado em tempo real por data/competência, sem depender de status gravado.",
            "review": "OMs com needs_review verdadeiro ficam fora do cumprimento e entram em a_conferir.",
        },
        "metrics": {
            "total_ordens": {"count": len(orders), "order_ids": _ids(orders)},
            "planejado": {"count": planejado, "order_ids": _ids(planned_orders)},
            "realizado_no_prazo": {"count": realizado_no_prazo, "order_ids": _ids(on_time_orders)},
            "realizado_com_atraso": {"count": realizado_com_atraso, "order_ids": _ids(late_completed_orders)},
            "atrasado_atual_confirmado": {"count": atrasado_atual_confirmado, "order_ids": _ids(overdue_orders)},
            "cancelado": {"count": cancelado, "order_ids": _ids(cancelled_orders)},
            "a_conferir": {"count": a_conferir, "order_ids": _ids(review_orders)},
            "abertas": {"count": abertas, "order_ids": _ids(open_orders)},
            "em_execucao": {"count": em_execucao, "order_ids": _ids(in_progress_orders)},
            "concluidas": {"count": concluidas, "order_ids": _ids(completed_orders)},
            "concluidas_com_pendencia": {"count": concluidas_com_pendencia, "order_ids": _ids(issue_completed_orders)},
        },
    }

    return {
        "total_ordens": len(orders),
        "planejado": planejado,
        "realizado_no_prazo": realizado_no_prazo,
        "realizado_com_atraso": realizado_com_atraso,
        "atrasado_atual_confirmado": atrasado_atual_confirmado,
        "cancelado": cancelado,
        "a_conferir": a_conferir,
        "abertas": abertas,
        "em_execucao": em_execucao,
        "concluidas": concluidas,
        "concluidas_com_pendencia": concluidas_com_pendencia,
        "pendencias_material": pendencias_material,
        "corretivas_abertas": corretivas_abertas,
        "paradas_abertas": paradas_abertas,
        "itens_total": itens_total,
        "itens_respondidos": itens_respondidos,
        "preenchimento_pct": preenchimento_pct,
        "cumprimento_anual": cumprimento_anual,
        "cumprimento_mensal": cumprimento_mensal,
        "ativos_sem_plano": sem_plano_count,
        "maquinas_paradas": paradas_count,
        "meta": meta,
        "composition": composition,
    }

@app.get("/quality/indicators/drilldown")
async def get_quality_indicator_drilldown(
    year: int,
    metric: str,
    consolidado: bool = False,
    type: Optional[str] = None,
    sector_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    indicators = await get_quality_indicators(year=year, consolidado=consolidado, type=type, sector_id=sector_id, db=db)
    metric_data = (indicators.get("composition") or {}).get("metrics", {}).get(metric)
    if not metric_data:
        return {"metric": metric, "items": [], "total": 0, "rules": (indicators.get("composition") or {}).get("rules", {})}
    order_ids = metric_data.get("order_ids") or []
    if not order_ids:
        return {"metric": metric, "items": [], "total": 0, "rules": (indicators.get("composition") or {}).get("rules", {})}
    res = await db.execute(
        select(MaintenanceOrder)
        .where(MaintenanceOrder.id.in_(order_ids))
        .options(selectinload(MaintenanceOrder.asset).selectinload(Asset.sector))
        .order_by(MaintenanceOrder.planned_year, MaintenanceOrder.planned_month, MaintenanceOrder.friendly_number)
    )
    orders = res.scalars().all()
    return {
        "metric": metric,
        "total": len(orders),
        "count_from_indicator": metric_data.get("count"),
        "rules": (indicators.get("composition") or {}).get("rules", {}),
        "items": [
            {
                "id": o.id,
                "friendly_number": o.friendly_number,
                "asset_id": o.asset_id,
                "asset_patrimonio": o.asset.patrimonio if o.asset else None,
                "asset_description": o.asset.description if o.asset else None,
                "sector": o.asset.sector.name if o.asset and o.asset.sector else None,
                "planned_year": o.planned_year,
                "planned_month": o.planned_month,
                "planned_date": o.planned_date.isoformat() if o.planned_date else None,
                "status": o.status,
                "execution_status": o.execution_status,
                "started_at": o.started_at.isoformat() if o.started_at else None,
                "completed_at": o.completed_at.isoformat() if o.completed_at else None,
                "operator_name": o.operator_name,
                "needs_review": o.needs_review,
                "final_condition": o.final_condition,
            }
            for o in orders
        ],
    }

@app.get("/quality/review")
async def get_orders_to_review(db: AsyncSession = Depends(get_db)):
    # Retorna ordens marcadas com needs_review = True
    q = select(MaintenanceOrder).where(MaintenanceOrder.needs_review == 1).options(
        selectinload(MaintenanceOrder.asset).selectinload(Asset.sector)
    ).order_by(MaintenanceOrder.planned_year, MaintenanceOrder.planned_month)
    res = await db.execute(q)
    return res.scalars().all()

@app.post("/quality/review/{order_id}")
async def resolve_order_review(order_id: str, decision: str, notes: Optional[str] = None, operator_name: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    # Decisões possíveis: 'completed_on_time', 'completed_with_delay', 'not_applicable', 'cancelled'
    q = select(MaintenanceOrder).where(MaintenanceOrder.id == order_id)
    res = await db.execute(q)
    db_order = res.scalars().first()
    if not db_order:
        raise HTTPException(status_code=404, detail="Ordem não encontrada")

    db_order.needs_review = False
    db_order.review_decision = decision
    db_order.review_operator = operator_name
    db_order.review_at = utcnow_naive()
    db_order.review_notes = notes

    if decision == 'completed_on_time':
        db_order.status = 'completed'
        db_order.execution_status = 'completed'
        db_order.completed_at = db_order.started_at or utcnow_naive()
    elif decision == 'completed_with_delay':
        db_order.status = 'completed_with_issues'
        db_order.execution_status = 'completed'
        db_order.completed_at = utcnow_naive()
    elif decision in ['not_applicable', 'cancelled']:
        db_order.status = 'cancelled'
        db_order.execution_status = 'cancelled'

    await db.flush()
    await db.commit()
    return {"message": "Revisão registrada com sucesso."}

# --- SERVIR FRONTEND ESTÁTICO (HOMOLOGAÇÃO/PRODUÇÃO) ---
from fastapi.staticfiles import StaticFiles

# Certificar que o diretório de uploads existe
os.makedirs(UPLOADS_DIR, exist_ok=True)
frontend_dist = os.path.join(BASE_DIR, "frontend", "dist")

static_assets_dir = os.path.join(frontend_dist, "static-assets")
if os.path.exists(static_assets_dir):
    app.mount("/static-assets", StaticFiles(directory=static_assets_dir), name="static_assets")

FRONTEND_SHELL_HEADERS = {
    # A página HTML nunca pode permanecer presa a uma versão anterior: ela é
    # quem aponta para os arquivos JavaScript com nome/hash da versão atual.
    # Isso evita a tela branca após atualização em PCs que ficam ligados.
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def frontend_shell_response(index_path: str) -> FileResponse:
    return FileResponse(index_path, headers=FRONTEND_SHELL_HEADERS)


@app.get("/sw.js")
@app.get("/index.html")
@app.get("/manifest.webmanifest")
@app.get("/favicon.svg")
@app.get("/icons.svg")
@app.get("/mec-maintenance-icon.svg")
@app.get("/icon-192.png")
@app.get("/icon-512.png")
async def get_frontend_root_asset(request: Request):
    filename = request.url.path.lstrip("/")
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Caminho de arquivo inválido.")
    file_path = os.path.join(frontend_dist, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    if filename in {"sw.js", "index.html", "manifest.webmanifest"}:
        return FileResponse(file_path, headers=FRONTEND_SHELL_HEADERS)
    return FileResponse(file_path)

# Servir uploads de forma segura (impedindo Path Traversal e listagem de diretório)
@app.get("/data/uploads/{filename}")
@app.get("/backend/uploads/{filename}")
async def get_uploaded_file(filename: str):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Caminho de arquivo inválido.")

    file_path = os.path.join(UPLOADS_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")

    return FileResponse(file_path)


# Rotas internas que começam com nomes também usados pela API. Sem esta
# exceção, abrir um favorito ou atualizar a página do checklist faria o
# catch-all protegê-las como se fossem endpoints da API e retornaria 404.
# Os botões do React funcionavam; o problema aparecia somente em acesso direto
# (por exemplo, após reabrir o navegador/tablet na mesma tela).
@app.get("/checklists/iniciar")
@app.get("/ordens/{order_id}")
async def serve_spa_direct_operation_route(order_id: Optional[str] = None):
    index_path = os.path.join(frontend_dist, "index.html")
    if os.path.exists(index_path):
        return frontend_shell_response(index_path)
    return HTMLResponse("<!doctype html><html><body><div id='root'>Manutenção em Campo</div></body></html>")


# --- SPA CATCH-ALL ROUTE ---
@app.get("/{path:path}")
async def spa_catchall(request: Request, path: str):
    # Exclude technical endpoints
    path_parts = path.strip("/").split("/")
    first_part = path_parts[0] if path_parts else ""

    EXCLUDED_PREFIXES = {
        "api", "v2", "health", "ping", "docs", "redoc", "openapi.json",
        "operators", "orders", "assets", "plans", "checklists", "sectors",
        "issues", "backup", "reports", "quality",
        "planning", "resolve-token", "data", "backend", "thumbnails",
        "static-assets"
    }

    if first_part in EXCLUDED_PREFIXES:
        raise HTTPException(status_code=404, detail="Not Found")

    # Prevent intercepting static file requests that do not exist (contain a dot in filename)
    if "." in first_part or (len(path_parts) > 1 and "." in path_parts[-1]):
        raise HTTPException(status_code=404, detail="Not Found")

    index_path = os.path.join(frontend_dist, "index.html")
    if os.path.exists(index_path):
        return frontend_shell_response(index_path)
    return HTMLResponse("<!doctype html><html><body><div id='root'>Manutenção em Campo</div></body></html>")
