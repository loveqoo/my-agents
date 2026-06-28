"""models.dev 카탈로그 (스펙 047 #7).

번들 스냅샷 `data/models_dev.json`(외부 런타임 의존 없음 — 박제)을 1회 로드해, GET /models가
돌려준 raw 모델 id를 카탈로그와 매칭하여 메타(context·modalities·cost·capabilities)를 채운다.
매칭은 best-effort: full id(`openai/gpt-4o`)·bare id(`gpt-4o`) 양쪽 색인. 미수록이면 None
(MLX 로컬·사설 모델은 대개 미수록 — 정상).

스냅샷 갱신은 런타임이 아니라 수동: `tests/refresh_models_dev.py`.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

_DATA = os.path.join(os.path.dirname(__file__), "data", "models_dev.json")


def _to_meta(entry: dict[str, Any]) -> dict[str, Any]:
    """models.dev 엔트리 → ModelConfig.meta 정규화 형태."""
    limit = entry.get("limit") or {}
    cost = entry.get("cost") or {}
    modalities = entry.get("modalities") or {}
    return {
        "catalog_id": entry.get("id"),
        "name": entry.get("name"),
        "context": limit.get("context"),
        "output_limit": limit.get("output"),
        "modalities": {
            "input": modalities.get("input") or [],
            "output": modalities.get("output") or [],
        },
        "cost": {"input": cost.get("input"), "output": cost.get("output")},
        "capabilities": {
            "reasoning": bool(entry.get("reasoning")),
            "tool_call": bool(entry.get("tool_call")),
            "structured_output": bool(entry.get("structured_output")),
            "attachment": bool(entry.get("attachment")),
        },
        "release_date": entry.get("release_date"),
    }


@lru_cache(maxsize=1)
def _index() -> tuple[dict[str, dict], dict[str, dict]]:
    """(by_full, by_bare) 색인을 1회 빌드. 파일 없으면 빈 색인(graceful)."""
    by_full: dict[str, dict] = {}
    by_bare: dict[str, dict] = {}
    try:
        with open(_DATA, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return by_full, by_bare
    for provider in raw.values():
        for full_id, entry in (provider.get("models") or {}).items():
            meta = _to_meta(entry)
            by_full[full_id] = meta
            bare = full_id.split("/")[-1]
            by_bare.setdefault(bare, meta)  # 충돌 시 first-wins(best-effort)
    return by_full, by_bare


def lookup(model_id: str | None) -> dict[str, Any] | None:
    """raw 모델 id를 카탈로그와 매칭해 메타 반환. 미수록이면 None.

    우선순위: full id 완전일치 → bare id(마지막 세그먼트) 일치.
    """
    if not model_id:
        return None
    by_full, by_bare = _index()
    if model_id in by_full:
        return by_full[model_id]
    bare = model_id.split("/")[-1]
    return by_bare.get(bare)


def stats() -> dict[str, int]:
    """진단용 — 색인 크기."""
    by_full, by_bare = _index()
    return {"full_ids": len(by_full), "bare_ids": len(by_bare)}
