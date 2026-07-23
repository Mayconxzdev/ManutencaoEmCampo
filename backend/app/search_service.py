"""Busca global híbrida leve para Manutenção em Campo.

Base principal: SQLite FTS5, porque o projeto opera com SQLite/Windows/offline.
Quando DATABASE_URL não é SQLite, o serviço cai para LIKE básico sem quebrar.
"""
from __future__ import annotations

import re
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models import (
    Asset,
    AssetDocument,
    AssetDocumentIndex,
    ChecklistItem,
    ChecklistTemplate,
    ChecklistTemplateVersion,
    MaintenanceOrder,
    MaintenancePlan,
    Sector,
)

TOKEN_RE = re.compile(r"[\wÀ-ÿ]+", re.UNICODE)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split())


def _code_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def make_fts_query(query: str, *, max_terms: int = 8) -> str:
    """Converte texto livre em consulta FTS5 segura com busca por prefixo."""
    terms = []
    for token in TOKEN_RE.findall(query or ""):
        token = token.strip("_").lower()
        if len(token) < 2 and not token.isdigit():
            continue
        if token not in terms:
            terms.append(token)
        if len(terms) >= max_terms:
            break
    return " OR ".join(f"{term}*" for term in terms)


async def fts5_available(db: AsyncSession) -> bool:
    try:
        await db.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS temp.__mec_fts_probe USING fts5(value)"))
        await db.execute(text("DROP TABLE IF EXISTS temp.__mec_fts_probe"))
        return True
    except Exception:
        return False


async def ensure_search_schema(db: AsyncSession) -> bool:
    """Cria a tabela FTS5 se o banco suportar. Retorna False no fallback."""
    if not await fts5_available(db):
        return False
    await db.execute(text("""
        CREATE VIRTUAL TABLE IF NOT EXISTS global_search_fts USING fts5(
            entity_type,
            entity_id UNINDEXED,
            title,
            body,
            metadata UNINDEXED,
            tokenize = 'unicode61 remove_diacritics 2'
        )
    """))
    return True


async def _fts_count(db: AsyncSession) -> int:
    try:
        value = (await db.execute(text("SELECT count(*) FROM global_search_fts"))).scalar()
        return int(value or 0)
    except Exception:
        return 0


