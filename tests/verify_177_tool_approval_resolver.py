"""verify_177 — 도구 승인 정책 리졸버 단위 매트릭스(스펙 177 P1).

`runtime.resolve_tool_approval(server, tool, tools_meta)`가 단일 진실원임을 핀:
  R1 tools_meta.approval.required=true → "mcp.{server}.{tool}"(관리자 데이터 설정).
  R2 tools_meta 있으나 approval 없음 → 레거시 폴백(delete_record→data.delete, 그 외→None).
  R3 tools_meta 없음(None/{}) → 레거시 폴백.
  R4 approval.required=false/누락 → 레거시 폴백(승인 안 걸림 확인).
  R5 임의 신규 도구를 tools_meta로 켜면 → permission 생성(하드코딩 없이도 게이트).
실행: cd packages/api && uv run python ../../tests/verify_177_tool_approval_resolver.py
"""
from api.blocks import _tools_meta_from_details
from api.runtime import resolve_tool_approval

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def main() -> None:
    # R1 — tools_meta로 승인 켠 도구.
    tm = {"delete_record": {"approval": {"required": True}}}
    check(resolve_tool_approval("local-tools", "delete_record", tm) == "mcp.local-tools.delete_record",
          "R1 tools_meta.required=true → mcp.local-tools.delete_record")

    # R2 — tools_meta 있으나 approval 없음 → 레거시 폴백.
    tm_noappr = {"delete_record": {"description": "x", "params": []}}
    check(resolve_tool_approval("local-tools", "delete_record", tm_noappr) == "data.delete",
          "R2 approval 없음 → 레거시 data.delete")
    check(resolve_tool_approval("local-tools", "web_search", tm_noappr) is None,
          "R2 비위험 도구(레거시 없음) → None")

    # R3 — tools_meta 없음 → 레거시 폴백.
    check(resolve_tool_approval("local-tools", "delete_record", None) == "data.delete",
          "R3 tools_meta=None → 레거시 data.delete")
    check(resolve_tool_approval("local-tools", "delete_record", {}) == "data.delete",
          "R3 tools_meta={} → 레거시 data.delete")

    # R4 — required=false/누락 → 레거시 폴백(안 걸림).
    check(resolve_tool_approval("srv", "t", {"t": {"approval": {"required": False}}}) is None,
          "R4 required=false + 레거시 없음 → None")

    # R5 — 임의 신규 도구를 tools_meta로 켜면 하드코딩 없이 게이트.
    check(resolve_tool_approval("acme", "wire_money", {"wire_money": {"approval": {"required": True}}})
          == "mcp.acme.wire_money",
          "R5 신규 도구 tools_meta로 승인 켜짐(하드코딩 불요)")
    check(resolve_tool_approval("acme", "wire_money", None) is None,
          "R5 대조: 설정 없으면 승인 안 걸림")

    # R6 — reconcile 왕복(적대 검토 P0): 재탐색이 admin approval을 파괴하지 않아야 한다.
    # 라이브 탐색 결과(toolsDetail)엔 approval이 없으므로 기존 tools_meta에서 이월 보존해야 함.
    prior = {"web_search": {"description": "old", "params": [], "approval": {"required": True}}}
    details = [{"name": "web_search", "description": "새 설명", "params": [{"name": "query"}]}]
    merged = _tools_meta_from_details(details, prior)
    check(merged["web_search"].get("approval") == {"required": True},
          "R6 재탐색이 admin approval 이월 보존(게이트 안 지워짐)")
    check(merged["web_search"]["description"] == "새 설명",
          "R6 설명/파라미터는 탐색 결과로 갱신")
    check(resolve_tool_approval("srv", "web_search", merged) == "mcp.srv.web_search",
          "R6 재탐색 후에도 리졸버가 여전히 게이트 생성")
    # 도구가 탐색에서 사라지면 그 approval도 사라짐(정상 — 도구 자체가 없음).
    gone = _tools_meta_from_details([{"name": "echo", "description": "", "params": []}], prior)
    check("web_search" not in gone, "R6 사라진 도구는 approval도 소멸(정상)")
    # prior 없으면(신규 등록) approval 없음.
    check((_tools_meta_from_details(details).get("web_search") or {}).get("approval") is None,
          "R6 prior 없는 신규 탐색 → approval 없음")

    print("\nPASS — 0 failed" if not _fails else f"\nFAIL — {len(_fails)} failed")
    raise SystemExit(1 if _fails else 0)


if __name__ == "__main__":
    main()
