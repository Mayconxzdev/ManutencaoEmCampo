import json
import uuid
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Asset,
    ChecklistTemplate,
    ChecklistItem,
    MaintenancePlan,
    MaintenanceOrder,
    MaintenanceMaterial,
    EpiCatalog,
    SafetyHazard,
    SafetyTask,
    EpiRule,
    EpiRuleItem,
    EpiRuleSource,
    EpiSuggestion,
    EpiRequirement
)

def gen_uuid() -> str:
    return str(uuid.uuid4())

# ============================================================
# 1. MOTOR DE RESOLUÇÃO DE EPI (HIERARQUIA E EXCEÇÕES)
# ============================================================

async def resolve_epis_for_plan(db: AsyncSession, plan_id: str) -> List[Dict[str, Any]]:
    """
    Resolve a lista final de EPIs para um plano combinando as regras de acordo com a hierarquia:
    1. Regra geral da planta (plant) [Menos específica]
    2. Regra do setor (sector)
    3. Regra do tipo de ativo (asset_type)
    4. Regra da família do ativo (asset_family)
    5. Regra do fabricante/modelo (manufacturer_model)
    6. Regra do checklist (checklist_template)
    7. Regra da tarefa (task)
    8. Regra do plano (plan)
    9. Regra específica do ativo (asset) [Mais específica]

    A regra mais específica sobrepõe regras gerais em caso de colisão por categoria de EPI.
    """
    # 1. Obter informações completas do plano e ativo
    plan_res = await db.execute(
        select(MaintenancePlan)
        .where(MaintenancePlan.id == plan_id)
        .options(
            selectinload(MaintenancePlan.asset),
            selectinload(MaintenancePlan.epi_requirements)
        )
    )
    plan = plan_res.scalars().first()
    if not plan:
        return []

    asset = plan.asset
    if not asset:
        return []

    # 2. Identificar escopos aplicáveis
    scopes = [('plant', 'global')]
    if asset.sector_id:
        scopes.append(('sector', asset.sector_id))
        from app.models import Sector
        sec_res = await db.execute(select(Sector.name).where(Sector.id == asset.sector_id))
        sec_name = sec_res.scalar()
        if sec_name:
            scopes.append(('sector', sec_name.lower()))
    if asset.type:
        scopes.append(('asset_type', asset.type))
    # Família de ativos baseada na primeira palavra da descrição
    family = asset.description.split()[0].strip(',').lower() if asset.description else 'general'
    scopes.append(('asset_family', family))
    if asset.manufacturer:
        scopes.append(('manufacturer_model', asset.manufacturer.lower()))
    if asset.model:
        scopes.append(('manufacturer_model', asset.model.lower()))
    if asset.manufacturer or asset.model:
        key = f"{asset.manufacturer or ''}|{asset.model or ''}".lower()
        scopes.append(('manufacturer_model', key))

    if plan.checklist_template_version_id:
        from app.models import ChecklistTemplateVersion, ChecklistItem, SafetyTask
        version_res = await db.execute(
            select(ChecklistTemplateVersion)
            .where(ChecklistTemplateVersion.id == plan.checklist_template_version_id)
        )
        version = version_res.scalars().first()
        if version:
            scopes.append(('checklist_template', version.template_id))
            scopes.append(('checklist_version', version.id))

            # Adicionar escopos de tarefa baseados nos itens do checklist
            items_res = await db.execute(
                select(ChecklistItem).where(ChecklistItem.version_id == version.id)
            )
            items = items_res.scalars().all()

            st_res = await db.execute(select(SafetyTask))
            safety_tasks = st_res.scalars().all()

            for item in items:
                scopes.append(('task', item.id))
                scopes.append(('task', item.description))
                for st in safety_tasks:
                    if st.name.lower() in item.description.lower():
                        scopes.append(('task', st.id))
                        scopes.append(('task', st.name))

    scopes.append(('plan', plan.id))
    scopes.append(('asset', asset.id))

    # 3. Buscar todas as regras aprovadas para esses escopos com validação de vigência
    conditions = []
    for scope_type, scope_id in scopes:
        conditions.append(and_(EpiRule.scope == scope_type, EpiRule.scope_id == scope_id))

    rules_res = await db.execute(
        select(EpiRule)
        .where(
            and_(
                EpiRule.status == 'approved',
                or_(*conditions),
                or_(EpiRule.valid_from == None, EpiRule.valid_from <= date.today()),
                or_(EpiRule.valid_until == None, EpiRule.valid_until >= date.today())
            )
        )
        .options(selectinload(EpiRule.rule_items).selectinload(EpiRuleItem.epi_catalog))
    )
    rules = rules_res.scalars().all()

    # Filtrar regras que foram substituídas (superseded) por alguma regra ativa
    superseded_ids = {r.supersedes_rule_id for r in rules if r.supersedes_rule_id}
    rules = [r for r in rules if r.id not in superseded_ids]

    # 4. Ordenar regras por especificidade (plant=1, sector=2, ..., asset=10)
    specificity_order = {
        'plant': 1,
        'sector': 2,
        'asset_type': 3,
        'asset_family': 4,
        'manufacturer_model': 5,
        'checklist_template': 6,
        'checklist_version': 7,
        'task': 8,
        'plan': 9,
        'asset': 10
    }

    # Agrupar itens de regra resolvidos por categoria de EPI
    # Estrutura: {categoria: (especificidade, item_resolvido_dict)}
    resolved_by_category: Dict[str, Tuple[int, Dict[str, Any]]] = {}

    # Identificar riscos de partes giratórias/rotativas expostas na checklist
    has_rotating_parts = False
    if plan.checklist_template_version_id:
        items_res = await db.execute(
            select(ChecklistItem).where(ChecklistItem.version_id == plan.checklist_template_version_id)
        )
        for item in items_res.scalars().all():
            desc_lower = item.description.lower()
            if any(w in desc_lower for w in ['giratór', 'rotativ', 'polia', 'engrenagem', 'eixo em movimento']):
                has_rotating_parts = True
                break

    for rule in rules:
        spec = specificity_order.get(rule.scope, 1)
        for item in rule.rule_items:
            cat = item.epi_catalog
            if not cat or not cat.ativo:
                continue

            # Regra de proteção: partes giratórias expostas impedem luvas normais (enroscamento)
            if has_rotating_parts and cat.category == 'proteção das mãos':
                # Só permitir luva específica se a regra for de escopo alto (ex: plan ou asset)
                # e tiver justificativa explícita de segurança contra enroscamento.
                if spec < 8 and 'luva' in cat.name.lower() and 'isolante' not in cat.name.lower():
                    # Ignorar luvas gerais de raspa/vaqueta que podem enroscar
                    continue

            item_dict = {
                "id": cat.id,
                "item_name": cat.name,
                "ca_number": None,
                "validity": "Vigente",
                "is_mandatory": item.obrigatoriedade == 'mandatory',
                "category": cat.category,
                "scope": rule.scope,
                "rule_id": rule.id
            }

            # Se não houver item nessa categoria, ou se a especificidade atual for maior
            if cat.category not in resolved_by_category or spec > resolved_by_category[cat.category][0]:
                resolved_by_category[cat.category] = (spec, item_dict)

    # Extrair lista plana ordenada por categoria
    resolved_list = [val[1] for val in resolved_by_category.values()]
    return resolved_list