async def rebuild_search_index(db: AsyncSession) -> dict[str, int | bool]:
    """Reconstrói o índice local auditável sem alterar tabelas de negócio."""
    if await fts5_available(db):
        await db.execute(text("DROP TABLE IF EXISTS global_search_fts"))
        await db.commit()

    enabled = await ensure_search_schema(db)
    if not enabled:
        return {"fts5": False, "indexed": 0}
    await db.commit()
    await db.execute(text("SELECT count(*) FROM global_search_fts"))
    indexed = 0

    sectors = {s.id: s.name for s in (await db.execute(select(Sector))).scalars().all()}

    assets = (await db.execute(select(Asset))).scalars().all()
    assets_by_id = {asset.id: asset for asset in assets}
    for asset in assets:
        title = f"{asset.patrimonio} · {asset.description}"
        body = " ".join(_clean(x) for x in [
            asset.type,
            asset.description,
            asset.manufacturer,
            asset.model,
            asset.serial_number,
            sectors.get(asset.sector_id),
            asset.status,
            asset.notes,
            asset.manual,
            asset.ficha_tecnica,
            asset.caminho_documentos,
        ])
        await db.execute(text("""
            INSERT INTO global_search_fts(entity_type, entity_id, title, body, metadata)
            VALUES ('asset', :id, :title, :body, :metadata)
        """), {"id": asset.id, "title": title, "body": body, "metadata": asset.patrimonio})
        indexed += 1

    docs = (await db.execute(select(AssetDocument))).scalars().all()
    for doc in docs:
        asset = assets_by_id.get(doc.asset_id)
        body = " ".join(_clean(x) for x in [
            doc.original_name,
            doc.category,
            doc.origin,
            doc.mime_type,
            asset.patrimonio if asset else None,
            asset.description if asset else None,
            doc.original_path,
        ])
        title = doc.name or doc.original_name or "Arquivo"
        if asset and asset.patrimonio:
            title = f"{title} · {asset.patrimonio}"
        await db.execute(text("""
            INSERT INTO global_search_fts(entity_type, entity_id, title, body, metadata)
            VALUES ('asset_file', :id, :title, :body, :metadata)
        """), {"id": doc.id, "title": title, "body": body, "metadata": doc.asset_id})
        indexed += 1

    linked_docs = (await db.execute(select(AssetDocumentIndex))).scalars().all()
    for doc in linked_docs:
        asset = assets_by_id.get(doc.asset_id)
        body = " ".join(_clean(x) for x in [
            doc.file_name,
            doc.document_type,
            doc.extracted_text,
            doc.notes,
            asset.patrimonio if asset else None,
            asset.description if asset else None,
            doc.file_path,
        ])
        title = doc.file_name
        if asset and asset.patrimonio:
            title = f"{title} · {asset.patrimonio}"
        await db.execute(text("""
            INSERT INTO global_search_fts(entity_type, entity_id, title, body, metadata)
            VALUES ('legacy_document', :id, :title, :body, :metadata)
        """), {"id": doc.id, "title": title, "body": body, "metadata": doc.asset_id})
        indexed += 1

    plans = (await db.execute(select(MaintenancePlan))).scalars().all()
    for plan in plans:
        body = " ".join(_clean(x) for x in [
            plan.name,
            plan.periodicity,
            plan.frequency_days,
            plan.frequency_months,
            plan.planned_month,
            plan.confidence,
            plan.source_document,
            plan.source_document_page,
            plan.safety_instructions,
            plan.recurrence_status,
        ])
        await db.execute(text("""
            INSERT INTO global_search_fts(entity_type, entity_id, title, body, metadata)
            VALUES ('plan', :id, :title, :body, :metadata)
        """), {"id": plan.id, "title": plan.name, "body": body, "metadata": plan.asset_id})
        indexed += 1

    orders = (await db.execute(select(MaintenanceOrder).limit(5000))).scalars().all()
    for order in orders:
        title = f"OM {order.friendly_number or ''}".strip()
        body = " ".join(_clean(x) for x in [
            order.status,
            order.execution_status,
            order.priority,
            order.final_condition,
            order.notes,
            order.source_note,
            order.reschedule_reason,
            order.operator_name,
        ])
        await db.execute(text("""
            INSERT INTO global_search_fts(entity_type, entity_id, title, body, metadata)
            VALUES ('order', :id, :title, :body, :metadata)
        """), {"id": order.id, "title": title, "body": body, "metadata": order.asset_id})
        indexed += 1

    checklist_rows = await db.execute(
        select(ChecklistItem, ChecklistTemplateVersion, ChecklistTemplate)
        .join(ChecklistTemplateVersion, ChecklistItem.version_id == ChecklistTemplateVersion.id)
        .join(ChecklistTemplate, ChecklistTemplateVersion.template_id == ChecklistTemplate.id)
        .limit(10000)
    )
    for item, version, template in checklist_rows.all():
        title = f"{template.name} · item {item.item_number}"
        body = " ".join(_clean(x) for x in [
            template.code_reference,
            template.asset_type,
            template.asset_patrimonio,
            template.asset_manufacturer,
            template.asset_model_ref,
            template.rq_cmp_reference,
            item.description,
            item.suggested_materials,
            item.not_applicable_reasons,
            version.source_document,
        ])
        await db.execute(text("""
            INSERT INTO global_search_fts(entity_type, entity_id, title, body, metadata)
            VALUES ('checklist_item', :id, :title, :body, :metadata)
        """), {"id": item.id, "title": title, "body": body, "metadata": template.id})
        indexed += 1

    await db.commit()
    return {"fts5": True, "indexed": indexed}


