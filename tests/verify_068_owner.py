"""스펙 068 검증(단위 시맨틱) — chat 세션 소유권 무덮어쓰기 불변식 (인프라 불요).

`_next_owner(current, incoming)`가 소유권을 *생성 시 1회*만 부여하고, 기존 non-null 소유자를
*다른* 유저로 덮어쓰지 않는지(이전 거부) 격리 검증한다. 이게 D1(resume 소유자 스코프)과 함께
chat resume의 소유권 탈취를 봉인하는 두 번째 방어선이다(learning 069). 실 DB/HTTP는
verify_068_live.py(통합 rung)에서 별도 확인.

검증:
  N1. 미소유(None)에 유저 → 부여(생성 시 1회)
  N2. 기존 소유자 == incoming → 동일 유저 유지(멱등)
  N3. 기존 소유자 != incoming → current 유지(★ 이전 거부 = 탈취 봉인)
  N4. incoming 빈 값(None/"") → current 보존(빈칸 대화가 소유자 안 지움 — 무회귀)
  N5. 미소유 + 빈 incoming → None 유지(머신/익명 세션은 NULL 유지)

실행: .venv/bin/python tests/verify_068_owner.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from api.chat import _next_owner  # noqa: E402

_fails: list[str] = []

A = "11111111-1111-1111-1111-111111111111"
B = "22222222-2222-2222-2222-222222222222"


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# ---- N1. 미소유 → 부여(생성 시 1회) ----
check(_next_owner(None, A) == A, "N1: 미소유(None) + 유저 A → A 부여(생성 시 1회)")

# ---- N2. 동일 유저 멱등 ----
check(_next_owner(A, A) == A, "N2: 기존 A + incoming A → A 유지(멱등)")

# ---- N3. 이전 거부(★ 탈취 봉인) ----
check(_next_owner(A, B) == A, "N3(★): 기존 A + 다른 유저 B → A 유지(이전 거부 = 소유권 탈취 봉인)")
check(_next_owner(A, B) != B, "N3(★): 기존 소유자가 attacker(B)로 절대 안 바뀜")

# ---- N4. 빈 incoming 보존(무회귀) ----
check(_next_owner(A, None) == A, "N4: 기존 A + incoming None(머신) → A 보존(빈칸 무삭제)")
check(_next_owner(A, "") == A, "N4: 기존 A + incoming '' → A 보존")

# ---- N5. 미소유 + 빈 incoming → None 유지 ----
check(_next_owner(None, None) is None, "N5: 미소유 + None → None 유지(머신/익명 세션 NULL 유지)")
check(_next_owner(None, "") is None, "N5: 미소유 + '' → None 유지")

print()
if _fails:
    print(f"FAILED ({len(_fails)})")
    for m in _fails:
        print("  - " + m)
    sys.exit(1)
print("ALL PASS — 스펙 068 소유권 무덮어쓰기 불변식 전부 통과")