# ============================================================
# 2. MOTOR DE SUGESTÕES E SIMILARIDADE ENTRE ATIVOS
# ============================================================

async def calculate_asset_similarity_groups(db: AsyncSession, asset_id: str) -> List[Dict[str, Any]]:
    """
    Identifica ativos similares ao informado com base em:
    mesma família (type), mesmo fabricante, mesmo modelo, mesmo setor, mesmos checklists.
    """
    asset_res = await db.execute(select(Asset).where(Asset.id == asset_id))
    source_asset = asset_res.scalars().first()
    if not source_asset:
        return []

    all_assets_res = await db.execute(
        select(Asset).where(and_(Asset.id != asset_id, Asset.status == 'active'))
    )
    all_assets = all_assets_res.scalars().all()

    similar_groups = []
    for target in all_assets:
        score = 0.0
        reasons = []
        if target.type == source_asset.type:
            score += 1.0
            reasons.append("Mesmo tipo de ativo")
        if target.manufacturer and target.manufacturer == source_asset.manufacturer:
            score += 1.5
            reasons.append("Mesmo fabricante")
        if target.model and target.model == source_asset.model:
            score += 2.0
            reasons.append("Mesmo modelo/referência")
        if target.sector_id and target.sector_id == source_asset.sector_id:
            score += 0.5
            reasons.append("Mesmo setor operacional")

        if score >= 2.0:
            similar_groups.append({
                "asset_id": target.id,
                "patrimonio": target.patrimonio,
                "description": target.description,
                "score": score,
                "reasons": reasons
            })

    return sorted(similar_groups, key=lambda x: x['score'], reverse=True)

