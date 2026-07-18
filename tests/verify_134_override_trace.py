"""verify_134 — 턴 트레이스 오버라이드 기록 (_overrides_trace).

  V1 허용 키만 통과(모르는 키 드롭), 실제 온 것만.
  V2 systemPrompt 비밀 마스킹 + 캡 300.
  V3 리스트 항목 캡 100·개수 20.
  V4 빈/None/비-dict → None(트레이스 필드 미기록=무회귀).
실행: uv run --project packages/api python tests/verify_134_override_trace.py
"""

import os
import sys

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"
    ),
)
from api.chat import _overrides_trace  # noqa: E402

_fails = []
passed = 0


def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


t = _overrides_trace({"model": "m1", "temperature": 0.9, "이상한키": "x", "historyDepth": 5})
check(t == {"model": "m1", "temperature": 0.9, "historyDepth": 5}, f"V1 허용 키만 (got {t})")

t2 = _overrides_trace({"systemPrompt": "프롬프트 api_key: sk-LEAK-777777 " + "가" * 500})
check(
    t2 is not None
    and "sk-LEAK-777777" not in t2["systemPrompt"]
    and "«secret»" in t2["systemPrompt"],
    "V2a systemPrompt 비밀 마스킹",
)
check(len(t2["systemPrompt"]) <= 301, f"V2b 캡 300 (got {len(t2['systemPrompt'])})")

t3 = _overrides_trace({"mcps": [f"tool-{i}" + "x" * 200 for i in range(30)]})
check(
    len(t3["mcps"]) == 20 and all(len(x) <= 101 for x in t3["mcps"]),
    f"V3 리스트 20개·항목 100캡 (got {len(t3['mcps'])})",
)

check(
    _overrides_trace({}) is None
    and _overrides_trace(None) is None
    and _overrides_trace("x") is None,
    "V4 빈/None/비-dict → None",
)
check(_overrides_trace({"model": None}) is None, "V4b None 값 키는 스킵 → None")

# V5(codex 134 #1) — 공백 systemPrompt는 백엔드가 적용 안 함 → 트레이스도 미기록(가드 미러)
check(
    _overrides_trace({"systemPrompt": "   "}) is None,
    "V5 공백 systemPrompt → 미기록(적용 가드 미러)",
)
check(
    _overrides_trace({"systemPrompt": "   ", "model": "m"}) == {"model": "m"}, "V5b 다른 키는 유지"
)

print(f"\n{passed} passed, {len(_fails)} failed")
if _fails:
    sys.exit(1)
