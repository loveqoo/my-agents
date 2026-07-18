"""verify (단위) — codex 259-261 적대 리뷰 후속 하드닝 (스키마 화이트리스트·상한).

  H1 키 화이트리스트: model_cfg·임의 키는 저장에서 드롭(비밀 에코 풋건 봉인, codex P3).
  H2 알려진 필드 보존: name/model/tools/context/format/fields 라운드트립.
  H3 값 화이트리스트: context/format 잡값은 드롭(런타임 normalize와 정합).
  H4 상한: prompt>20000·tools>100·fields>100 → 422(ValueError). nodes>50 기존.
  H5 리스트 내 잡값 정리: tools/fields의 비문자열·과길이 원소 제거.

실행: uv run --project packages/api python tests/verify_codex_259_261_hardening.py
"""

import os
import sys

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"
    ),
)

from pydantic import ValidationError  # noqa: E402

from api.schemas import AgentConfig  # noqa: E402

_fails = []
passed = 0


def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


def _nodes(cfg):
    return AgentConfig(nodes=cfg).nodes


def _rejects(cfg, label):
    try:
        AgentConfig(nodes=cfg)
        check(False, f"{label} — 거부돼야 함(통과됨)")
    except ValidationError:
        check(True, label)


def main():
    # H1 화이트리스트 — model_cfg·임의 키 드롭
    n = _nodes([{"prompt": "p", "model_cfg": {"api_key": "SECRET"}, "evil": "x", "internal": 1}])
    check("model_cfg" not in n[0], "H1 model_cfg 드롭(비밀 에코 봉인)")
    check("evil" not in n[0] and "internal" not in n[0], "H1 임의 키 드롭(화이트리스트)")
    check(n[0] == {"prompt": "p"}, f"H1 알려진 키만 남음 (got {n[0]})")

    # H2 알려진 필드 보존
    n = _nodes(
        [
            {
                "name": "분석",
                "prompt": "P",
                "model": "gpt",
                "tools": ["add"],
                "context": "clean",
                "format": "json",
                "fields": ["title"],
            }
        ]
    )
    check(
        n[0]
        == {
            "name": "분석",
            "prompt": "P",
            "model": "gpt",
            "tools": ["add"],
            "context": "clean",
            "format": "json",
            "fields": ["title"],
        },
        f"H2 알려진 필드 라운드트립 (got {n[0]})",
    )

    # H3 값 화이트리스트 — context/format 잡값 드롭
    n = _nodes([{"prompt": "P", "context": "hacker", "format": "yaml"}])
    check("context" not in n[0] and "format" not in n[0], "H3 context/format 잡값 드롭")

    # H4 상한
    _rejects([{"prompt": "x" * 20001}], "H4 prompt>20000 거부")
    _rejects([{"prompt": "P", "tools": ["t"] * 101}], "H4 tools>100 거부")
    _rejects([{"prompt": "P", "fields": ["f"] * 101}], "H4 fields>100 거부")
    _rejects([{"prompt": "P"}] * 51, "H4 nodes>50 거부(기존)")
    _rejects([{"prompt": "P", "name": "n" * 201}], "H4 name>200 거부")

    # H5 리스트 내 잡값 정리
    n = _nodes([{"prompt": "P", "tools": ["ok", 123, "y" * 201, "ok2"]}])
    check(
        n[0]["tools"] == ["ok", "ok2"], f"H5 tools 비문자열·과길이 원소 제거 (got {n[0]['tools']})"
    )

    # 빈 prompt 여전히 거부(기존)
    _rejects([{"prompt": "   "}], "H4 빈 prompt 거부(기존)")

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        for f in _fails:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    main()
