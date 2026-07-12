"""스펙 303 검증 — 첫 설치 시드 예제 트림(최소 정예).

seed 카탈로그 상수를 직접 측정한다(DB 불필요·결정적). 두 축:
  C. 카운트 — 페르소나 2·컬렉션 3·세션 0·에이전트 5(트림 후 정예).
  R. 참조 무결 + 고아 0 — 시드 에이전트가 가리키는 persona/vectorTable 자산이 전부 존재하고,
     반대로 모든 페르소나·컬렉션이 ≥1 에이전트에 참조된다(고아 없음).

실행: uv run python tests/verify_303_seed_trim.py
전제: 없음(라이브 DB 불필요). import만 되면 동작.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from api import seed  # noqa: E402

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def main() -> None:
    persona_names = {p[0] for p in seed.PERSONAS}
    collection_names = {c[0] for c in seed.COLLECTIONS}

    # ── C. 카운트(트림 후 정예) ────────────────────────────────────────────
    check(len(seed.PERSONAS) == 2, f"C 페르소나 2 (현재 {len(seed.PERSONAS)}: {sorted(persona_names)})")
    check(len(seed.COLLECTIONS) == 3, f"C 컬렉션 3 (현재 {len(seed.COLLECTIONS)}: {sorted(collection_names)})")
    check(len(seed.SESSIONS) == 0, f"C 세션 0 (현재 {len(seed.SESSIONS)})")
    check(len(seed.APPROVALS) == 0, f"C 승인 0 (현재 {len(seed.APPROVALS)})")

    # 고아였던 항목이 실제로 사라졌는지 명시 단언(재발 방지).
    check("strict-senior-engineer" not in persona_names, "C strict-senior-engineer 제거됨")
    check("calm-sre" not in persona_names, "C calm-sre 제거됨")
    check("support-tickets" not in collection_names, "C support-tickets 제거됨")

    # ── R. 시드 에이전트가 참조하는 persona/vectorTable 수집 ──────────────────
    # ui 에이전트(AGENTS): (aid, name, desc, source, model, persona, mems, hist, vts, ...)
    ref_personas: set[str] = set()
    ref_vts: set[str] = set()
    for row in seed.AGENTS:
        ref_personas.add(row[5])   # persona 키
        ref_vts.update(row[8])     # vectorTables
    # plan-execute 데모(별도 시드 함수)는 persona="methodical-researcher"·vectorTables=[] 고정.
    ref_personas.add("methodical-researcher")

    # R1. 무결 — 참조 자산이 전부 카탈로그에 존재(dangling 0).
    dangling_p = ref_personas - persona_names
    dangling_v = ref_vts - collection_names
    check(not dangling_p, f"R1 persona dangling 0 (발견: {dangling_p})")
    check(not dangling_v, f"R1 vectorTable dangling 0 (발견: {dangling_v})")

    # R2. 고아 0 — 모든 페르소나·컬렉션이 ≥1 에이전트에 참조됨(정예: 걸리적거리는 미참조 없음).
    orphan_p = persona_names - ref_personas
    orphan_v = collection_names - ref_vts
    check(not orphan_p, f"R2 고아 페르소나 0 (발견: {orphan_p})")
    check(not orphan_v, f"R2 고아 컬렉션 0 (발견: {orphan_v})")

    print()
    if _fails:
        print(f"FAIL {len(_fails)}건:")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("PASS — 스펙 303 시드 트림 정합(카운트·참조무결·고아0).")


if __name__ == "__main__":
    main()
