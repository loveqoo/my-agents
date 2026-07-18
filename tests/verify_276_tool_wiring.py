"""직접형 도구 단위 배선 단위 검증 (스펙 276).

selected_for_server(서버별 노출 필터) 시맨틱 + AgentConfig.tools 라운드트립 보존.
실행: uv run --project packages/api python tests/verify_276_tool_wiring.py
"""

from api.runtime import selected_for_server
from api.schemas import AgentConfig

fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        fails.append(msg)


# ① 구저장(tools 미지정/빈 목록) → 전체 노출(무회귀의 핵심)
check(selected_for_server("calc-tools", None) is None, "None → 전체 노출")
check(selected_for_server("calc-tools", []) is None, "빈 목록 → 전체 노출")

# ② 이 서버 항목 있으면 그것만
check(
    selected_for_server("calc-tools", ["calc-tools__add", "calc-tools__echo"])
    == {"calc-tools__add", "calc-tools__echo"},
    "항목 있음 → 그 도구만",
)

# ③ 타 서버 항목은 이 서버를 제한하지 않음(오버라이드 서버 추가·카탈로그 미열거 폴백)
check(
    selected_for_server("web-fetch", ["calc-tools__add"]) is None,
    "타 서버 항목 → 이 서버 전체 폴백",
)

# ④ 혼합 선택은 서버별로 분할
sel = ["calc-tools__add", "web-fetch__wiki_search"]
check(selected_for_server("calc-tools", sel) == {"calc-tools__add"}, "혼합 — calc-tools는 add만")
check(
    selected_for_server("web-fetch", sel) == {"web-fetch__wiki_search"},
    "혼합 — web-fetch는 wiki_search만",
)

# ⑤ 대시 서버명 접두 혼동 없음(NAME_RULE 밑줄 금지 — 272 불변식 공유)
check(
    selected_for_server("calc", ["calc-tools__add"]) is None,
    "'calc'는 'calc-tools__' 접두에 안 걸림",
)

# ⑥ 비-문자열 원소 무시(fail-safe)
check(
    selected_for_server("calc-tools", [None, 3, "calc-tools__add"]) == {"calc-tools__add"},  # type: ignore[list-item]
    "비-문자열 원소 무시",
)

# ⑦ AgentConfig.tools 라운드트립 보존(learning 101 — model_dump 드롭 방지)
dumped = AgentConfig(tools=["calc-tools__add"], mcps=["calc-tools"]).model_dump()
check(
    dumped["tools"] == ["calc-tools__add"] and dumped["mcps"] == ["calc-tools"],
    "AgentConfig 왕복 보존",
)
check(AgentConfig().model_dump()["tools"] == [], "미지정 기본=빈 목록(전체 폴백)")

print()
print(f"{len(fails)} FAIL" if fails else "ALL PASS")
raise SystemExit(1 if fails else 0)
