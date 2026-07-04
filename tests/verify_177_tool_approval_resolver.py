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


def perm(server, tool, tm=None, tp=None):
    r = resolve_tool_approval(server, tool, tm, tp)
    return r["permission"] if r else None


def appr(server, tool, tm=None, tp=None):
    r = resolve_tool_approval(server, tool, tm, tp)
    return r["approver"] if r else None


def main() -> None:
    # R1 — tools_meta로 승인 켠 도구(반환은 {permission, approver}).
    tm = {"delete_record": {"approval": {"required": True}}}
    check(perm("local-tools", "delete_record", tm) == "mcp.local-tools.delete_record",
          "R1 tools_meta.required=true → mcp.local-tools.delete_record")
    check(appr("local-tools", "delete_record", tm) == "admin", "R1 approver 기본 admin")

    # R2 — tools_meta 있으나 approval 없음 → 레거시 폴백.
    tm_noappr = {"delete_record": {"description": "x", "params": []}}
    check(perm("local-tools", "delete_record", tm_noappr) == "data.delete",
          "R2 approval 없음 → 레거시 data.delete")
    check(perm("local-tools", "web_search", tm_noappr) is None, "R2 비위험 도구(레거시 없음) → None")

    # R3 — tools_meta 없음 → 레거시 폴백.
    check(perm("local-tools", "delete_record", None) == "data.delete", "R3 tools_meta=None → 레거시")
    check(perm("local-tools", "delete_record", {}) == "data.delete", "R3 tools_meta={} → 레거시")

    # R4 — required=false/누락 → 레거시 폴백(안 걸림).
    check(perm("srv", "t", {"t": {"approval": {"required": False}}}) is None,
          "R4 required=false + 레거시 없음 → None")

    # R5 — 임의 신규 도구를 tools_meta로 켜면 하드코딩 없이 게이트.
    check(perm("acme", "wire_money", {"wire_money": {"approval": {"required": True}}})
          == "mcp.acme.wire_money", "R5 신규 도구 tools_meta로 승인 켜짐(하드코딩 불요)")
    check(perm("acme", "wire_money", None) is None, "R5 대조: 설정 없으면 승인 안 걸림")

    # ---- P2: approver + 에이전트 오버라이드 ----
    # R7 approver — 도구 기본이 self면 self.
    tm_self = {"t": {"approval": {"required": True, "approver": "self"}}}
    check(appr("srv", "t", tm_self) == "self", "R7 도구 기본 approver=self 반영")
    # R8 강화 — 도구 기본 없음, 오버라이드로 켜기.
    tp_on = {"mcp:srv/t": {"approval": {"required": True}}}
    check(perm("srv", "t", None, tp_on) == "mcp.srv.t", "R8 오버라이드 강화(끔→켬)")
    # R8 완화 — 도구 기본 required=true, 오버라이드로 끄기.
    tp_off = {"mcp:srv/t": {"approval": {"required": False}}}
    check(perm("srv", "t", {"t": {"approval": {"required": True}}}, tp_off) is None,
          "R8 오버라이드 완화(켬→끔)")
    # R8 approver 오버라이드 — 기본 admin, 오버라이드로 self.
    tp_self = {"mcp:srv/t": {"approval": {"approver": "self"}}}
    check(appr("srv", "t", {"t": {"approval": {"required": True}}}, tp_self) == "self",
          "R8 오버라이드 approver admin→self")
    # R8 레거시 위 오버라이드 — delete_record(레거시 required) 완화.
    check(perm("local-tools", "delete_record", None,
               {"mcp:local-tools/delete_record": {"approval": {"required": False}}}) is None,
          "R8 레거시 게이트도 오버라이드로 완화 가능")
    # R8 approver 오염 방어 — 이상값은 admin으로 fail-closed.
    check(appr("srv", "t", {"t": {"approval": {"required": True, "approver": "everyone"}}}) == "admin",
          "R8 approver 이상값 → admin fail-closed")

    # R6 — reconcile 왕복(적대 검토 P0): 재탐색이 admin approval을 파괴하지 않아야 한다.
    # 라이브 탐색 결과(toolsDetail)엔 approval이 없으므로 기존 tools_meta에서 이월 보존해야 함.
    prior = {"web_search": {"description": "old", "params": [], "approval": {"required": True}}}
    details = [{"name": "web_search", "description": "새 설명", "params": [{"name": "query"}]}]
    merged = _tools_meta_from_details(details, prior)
    check(merged["web_search"].get("approval") == {"required": True},
          "R6 재탐색이 admin approval 이월 보존(게이트 안 지워짐)")
    check(merged["web_search"]["description"] == "새 설명",
          "R6 설명/파라미터는 탐색 결과로 갱신")
    check(perm("srv", "web_search", merged) == "mcp.srv.web_search",
          "R6 재탐색 후에도 리졸버가 여전히 게이트 생성")
    # 도구가 탐색에서 사라지면 그 approval도 사라짐(정상 — 도구 자체가 없음).
    gone = _tools_meta_from_details([{"name": "echo", "description": "", "params": []}], prior)
    check("web_search" not in gone, "R6 사라진 도구는 approval도 소멸(정상)")
    # prior 없으면(신규 등록) approval 없음.
    check((_tools_meta_from_details(details).get("web_search") or {}).get("approval") is None,
          "R6 prior 없는 신규 탐색 → approval 없음")


