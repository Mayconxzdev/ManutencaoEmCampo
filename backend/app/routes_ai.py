from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.clock import utcnow_naive
from app.database import get_db
from app.models import AssetDocumentIndex, SemanticDocumentChunk
from app.search_service import search_global

router = APIRouter(prefix="/v2/ai", tags=["ai-local"])

CHUNK_RE = re.compile(r"\s+")
TOKEN_RE = re.compile(r"[\wÀ-ÿ]{2,}", re.UNICODE)
EMBEDDING_MODEL = "mec-hash-embedding-v1"
EMBEDDING_DIMS = 384

class AskRequest(BaseModel):
    q: str
    limit: int = 8
    use_semantic: bool = False

async def _table_exists(db: AsyncSession, name: str) -> bool:
    try:
        return bool((await db.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"), {"name": name})).scalar())
    except Exception:
        return False

def _chunks(text_value: str, size: int = 1200, overlap: int = 160) -> list[str]:
    text_value = CHUNK_RE.sub(" ", text_value or "").strip()
    if not text_value:
        return []
    out: list[str] = []
    start = 0
    while start < len(text_value) and len(out) < 2000:
        piece = text_value[start:start + size].strip()
        if piece:
            out.append(piece)
        start += max(1, size - overlap)
    return out


def _clean(value: Any) -> str:
    return CHUNK_RE.sub(" ", str(value or "")).strip()


def _embedding(text_value: str, dims: int = EMBEDDING_DIMS) -> list[float]:
    """Deterministic local embedding.

    The official runtime can also carry LanceDB/Qdrant/sentence-transformers,
    but this fallback keeps the server useful offline and avoids downloading a
    model during production use. It is a hashed sparse vector normalized for
    cosine ranking; the model name is stored in the DB for auditability.
    """
    values = [0.0] * dims
    tokens = [token.lower() for token in TOKEN_RE.findall(text_value or "")]
    if not tokens:
        return values
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % dims
        sign = 1.0 if digest[4] & 1 else -1.0
        values[bucket] += sign
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return [round(value / norm, 6) for value in values]


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    size = min(len(left), len(right))
    return float(sum(left[idx] * right[idx] for idx in range(size)))


def _code_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _literal_boost(query: str, text_value: str) -> float:
    query_terms = [token.lower() for token in TOKEN_RE.findall(query or "")]
    if not query_terms:
        return 0.0
    lowered = (text_value or "").lower()
    matched = sum(1 for term in query_terms if term in lowered)
    boost = 0.45 * (matched / len(query_terms))
    query_code = _code_key(query)
    if query_code and len(query_code) >= 2 and query_code in _code_key(text_value):
        boost += 0.65
    return boost


async def _document_sources(db: AsyncSession, limit: int) -> list[dict[str, Any]]:
    rows = (await db.execute(text("""
        SELECT
            idx.id,
            idx.file_name,
            idx.file_path,
            idx.document_type,
            idx.confidence,
            idx.extracted_text,
            idx.extraction_method,
            idx.notes,
            idx.asset_id,
            assets.patrimonio,
            assets.description AS asset_description,
            assets.type AS asset_type,
            sectors.name AS sector_name
          FROM asset_document_index idx
          LEFT JOIN assets ON assets.id = idx.asset_id
          LEFT JOIN sectors ON sectors.id = assets.sector_id
         ORDER BY idx.indexed_at DESC, idx.file_name ASC
         LIMIT :limit
    """), {"limit": max(1, min(limit, 10000))})).mappings().all()
    return [dict(row) for row in rows]


def _source_text(row: dict[str, Any]) -> str:
    extracted = _clean(row.get("extracted_text"))
    metadata = " | ".join(part for part in [
        f"Arquivo: {_clean(row.get('file_name'))}",
        f"Tipo: {_clean(row.get('document_type'))}",
        f"Ativo: {_clean(row.get('patrimonio'))}",
        f"Descrição do ativo: {_clean(row.get('asset_description'))}",
        f"Setor: {_clean(row.get('sector_name'))}",
        f"Confiança: {_clean(row.get('confidence'))}",
        f"Caminho: {_clean(row.get('file_path'))}",
        f"Notas: {_clean(row.get('notes'))}",
    ] if part and not part.endswith(": "))
    if extracted:
        return f"{metadata}\nTexto extraído: {extracted}"
    return metadata


def _citation(row: dict[str, Any], score: float | None = None) -> dict[str, Any]:
    snippet = _clean(row.get("text"))[:900]
    citation = {
        "source_kind": row.get("source_kind"),
        "source_id": row.get("source_id"),
        "chunk_index": row.get("chunk_index"),
        "title": row.get("title"),
        "snippet": snippet,
        "page": None,
        "score": round(float(score or 0.0), 6),
    }
    return citation


@router.post("/reindex-chunks")
async def reindex_chunks(limit: int = 2000, db: AsyncSession = Depends(get_db)):
    if not await _table_exists(db, "semantic_document_chunks"):
        return {"enabled": False, "schema_missing": True}
    await db.execute(text("DELETE FROM semantic_document_chunks"))
    rows = await _document_sources(db, limit)
    total = 0
    for doc in rows:
        source_text = _source_text(doc)
        for idx, chunk in enumerate(_chunks(source_text)):
            db.add(SemanticDocumentChunk(
                id=str(uuid.uuid4()),
                source_kind="asset_document_index",
                source_id=doc["id"],
                chunk_index=idx,
                title=doc.get("file_name"),
                text=chunk,
                text_hash=hashlib.sha256(chunk.encode("utf-8")).hexdigest(),
                embedding_model=EMBEDDING_MODEL,
                vector_json=json.dumps(_embedding(chunk), separators=(",", ":")),
                created_at=utcnow_naive(),
            ))
            total += 1
    await db.commit()
    return {
        "enabled": True,
        "documents": len(rows),
        "chunks": total,
        "mode": "local_vector_chunks",
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dimensions": EMBEDDING_DIMS,
        "vector_store": "sqlite:semantic_document_chunks",
    }


@router.get("/status")
async def ai_status(db: AsyncSession = Depends(get_db)):
    if not await _table_exists(db, "semantic_document_chunks"):
        return {"enabled": False, "schema_missing": True}
    row = (await db.execute(text("""
        SELECT
            count(*) AS chunks,
            count(DISTINCT source_id) AS documents,
            sum(CASE WHEN vector_json IS NULL OR vector_json = '' THEN 0 ELSE 1 END) AS vectors,
            max(created_at) AS last_indexed_at
          FROM semantic_document_chunks
    """))).mappings().first()
    return {
        "enabled": True,
        "vector_store": "sqlite:semantic_document_chunks",
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dimensions": EMBEDDING_DIMS,
        "chunks": int(row["chunks"] or 0),
        "documents": int(row["documents"] or 0),
        "vectors": int(row["vectors"] or 0),
        "last_indexed_at": row["last_indexed_at"],
    }

@router.post("/ask")
async def ask_local(req: AskRequest, db: AsyncSession = Depends(get_db)):
    """Resposta preparada para RAG local sem inventar conteúdo.

    Enquanto embeddings/modelo local não forem configurados, retorna trechos e
    fontes por FTS5/chunks para o Codex ou operador interpretar.
    """
    fts = await search_global(db, req.q, limit=req.limit)
    chunk_hits: list[dict[str, Any]] = []
    if await _table_exists(db, "semantic_document_chunks"):
        query_vector = _embedding(req.q)
        vector_rows = (await db.execute(text("""
            SELECT source_kind, source_id, chunk_index, title, text, vector_json, embedding_model
              FROM semantic_document_chunks
             WHERE vector_json IS NOT NULL AND vector_json != ''
             LIMIT 10000
        """))).mappings().all()
        scored: list[tuple[float, dict[str, Any]]] = []
        for row in vector_rows:
            try:
                vector = json.loads(row["vector_json"])
            except Exception:
                continue
            row_dict = dict(row)
            score = _cosine(query_vector, vector) + _literal_boost(req.q, row_dict.get("text") or "")
            scored.append((score, row_dict))
        scored.sort(key=lambda item: item[0], reverse=True)
        chunk_hits = [_citation(row, score) for score, row in scored[: max(1, min(req.limit, 30))] if score > 0]

        terms = [t.lower() for t in TOKEN_RE.findall(req.q or "")[:8]]
        if terms:
            where = " OR ".join(["lower(text) LIKE :t%d" % i for i in range(len(terms))])
            params = {f"t{i}": f"%{term}%" for i, term in enumerate(terms)}
            rows = (await db.execute(text(f"""
                SELECT source_kind, source_id, chunk_index, title, text
                  FROM semantic_document_chunks
                 WHERE {where}
                 LIMIT :limit
            """), {**params, "limit": max(1, min(req.limit, 30))})).mappings().all()
            seen = {(hit["source_id"], hit["chunk_index"]) for hit in chunk_hits}
            for row in rows:
                key = (row["source_id"], row["chunk_index"])
                if key not in seen:
                    chunk_hits.append(_citation(dict(row), 0.0))
                    seen.add(key)
    return {
        "query": req.q,
        "answer_mode": "retrieval_only",
        "message": "Resposta limitada a fontes: nenhum conteúdo é afirmado sem citação documental. Configure um LLM local se quiser síntese automática.",
        "embedding_model": EMBEDDING_MODEL,
        "vector_store": "sqlite:semantic_document_chunks",
        "fts_results": fts.get("items", []),
        "citations": chunk_hits[: max(1, min(req.limit, 30))],
    }