async def search_global(
    db: AsyncSession,
    query: str,
    *,
    entity_type: Optional[str] = None,
    limit: int = 30,
    rebuild_if_empty: bool = True,
) -> dict[str, Any]:
    cleaned_query = _clean(query)
    if len(cleaned_query) < 2:
        return {"query": cleaned_query, "backend": "none", "items": [], "total": 0}

    enabled = await ensure_search_schema(db)
    if enabled and rebuild_if_empty and await _fts_count(db) == 0:
        await rebuild_search_index(db)
    fts_query = make_fts_query(cleaned_query)
    if enabled and fts_query:
        where_type = "AND global_search_fts.entity_type = :entity_type" if entity_type else ""
        sql = text(f"""
            SELECT
                global_search_fts.entity_type,
                global_search_fts.entity_id,
                global_search_fts.title,
                snippet(global_search_fts, 3, '<b>', '</b>', '…', 12) AS snippet,
                global_search_fts.metadata,
                bm25(global_search_fts) AS rank,
                CASE
                    WHEN global_search_fts.entity_type = 'asset' AND lower(global_search_fts.metadata) = :query_lower THEN 0
                    WHEN global_search_fts.entity_type = 'asset' AND replace(replace(lower(global_search_fts.metadata), '-', ''), ' ', '') = :query_code THEN 0
                    WHEN global_search_fts.entity_type = 'asset' AND lower(global_search_fts.title) LIKE :title_prefix THEN 1
                    WHEN global_search_fts.entity_type = 'order' AND lower(global_search_fts.title) LIKE :title_prefix THEN 2
                    WHEN global_search_fts.entity_type = 'plan' THEN 4
                    WHEN global_search_fts.entity_type = 'checklist_item' THEN 5
                    WHEN global_search_fts.entity_type IN ('asset_file', 'legacy_document') THEN 6
                    ELSE 7
                END AS priority,
                -- asset fields
                a.status AS asset_status,
                a.is_operable AS asset_operable,
                a.patrimonio AS asset_patrimonio,
                CASE WHEN lower(global_search_fts.metadata) = :query_lower
                        OR replace(replace(lower(global_search_fts.metadata), '-', ''), ' ', '') = :query_code
                     THEN 1 ELSE 0 END AS is_exact_patrimonio_match,
                -- parent asset fields for documents
                parent_a.status AS parent_asset_status,
                parent_a.description AS parent_asset_name,
                parent_a.patrimonio AS parent_asset_patrimonio,
                -- file fields
                COALESCE(ad.original_name, adi.file_name) AS file_name,
                COALESCE(ad.category, adi.document_type) AS file_kind,
                COALESCE(ad.mime_type, CASE
                    WHEN lower(adi.file_extension) = '.pdf' THEN 'application/pdf'
                    WHEN lower(adi.file_extension) IN ('.jpg', '.jpeg') THEN 'image/jpeg'
                    WHEN lower(adi.file_extension) = '.png' THEN 'image/png'
                    ELSE NULL
                END) AS mime_type
            FROM global_search_fts
            LEFT JOIN assets AS a
                ON (global_search_fts.entity_type = 'asset' AND global_search_fts.entity_id = a.id)
                OR (global_search_fts.entity_type = 'order' AND global_search_fts.metadata = a.id)
            LEFT JOIN assets AS parent_a
                ON (global_search_fts.entity_type IN ('asset_file', 'legacy_document') AND global_search_fts.metadata = parent_a.id)
            LEFT JOIN asset_documents AS ad
                ON (global_search_fts.entity_type = 'asset_file' AND global_search_fts.entity_id = ad.id)
            LEFT JOIN asset_document_index AS adi
                ON (global_search_fts.entity_type = 'legacy_document' AND global_search_fts.entity_id = adi.id)
            WHERE global_search_fts MATCH :query {where_type}
            ORDER BY
                CASE WHEN global_search_fts.entity_type = 'asset'
                    AND (lower(global_search_fts.metadata) = :query_lower
                        OR replace(replace(lower(global_search_fts.metadata), '-', ''), ' ', '') = :query_code)
                    THEN 0 ELSE 1 END,
                CASE
                    WHEN COALESCE(a.status, parent_a.status) = 'active' THEN 0
                    WHEN COALESCE(a.status, parent_a.status) = 'inactive' THEN 1
                    ELSE 2
                END,
                priority, rank
            LIMIT :limit
        """)
        params: dict[str, Any] = {
            "query": fts_query,
            "query_lower": cleaned_query.lower(),
            "query_code": _code_key(cleaned_query),
            "title_prefix": f"{cleaned_query.lower()}%",
            "limit": max(1, min(limit, 100)),
        }
        if entity_type:
            params["entity_type"] = entity_type
        rows = (await db.execute(sql, params)).mappings().all()
        items = []
        for row in rows:
            item = {
                "entity_type": row["entity_type"],
                "entity_id": row["entity_id"],
                "title": row["title"],
                "snippet": row["snippet"],
                "metadata": row["metadata"],
                "rank": row["rank"],
                "priority": row["priority"],
                "is_exact_patrimonio_match": bool(row["is_exact_patrimonio_match"]),
            }
            if row["entity_type"] == "asset" and row["asset_status"]:
                item["asset_status"] = row["asset_status"]
                item["asset_operable"] = bool(row["asset_operable"])
                item["patrimonio"] = row["asset_patrimonio"]
            elif row["entity_type"] in ("asset_file", "legacy_document"):
                if row["parent_asset_status"]:
                    item["parent_asset_status"] = row["parent_asset_status"]
                    item["parent_asset_name"] = row["parent_asset_name"]
                    item["parent_asset_patrimonio"] = row["parent_asset_patrimonio"]
                if row["file_name"]:
                    item["file_name"] = row["file_name"]
                    item["file_kind"] = row["file_kind"]
                    item["mime_type"] = row["mime_type"]
            items.append(item)
        return {"query": cleaned_query, "backend": "sqlite_fts5", "fts_query": fts_query, "items": items, "total": len(items)}

    # Fallback portátil: assets + documentos linkados por LIKE.
    like = f"%{cleaned_query}%"
    items: list[dict[str, Any]] = []
    normalized_q = cleaned_query.lower().replace("-", "").replace(" ", "")
    if entity_type in {None, "asset"}:
        assets = (await db.execute(
            select(Asset).where(sa.or_(
                Asset.patrimonio.like(like),
                Asset.description.like(like),
                Asset.manufacturer.like(like),
                Asset.model.like(like),
                Asset.notes.like(like),
            )).limit(limit)
        )).scalars().all()
        # Sort: exact patrimonio match first, active before inactive
        def _asset_sort_key(a: Asset) -> tuple[int, int, str]:
            is_inactive = 1 if a.status == "inactive" else 0
            is_exact = 0 if (a.patrimonio.lower() == cleaned_query.lower()
                             or a.patrimonio.lower().replace("-", "").replace(" ", "") == normalized_q) else 1
            return (is_exact, is_inactive, a.patrimonio)
        assets = sorted(assets, key=_asset_sort_key)
        for a in assets:
            pat_lower = a.patrimonio.lower().replace("-", "").replace(" ", "") if a.patrimonio else ""
            items.append({
                "entity_type": "asset",
                "entity_id": a.id,
                "title": f"{a.patrimonio} · {a.description}",
                "snippet": a.notes,
                "metadata": a.patrimonio,
                "rank": 0,
                "priority": 0 if pat_lower == normalized_q else 2,
                "asset_status": a.status,
                "asset_operable": bool(a.is_operable),
                "patrimonio": a.patrimonio,
                "is_exact_patrimonio_match": pat_lower == normalized_q,
            })
    if entity_type in {None, "legacy_document"} and len(items) < limit:
        docs = (await db.execute(
            select(AssetDocumentIndex).where(sa.or_(
                AssetDocumentIndex.file_name.like(like),
                AssetDocumentIndex.document_type.like(like),
                AssetDocumentIndex.extracted_text.like(like),
                AssetDocumentIndex.notes.like(like),
            )).limit(limit - len(items))
        )).scalars().all()
        # Enrich with parent asset status
        for d in docs:
            parent_asset = None
            if d.asset_id:
                parent_res = await db.execute(select(Asset).where(Asset.id == d.asset_id))
                parent_asset = parent_res.scalars().first()
            item: dict[str, Any] = {
                "entity_type": "legacy_document",
                "entity_id": d.id,
                "title": d.file_name,
                "snippet": (d.extracted_text or d.notes or "")[:240],
                "metadata": d.asset_id,
                "rank": 0,
                "priority": 6,
                "is_exact_patrimonio_match": False,
            }
            if parent_asset:
                item["parent_asset_status"] = parent_asset.status
                item["parent_asset_name"] = parent_asset.description
                item["parent_asset_patrimonio"] = parent_asset.patrimonio
            items.append(item)
    return {"query": cleaned_query, "backend": "like_fallback", "items": items, "total": len(items)}