async def generate_epi_suggestions_for_plan(db: AsyncSession, plan_id: str) -> Optional[EpiSuggestion]:
    """
    Gera uma sugestão de EPI baseada em regras de ativos similares, checklists e análise textual determinística.
    Não aprova automaticamente.
    """
    plan_res = await db.execute(
        select(MaintenancePlan).where(MaintenancePlan.id == plan_id).options(selectinload(MaintenancePlan.asset))
    )
    plan = plan_res.scalars().first()
    if not plan or not plan.asset:
        return None

    asset = plan.asset

    # 1. Buscar similares que já possuem regras de EPI aprovadas
    similars = await calculate_asset_similarity_groups(db, asset.id)
    similar_rule_items = []
    confidence = 'low'
    reasons = []
    evidence = []

    similar_ids = [s['asset_id'] for s in similars[:5]]
    if similar_ids:
        # Buscar planos dos similares com regras
        sim_plans_res = await db.execute(
            select(MaintenancePlan)
            .where(and_(MaintenancePlan.asset_id.in_(similar_ids), MaintenancePlan.is_active == 1))
            .options(selectinload(MaintenancePlan.epi_requirements))
        )
        sim_plans = sim_plans_res.scalars().all()

        counts = {}
        for sp in sim_plans:
            for req in sp.epi_requirements:
                counts[req.item_name] = counts.get(req.item_name, 0) + 1

        # Se mais de 60% dos similares usam o mesmo EPI, sugerir com confiança média/alta
        for epi_name, cnt in counts.items():
            pct = cnt / len(sim_plans) if sim_plans else 0
            if pct >= 0.5:
                similar_rule_items.append(epi_name)
                evidence.append(f"{cnt} de {len(sim_plans)} ativos similares utilizam '{epi_name}'")
                confidence = 'high' if pct >= 0.8 else 'medium'

    # 2. Analisar o checklist template (epi_summary extraído do DOCX)
    docx_epis = []
    if plan.checklist_template_version_id:
        from app.models import ChecklistTemplateVersion
        ver_res = await db.execute(
            select(ChecklistTemplateVersion)
            .where(ChecklistTemplateVersion.id == plan.checklist_template_version_id)
            .options(selectinload(ChecklistTemplateVersion.template))
        )
        ver = ver_res.scalars().first()
        if ver and ver.template and ver.template.epi_summary:
            try:
                docx_epis = json.loads(ver.template.epi_summary)
                if docx_epis:
                    evidence.append(f"Extraído do documento original do checklist: {ver.source_document or 'checklists'}")
                    confidence = 'high' if confidence == 'high' else 'medium'
            except Exception:
                pass

    # Combinar sugestões
    suggested_names = list(set(similar_rule_items + docx_epis))
    if not suggested_names:
        # Fallback de busca de termos na checklist
        checklist_items_res = await db.execute(
            select(ChecklistItem).where(ChecklistItem.version_id == plan.checklist_template_version_id) if plan.checklist_template_version_id else select(ChecklistItem).where(False)
        )
        checklist_text = " ".join([i.description.lower() for i in checklist_items_res.scalars().all()])

        # Mapeamento de palavras-chave
        catalog_res = await db.execute(select(EpiCatalog).where(EpiCatalog.ativo == 1))
        for epi in catalog_res.scalars().all():
            keywords = epi.name.lower().split()
            if any(k in checklist_text for k in keywords if len(k) > 3):
                suggested_names.append(epi.name)
                evidence.append(f"Termo coincidente '{epi.name}' encontrado nas tarefas do checklist.")
                confidence = 'low'

    if not suggested_names:
        return None

    # Salvar sugestão no banco
    # Carregar ids do catálogo correspondentes
    suggested_items_detail = []
    for name in suggested_names:
        cat_res = await db.execute(select(EpiCatalog).where(func.lower(EpiCatalog.name) == name.lower()))
        cat = cat_res.scalars().first()
        if cat:
            suggested_items_detail.append({
                "epi_catalog_id": cat.id,
                "name": cat.name,
                "category": cat.category,
                "is_mandatory": True
            })

    # Detectar perigos na checklist
    hazards_detected = []
    checklist_text_full = ""
    if plan.checklist_template_version_id:
        items_res = await db.execute(select(ChecklistItem).where(ChecklistItem.version_id == plan.checklist_template_version_id))
        checklist_text_full = " ".join([i.description.lower() for i in items_res.scalars().all()])

    hazard_keywords = {
        'eletricidade': ['elétr', 'tensão', 'painel', 'fiação', 'disjuntor'],
        'partes giratórias': ['polia', 'eixo', 'correia', 'engrenagem', 'rotativo', 'girató'],
        'altura': ['altura', 'cinto', 'plataforma', 'escada', 'andaime'],
        'produto químico': ['químico', 'ácido', 'solvente', 'óleo', 'lubrif', 'graxa', 'limpeza'],
        'ruído': ['ruído', 'barulho', 'compressor', 'motor'],
        'superfície quente': ['quente', 'temperatura', 'aquec', 'respar', 'calor']
    }
    for haz, kws in hazard_keywords.items():
        if any(kw in checklist_text_full for kw in kws):
            hazards_detected.append(haz)

    # Remover sugestão antiga se houver
    await db.execute(
        sa.text("DELETE FROM epi_suggestions WHERE plan_id = :pid AND status = 'suggested'"),
        {"pid": plan.id}
    )

    suggestion = EpiSuggestion(
        id=gen_uuid(),
        plan_id=plan.id,
        checklist_template_id=ver.template_id if (plan.checklist_template_version_id and 'ver' in locals() and ver) else None,
        asset_id=asset.id,
        items_json=json.dumps(suggested_items_detail, ensure_ascii=False),
        hazards_json=json.dumps(hazards_detected, ensure_ascii=False),
        confidence=confidence,
        evidence_json=json.dumps(evidence, ensure_ascii=False),
        similarity_score=float(len(similars)),
        status='suggested'
    )
    db.add(suggestion)
    await db.commit()
    return suggestion

