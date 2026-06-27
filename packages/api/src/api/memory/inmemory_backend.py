"""인메모리 레퍼런스 백엔드 — `MemoryBackend`의 mem0-무의존 구현. 스펙 040 (P4).

존재 이유는 **drop-in 실측 증명**이다: mem0 코드를 한 줄도 공유하지 않는 백엔드가 같은 계약
(`tests/verify_040_memory_backend_contract.py`)을 통과하면, 추상화가 진짜 백엔드-중립임이 *측정*된다.
프로세스 메모리 dict 저장이라 영속·확장은 없다 — 프로덕션 백엔드가 아니라 계약 레퍼런스다.

mem0 어댑터가 "필터 AND 우회"로 축별 검색·병합하는 것과 달리, 여기서는 **합집합을 네이티브로**
계산한다(한 기억이 여러 축에 태깅되면 어느 축 질의로도 잡히고 id로 dedup). 같은 관측 계약을 다른
메커니즘으로 만족시키는 것이 요점이다.
"""

from .backend import scope_axes


class InMemoryBackend:
    """dict 저장 레퍼런스 백엔드. mem_cfg는 계약상 받지만 라우팅에 쓰지 않는다(LLM 추출 없음)."""

    def __init__(self, mem_cfg: dict | None = None):
        # 각 기억: {"id", "text", "axes": {axis: val, ...}}. axes는 add 시 태깅된 스코프 축.
        self._store: list[dict] = []
        self._seq = 0

    def _next_id(self) -> str:
        self._seq += 1
        return f"mem-{self._seq}"

    def add(self, scope: dict, messages: list[dict], infer: bool) -> None:
        axes = dict(scope_axes(scope))
        if not messages or not axes:
            return
        # infer는 계약상 받되 LLM이 없으므로 원문 그대로 저장(verbatim) — mem0의 추출은 어댑터 고유.
        for m in messages:
            text = (m.get("content") or "").strip()
            if not text:
                continue
            self._store.append({"id": self._next_id(), "text": text, "axes": dict(axes)})

    def _matches(self, rec: dict, axis: str, val: str) -> bool:
        return rec["axes"].get(axis) == val

    def search(self, scope: dict, query: str, limit: int) -> list[dict]:
        axes = scope_axes(scope)
        if not query or not axes:
            return []
        q = query.lower()
        merged: dict[str, dict] = {}
        # 축 우선순위 순으로 — 같은 기억이 여러 축에 잡히면 더 높은 score를 남긴다(id dedup).
        for axis, val in axes:
            for rec in self._store:
                if not self._matches(rec, axis, val) or q not in rec["text"].lower():
                    continue
                # 짧은(=질의 비중 큰) 본문일수록 높은 score — 결정적이고 (0,1] 범위.
                score = round(min(1.0, len(query) / max(1, len(rec["text"]))), 3)
                prev = merged.get(rec["id"])
                if prev is None or score > prev["score"]:
                    merged[rec["id"]] = {"type": "semantic", "text": rec["text"], "score": score, "scope": axis}
        hits = sorted(merged.values(), key=lambda h: h["score"], reverse=True)
        return hits[:limit]

    def list_all(self, scope: dict) -> list[dict]:
        axes = scope_axes(scope)
        if not axes:
            return []
        merged: dict[str, dict] = {}
        for axis, val in axes:
            for rec in self._store:
                if self._matches(rec, axis, val):
                    merged[rec["id"]] = {"id": rec["id"], "text": rec["text"]}
        return list(merged.values())

    def update(self, mem_id: str, text: str) -> bool:
        if not mem_id:
            return False
        for rec in self._store:
            if rec["id"] == mem_id:
                rec["text"] = text
                return True
        return False

    def delete(self, mem_id: str) -> bool:
        if not mem_id:
            return False
        before = len(self._store)
        self._store = [r for r in self._store if r["id"] != mem_id]
        return len(self._store) < before
