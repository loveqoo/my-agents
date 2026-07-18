"""스펙 171 검증 — 승인 재개 impl-drift 명시 가드의 판정 경계.

`_impl_drifted(snap, cur)`(chat.py 순수 함수)가 위상 정체 대조를 정확히 하는지 단위 검증한다.
가드가 True면 resume_approval이 조기 return(미정의 동작에 resume 안 함, approved-but-not-executed).

핵심 경계:
- snap None(마이그레이션 이전 행) = 대조 불가 → 스킵(False, 하위호환).
- ""(기본 DefaultUiAgent)와 None/""는 같은 위상 → False.
- 스냅샷이 있고 현재와 다르면(HIL→non-HIL이든 HIL→다른 HIL이든) → True(거부).

실행: cd packages/api && uv run python ../../tests/verify_171_impl_drift_guard.py
"""

import sys

from api.chat import _impl_drifted

_fails = []


def check(c, m):
    print(("  ok  " if c else " FAIL ") + m)
    if not c:
        _fails.append(m)


# (snap, cur, 기대 drift?, 설명)
CASES = [
    (None, "orchestrate", False, "snap None(이전 행) → 대조 스킵(하위호환)"),
    (None, None, False, "snap None + cur None → 스킵"),
    ("", "", False, "기본 == 기본 → drift 아님"),
    ("", None, False, "기본('') vs cur None → 둘 다 기본 → drift 아님"),
    ("", "orchestrate", True, "기본 → orchestrate 교체 → drift(핵심: 재개 거부)"),
    ("orchestrate", "", True, "orchestrate → 기본 교체 → drift"),
    ("orchestrate", None, True, "orchestrate → cur None(기본) → drift"),
    ("orchestrate", "orchestrate", False, "동일 impl → drift 아님(정상 재개)"),
    (
        "orchestrate",
        "orchestrate_ranked",
        True,
        "HIL→다른 HIL 교체 → drift(현 가드가 새로 잡는 케이스)",
    ),
    ("plan_execute", "route", True, "커스텀→다른 커스텀 → drift"),
]

for snap, cur, expected, desc in CASES:
    got = _impl_drifted(snap, cur)
    check(got == expected, f"_impl_drifted({snap!r}, {cur!r}) == {expected} — {desc} (got {got})")


if __name__ == "__main__":
    print()
    if _fails:
        print(f"❌ {len(_fails)} FAILED")
        for f in _fails:
            print("   - " + f)
        sys.exit(1)
    print("✅ ALL PASS (VERIFY171_OK)")