# ============================================================
# 3. INTELIGÊNCIA PARA MATERIAIS E FERRAMENTAS
# ============================================================

async def suggest_materials_for_plan(db: AsyncSession, plan_id: str) -> List[Dict[str, Any]]:
    """
    Analisa histórico de consumo real de materiais e propõe para o plano.
    Classifica como: 'mandatory', 'recommended', 'frequently_used', 'exceptional'.
    """
    plan_res = await db.execute(
        select(MaintenancePlan).where(MaintenancePlan.id == plan_id).options(selectinload(MaintenancePlan.orders))
    )
    plan = plan_res.scalars().first()
    if not plan:
        return []

    # 1. Carregar materiais consumidos nas últimas 10 execuções concluídas
    orders_res = await db.execute(
        select(MaintenanceOrder)
        .where(and_(MaintenanceOrder.plan_id == plan_id, MaintenanceOrder.execution_status == 'completed'))
        .order_by(MaintenanceOrder.completed_at.desc())
        .limit(10)
        .options(selectinload(MaintenanceOrder.materials))
    )
    last_orders = orders_res.scalars().all()
    if not last_orders:
        return []

    material_counts = {}
    for o in last_orders:
        for m in o.materials:
            material_counts[m.name] = material_counts.get(m.name, 0) + 1

    suggestions = []
    total_orders = len(last_orders)

    # 2. Classificar materiais com base no percentual de ocorrência
    for name, cnt in material_counts.items():
        ratio = cnt / total_orders
        if ratio >= 0.8:
            classification = 'mandatory'
            desc = "Utilizado em quase todas as manutenções (mais de 80% das execuções)."
        elif ratio >= 0.5:
            classification = 'recommended'
            desc = f"Frequente: Utilizado em {cnt} de {total_orders} execuções anteriores."
        elif ratio >= 0.2:
            classification = 'frequently_used'
            desc = f"Ocasional: Utilizado em {cnt} de {total_orders} execuções."
        else:
            classification = 'exceptional'
            desc = "Uso raro constatado no histórico."

        suggestions.append({
            "name": name,
            "count_used": cnt,
            "ratio": ratio,
            "classification": classification,
            "description": desc
        })

    return sorted(suggestions, key=lambda x: x['ratio'], reverse=True)