class _P:  # principal 스텁 — is_privileged(superuser 단락)만 씀
    def __init__(self, is_superuser: bool):
        import uuid
        self.id = uuid.uuid4()
        self.is_superuser = is_superuser


def gate_tests() -> None:
    """완화 게이트 RBAC(스펙 177 P2 D4) — **값 기반**(현재 기본 무관, TOCTOU-free). DB 불요.
    G: 완화 의도(required:false·approver:self)는 admin만·강화는 자유·self-lock(admin 통과)·TOCTOU 방어."""
    from fastapi import HTTPException

    from api.agents import _enforce_tool_policy_gate

    nonadmin, admin = _P(False), _P(True)

    def gate(cfg, principal):
        try:
            _enforce_tool_policy_gate(cfg, principal)
            return None
        except HTTPException as e:
            return e.status_code

    relax = {"toolPolicy": {"mcp:local-tools/delete_record": {"approval": {"required": False}}}}
    check(gate(relax, nonadmin) == 403, "G1 완화(required 끄기) + 비-admin → 403")
    check(gate(relax, admin) is None, "G2 완화 + admin(superuser) → 허용(self-lock: 정당 admin 통과)")

    strengthen = {"toolPolicy": {"mcp:local-tools/web_search": {"approval": {"required": True}}}}
    check(gate(strengthen, nonadmin) is None, "G3 강화(승인 추가) + 비-admin → 허용(강화는 자유)")

    apr_relax = {"toolPolicy": {"mcp:local-tools/delete_record": {"approval": {"approver": "self"}}}}
    check(gate(apr_relax, nonadmin) == 403, "G4 approver admin→self 약화 + 비-admin → 403")

    check(gate({"toolPolicy": {}}, nonadmin) is None, "G5 toolPolicy 없음 → 게이트 무영향")

    # G6 — TOCTOU 방어(적대 검토 M): 아직 승인 없는 임의 도구에 required:false를 심어도 값 기반이라
    # 비-admin은 저장 자체가 403. 비교 기반이었다면 "현재 no-op"이라 통과됐다가 나중 admin 강화 시 우회.
    toctou = {"toolPolicy": {"mcp:acme/未gated_tool": {"approval": {"required": False}}}}
    check(gate(toctou, nonadmin) == 403, "G6 TOCTOU: 비-게이트 도구에 required:false도 비-admin 403(값 기반)")
    check(gate({"toolPolicy": {"mcp:acme/t": {"approval": {"required": True}}}}, nonadmin) is None,
          "G6 대조: 강화는 어떤 도구든 비-admin 허용")


if __name__ == "__main__":
    main()
    gate_tests()
    print("\nPASS — 0 failed" if not _fails else f"\nFAIL — {len(_fails)} failed")
    raise SystemExit(1 if _fails else 0)