async def delete_search_document(db: AsyncSession, entity_type: str, entity_id: str) -> dict[str, Any]:
    enabled = await ensure_search_schema(db)
    if not enabled:
        return {"fts5": False, "deleted": 0}
    await db.execute(text("DELETE FROM global_search_fts WHERE entity_type=:entity_type AND entity_id=:entity_id"), {"entity_type": entity_type, "entity_id": entity_id})
    return {"fts5": True, "deleted": 1}

async def upsert_search_document(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: str,
    title: str,
    body: str = "",
    metadata: str | None = None,
    commit: bool = False,
) -> dict[str, Any]:
    """Atualiza um registro FTS sem rebuild completo.

    Útil para OCR/revisão documental/offline sync. Em falha, o chamador pode
    continuar e agendar rebuild manual sem afetar dados operacionais.
    """
    enabled = await ensure_search_schema(db)
    if not enabled:
        return {"fts5": False, "upserted": False}
    await db.execute(text("DELETE FROM global_search_fts WHERE entity_type=:entity_type AND entity_id=:entity_id"), {"entity_type": entity_type, "entity_id": entity_id})
    await db.execute(text("""
        INSERT INTO global_search_fts(entity_type, entity_id, title, body, metadata)
        VALUES (:entity_type, :entity_id, :title, :body, :metadata)
    """), {"entity_type": entity_type, "entity_id": entity_id, "title": title or "Sem título", "body": body or "", "metadata": metadata})
    if commit:
        await db.commit()
    return {"fts5": True, "upserted": True}