# ============================================================
# 4. INTELIGÊNCIA DE PERIODICIDADE E ESTIMATIVA DE DURAÇÃO
# ============================================================

async def suggest_periodicity_and_duration(db: AsyncSession, plan_id: str) -> Dict[str, Any]:
    """
    Analisa os registros e sugere a periodicidade recomendada (comparando com a cadastrada)
    e calcula a duração estimada ideal limpando anomalias.
    """
    plan_res = await db.execute(select(MaintenancePlan).where(MaintenancePlan.id == plan_id))
    plan = plan_res.scalars().first()
    if not plan:
        return {}

    # Carregar tempos das OMs concluídas válidas (excluindo tempos irreais < 5min ou > 12 horas)
    orders_res = await db.execute(
        select(MaintenanceOrder)
        .where(
            and_(
                MaintenanceOrder.plan_id == plan_id,
                MaintenanceOrder.execution_status == 'completed',
                MaintenanceOrder.duration_mins > 5,
                MaintenanceOrder.duration_mins < 720
            )
        )
    )
    durations = [o.duration_mins for o in orders_res.scalars().all() if o.duration_mins]

    # Calcular mediana limpa
    suggested_duration = plan.estimated_duration_mins
    if durations:
        durations.sort()
        mid = len(durations) // 2
        suggested_duration = int(durations[mid] if len(durations) % 2 != 0 else (durations[mid-1] + durations[mid]) / 2)

    # Analisar periodicidade por intervalo de datas das últimas execuções
    dates_res = await db.execute(
        select(MaintenanceOrder.completed_at)
        .where(and_(MaintenanceOrder.plan_id == plan_id, MaintenanceOrder.execution_status == 'completed'))
        .order_by(MaintenanceOrder.completed_at.desc())
        .limit(5)
    )
    dates = [d[0] for d in dates_res.fetchall() if d[0]]

    suggested_periodicity = plan.periodicity
    periodicity_reason = "Mantida a periodicidade atual por falta de histórico representativo."

    if len(dates) >= 3:
        intervals = []
        for i in range(len(dates) - 1):
            diff = (dates[i] - dates[i+1]).days
            intervals.append(diff)
        avg_days = sum(intervals) / len(intervals)

        if 25 <= avg_days <= 35:
            suggested_periodicity = 'monthly'
            periodicity_reason = f"Média histórica de {int(avg_days)} dias indica periodicidade mensal."
        elif 55 <= avg_days <= 65:
            suggested_periodicity = 'bimonthly'
            periodicity_reason = f"Média histórica de {int(avg_days)} dias indica periodicidade bimestral."
        elif 80 <= avg_days <= 100:
            suggested_periodicity = 'trimonthly'
            periodicity_reason = f"Média histórica de {int(avg_days)} dias indica periodicidade trimestral."
        elif 160 <= avg_days <= 200:
            suggested_periodicity = 'semiannual'
            periodicity_reason = f"Média histórica de {int(avg_days)} dias indica periodicidade semestral."
        elif 340 <= avg_days <= 380:
            suggested_periodicity = 'annual'
            periodicity_reason = f"Média histórica de {int(avg_days)} dias indica periodicidade anual."
        else:
            suggested_periodicity = 'custom'
            periodicity_reason = f"Histórico com média irregular de {int(avg_days)} dias."

    return {
        "plan_id": plan_id,
        "current_duration": plan.estimated_duration_mins,
        "suggested_duration": suggested_duration,
        "current_periodicity": plan.periodicity,
        "suggested_periodicity": suggested_periodicity,
        "periodicity_reason": periodicity_reason,
        "is_different": plan.periodicity != suggested_periodicity or plan.estimated_duration_mins != suggested_duration
    }

# ============================================================
# 5. OTIMIZAÇÃO DE ROTAS
# ============================================================

