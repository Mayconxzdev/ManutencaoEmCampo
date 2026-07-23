from __future__ import annotations

import json
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Request, Response

from app.config import APP_VERSION, LOGS_DIR

RECENT_REQUESTS: deque[dict[str, Any]] = deque(maxlen=500)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_path() -> Path:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return LOGS_DIR / "mec_requests.jsonl"


async def request_logging_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    start = time.perf_counter()
    status_code = 500
    error = None
    try:
        response: Response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as exc:
        error = str(exc)
        raise
    finally:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        record = {
            "ts": _now(),
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "query": str(request.url.query)[:500],
            "status_code": status_code,
            "elapsed_ms": elapsed_ms,
            "client_host": request.client.host if request.client else None,
            "app_version": APP_VERSION,
            "error": error,
        }
        RECENT_REQUESTS.appendleft(record)
        try:
            with _log_path().open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass


def recent_requests(limit: int = 100) -> list[dict[str, Any]]:
    return list(RECENT_REQUESTS)[: max(1, min(limit, 500))]
