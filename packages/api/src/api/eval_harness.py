"""에이전트 평가 하네스(스펙 119) — 데이터셋 × 실행함수 → **결정적 수치 점수**.

수치 기반 자율(목표 주고 무한 반복, Ralph)의 재료: 에이전트가 "좋아졌나"를 자동·결정적으로 판정하는
숫자. LLM 생성 텍스트는 비결정이라 **행위(trace 노드)·구조 신호를 하한**으로 스코어링한다(LLM-judge는
비결정 별도 축, 후속). 재사용 규약: `run_eval(cases, run_fn)` — run_fn만 갈아끼우면 어떤 실행 경로든 평가.

  run_fn(case) -> {"output": str, "trace_nodes": list[str], "error": bool}

scorer는 `(name, fn)` 팩토리 — fn(obs) -> bool. case는 asserts 전부 통과해야 pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable


# --- scorer 팩토리(결정적) — obs dict를 받아 bool ---
def trace_has(prefix: str):
    """trace 노드 중 prefix로 시작하는 게 하나라도 있으면 통과(행위 신호 — broker_invoke:* 등)."""
    return (f"trace_has:{prefix}", lambda o: any(str(n).startswith(prefix) for n in o.get("trace_nodes", [])))


def trace_lacks(prefix: str):
    """prefix로 시작하는 trace 노드가 **없어야** 통과(무위임 대조 등)."""
    return (f"trace_lacks:{prefix}", lambda o: not any(str(n).startswith(prefix) for n in o.get("trace_nodes", [])))


def no_error():
    return ("no_error", lambda o: not o.get("error"))


def output_nonempty():
    return ("output_nonempty", lambda o: bool((o.get("output") or "").strip()))


def output_contains(sub: str):
    return (f"output_contains:{sub}", lambda o: sub in (o.get("output") or ""))


@dataclass
class EvalCase:
    name: str
    input: str
    asserts: list  # [(name, fn)] — scorer 팩토리 반환값
    meta: dict = field(default_factory=dict)  # run_fn이 참고할 부가정보(agent_id 등)


@dataclass
class CaseResult:
    name: str
    passed: bool
    details: list  # [(assert_name, bool)]
    obs: dict


@dataclass
class EvalReport:
    results: list

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def score(self) -> float:
        """전 case 통과율(0.0–1.0). 빈 데이터셋 = 0.0(측정할 게 없음 = 신호 없음)."""
        return (self.passed / self.total) if self.total else 0.0

    def summary(self) -> str:
        return f"score={self.score:.3f} ({self.passed}/{self.total} cases)"

    def failures(self) -> list:
        return [r for r in self.results if not r.passed]


async def run_eval(
    cases: list,
    run_fn: Callable[[EvalCase], Awaitable[dict]],
) -> EvalReport:
    """각 case를 run_fn으로 실행하고 asserts를 평가해 EvalReport(수치 점수) 반환. run_fn이 던지면 그
    case는 error 관측으로 접어 **평가를 멈추지 않는다**(한 케이스 실패가 전체 수치 산출을 깨면 안 됨)."""
    results = []
    for case in cases:
        try:
            obs = await run_fn(case)
        except Exception as exc:  # noqa: BLE001 — 실행 실패도 하나의 결과(error)로 수치에 반영
            obs = {"output": "", "trace_nodes": [], "error": True, "exception": repr(exc)}
        # scorer 예외는 그 assert **실패**로 접는다(전체 평가 중단 금지) — malformed obs·커스텀 scorer
        # 버그가 수치 산출을 깨면 안 됨(codex 119 P2). 개별 scorer가 하나의 신호일 뿐.
        details = []
        for name, fn in case.asserts:
            try:
                ok = bool(fn(obs))
            except Exception:  # noqa: BLE001
                ok = False
            details.append((name, ok))
        # **빈 asserts = 자동 통과 금지**(codex 119 P1 — 데이터셋 실수가 조용히 score를 올리면 자율 신호가
        # 거짓이 됨). assert가 하나도 없으면 그 case는 명시적으로 실패로 표기한다.
        if not details:
            results.append(CaseResult(case.name, False, [("_no_asserts", False)], obs))
            continue
        results.append(CaseResult(case.name, all(ok for _, ok in details), details, obs))
    return EvalReport(results)


# ----------------------------- 선언적 asserts 매핑 (스펙 137) -----------------------------
# 문제집(DB)의 asserts JSON([{"type","arg"}])을 scorer 팩토리로 변환. **닫힌 집합** — 미지 type은
# ValueError(평가는 fail-closed: 모르는 채점 기준을 조용히 통과 처리하면 조용한 초록, 회고 100 대죄).
def llm_judge(criterion: str):
    """LLM-judge 채점(스펙 139, 비결정 축) — 러너가 obs["judge"][criterion]에 심판 결과를 주입하고
    이 scorer는 읽기만 한다(부재=False, fail-closed — 심판 미실행/미설정을 통과로 위장 금지).
    이름에 짧은 해시 접미 — 앞 60자가 같은 다른 기준의 details 이름 충돌 방지(codex 139 #5)."""
    import hashlib
    suffix = hashlib.md5(criterion.encode()).hexdigest()[:4]
    return (
        f"llm_judge:{criterion[:56]}#{suffix}",
        lambda o: bool((o.get("judge") or {}).get(criterion, {}).get("pass", False)),
    )


_ASSERT_TYPES = {
    "trace_has": (trace_has, True),  # (팩토리, arg 필수 여부)
    "trace_lacks": (trace_lacks, True),
    "output_contains": (output_contains, True),
    "no_error": (no_error, False),
    "output_nonempty": (output_nonempty, False),
    "llm_judge": (llm_judge, True),  # 스펙 139 — 비결정 축(러너가 judge 주입)
}


def build_asserts(spec_list: list) -> list:
    """선언 JSON → [(name, fn)] scorer 목록. 형식/type 오류는 ValueError(API 검증 계층에서 400으로)."""
    n_judge = sum(1 for it in (spec_list or []) if isinstance(it, dict) and it.get("type") == "llm_judge")
    if n_judge > 5:
        # 케이스당 judge 시간 상한(codex 139 #4): 5개 × 30초 타임아웃 = 최악 2.5분/케이스.
        raise ValueError(f"llm_judge 기준은 케이스당 5개 이하여야 합니다 (got {n_judge})")
    out = []
    for i, item in enumerate(spec_list or []):
        if not isinstance(item, dict) or "type" not in item:
            raise ValueError(f"asserts[{i}]: {{'type', 'arg'}} 형식이어야 합니다")
        t = item["type"]
        if t not in _ASSERT_TYPES:
            raise ValueError(f"asserts[{i}]: 알 수 없는 type {t!r} (허용: {sorted(_ASSERT_TYPES)})")
        factory, needs_arg = _ASSERT_TYPES[t]
        arg = item.get("arg")
        if needs_arg:
            if not isinstance(arg, str) or not arg.strip():
                raise ValueError(f"asserts[{i}]: type {t!r}는 비어있지 않은 문자열 arg가 필요합니다")
            if len(arg) > 500:
                raise ValueError(f"asserts[{i}]: arg는 500자 이하여야 합니다 (got {len(arg)}자)")
            out.append(factory(arg))
        else:
            out.append(factory())
    return out