async def group_orders_in_smart_routes(db: AsyncSession, competence: str) -> List[Dict[str, Any]]:
    """
    Agrupa ordens de manutenção preventivas em rotas otimizadas para uma competência (YYYY-MM).
    Considera setor, data planejada e duração.
    """
    orders_res = await db.execute(
        select(MaintenanceOrder)
        .where(
            and_(
                MaintenanceOrder.original_competence == competence,
                MaintenanceOrder.execution_status == 'not_started'
            )
        )
        .options(selectinload(MaintenanceOrder.asset))
    )
    orders = orders_res.scalars().all()
    if not orders:
        return []

    # Agrupar OMs por Setor e data planejada
    routes_map = {}
    for o in orders:
        sector_id = o.asset.sector_id if o.asset else "global"
        planned_date_str = str(o.planned_date) if o.planned_date else "a_programar"
        key = f"{sector_id}|{planned_date_str}"

        if key not in routes_map:
            routes_map[key] = {
                "sector_id": sector_id,
                "planned_date": planned_date_str,
                "orders": []
            }
        routes_map[key]["orders"].append(o)

    routes_list = []
    idx = 1
    for key, data in routes_map.items():
        total_duration = sum([o.duration_mins or 60 for o in data["orders"]])
        routes_list.append({
            "route_id": f"ROTA-{competence.replace('-', '')}-{idx:02d}",
            "sector_id": data["sector_id"],
            "planned_date": data["planned_date"],
            "orders_count": len(data["orders"]),
            "estimated_duration_mins": total_duration,
            "orders_details": [
                {
                    "id": o.id,
                    "friendly_number": o.friendly_number,
                    "patrimonio": o.asset.patrimonio if o.asset else "N/A",
                    "description": o.asset.description if o.asset else "N/A",
                    "priority": o.priority
                } for o in data["orders"]
            ]
        })
        idx += 1

    return routes_list

# ============================================================
# 6. EVITAR DUPLICIDADE EM CASO DE DEFEITOS/CORRETIVAS
# ============================================================

async def detect_duplicated_correctives(db: AsyncSession, asset_id: str, description: str) -> Optional[Dict[str, Any]]:
    """
    Verifica se já existe uma corretiva aberta para o mesmo ativo e descrição similar.
    """
    desc_words = [w.lower() for w in description.split() if len(w) > 3]
    if not desc_words:
        return None

    open_orders_res = await db.execute(
        select(MaintenanceOrder)
        .where(
            and_(
                MaintenanceOrder.asset_id == asset_id,
                MaintenanceOrder.order_type == 'corrective',
                MaintenanceOrder.execution_status.in_(['not_started', 'in_progress'])
            )
        )
    )
    open_orders = open_orders_res.scalars().all()

    for o in open_orders:
        o_notes = (o.notes or "").lower()
        matches = sum(1 for w in desc_words if w in o_notes)
        ratio = matches / len(desc_words)
        if ratio >= 0.5:
            return {
                "id": o.id,
                "friendly_number": o.friendly_number,
                "created_at": o.started_at.isoformat() if o.started_at else None,
                "notes": o.notes,
                "status": o.execution_status,
                "confidence": "high" if ratio >= 0.8 else "medium"
            }

    return None

# ============================================================
# 7. FILTRAGEM DE ATIVOS INATIVOS CANDIDATOS
# ============================================================

async def detect_candidate_inactive_assets(db: AsyncSession) -> List[Dict[str, Any]]:
    """
    Identifica ativos inativos na prática (sem manutenção há mais de 1 ano).
    """
    active_assets_res = await db.execute(
        select(Asset).where(Asset.status == 'active').options(selectinload(Asset.orders), selectinload(Asset.plans))
    )
    assets = active_assets_res.scalars().all()

    candidates = []
    for a in assets:
        last_order_date = None
        has_future_order = False

        for o in a.orders:
            if o.execution_status == 'completed' and o.completed_at:
                if not last_order_date or o.completed_at > last_order_date:
                    last_order_date = o.completed_at
            elif o.execution_status == 'not_started':
                has_future_order = True

        has_active_plans = any(p.is_active for p in a.plans)

        reasons = []
        if not a.orders:
            reasons.append("Nenhuma Ordem de Manutenção encontrada no histórico.")
        elif last_order_date and (datetime.utcnow() - last_order_date).days > 365:
            reasons.append(f"Última manutenção concluída há {(datetime.utcnow() - last_order_date).days} dias.")

        if not has_active_plans:
            reasons.append("Não possui plano de manutenção preventiva ativo cadastrado.")

        if reasons and not has_future_order:
            candidates.append({
                "id": a.id,
                "patrimonio": a.patrimonio,
                "description": a.description,
                "manufacturer": a.manufacturer,
                "model": a.model,
                "reasons": reasons,
                "last_maintenance": last_order_date.isoformat() if last_order_date else None
            })

    return candidates
