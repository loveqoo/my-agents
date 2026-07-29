"""외부 의존성 호출 정책 단일 대장 + 서킷브레이커(스펙 430).

**왜**: 타임아웃이 호출부 8곳에 제각각 하드코딩(15/5/10/30/60/120…)이고, 가장 중요한 모델 본선은
우리가 고른 적 없는 SDK 기본(600s·재시도 2)에 방치돼 있었다(2026-07-29 grep 전수 감사). 파라미터
서술자(스펙 409/411)가 4화면을 한 줄로 구동하듯, 외부호출 정책도 **여기 한 곳**이 정본이다
(policy-at-the-chokepoint) — 호출부는 값을 하드코딩하지 않고 대장을 참조한다.

**서킷브레이커**(구남님 교정으로 채택 — "과설계" 첫 기각이 틀렸음): 개인 사용의 실제 고통은 행(hang)
반복이다. 죽은 의존성에 매 요청이 타임아웃을 꽉 채워 기다리는 대신, 연속 실패 임계에서 회로를 열어
**즉시 실패 + "N초 후 재시도" 표면화**로 방어한다. 대안 경로 폴백은 클래스별로 안전한 것만(모델은
대체 모델로 조용히 갈아타지 않는다 — 스펙 428 "선언과 다른 실행 금지"와 정합).

agent 패키지에 둔 이유: 모델 호출 관문(reasoning_chat)이 agent 층이고 api→agent 단방향이라 여기가
양쪽(모델·api의 A2A/MCP/eval/카드)이 공유 가능한 유일한 층(capabilities.py와 같은 근거).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


# ----------------------------- 정책 대장 -----------------------------
@dataclass(frozen=True)
class CallPolicy:
    """외부 의존성 클래스 하나의 호출 정책(스펙 430).

    - timeout_s: 의미는 **호출부 배선에 따라 둘**(codex 430 정직화 — "전체 deadline" 단일 주장 틀렸음):
      `asyncio.timeout()`으로 감싼 곳(mcp.tool·mcp.discover)은 전체 벽시계 deadline, httpx/SDK에 넘기는
      곳(model.*·a2a·card·probe·rag)은 **per-phase 타임아웃**(connect/read/write 각각) — 행(무응답) 감지가
      목적이고, 스트리밍 총 시간은 의도적으로 무한(긴 생성은 정당). 느린-드립 방어가 필요한 신뢰경계
      호출은 호출부가 별도 wall-clock을 감쌈(providers _STREAM_DEADLINE 선례, learning 046).
    - retries: 멱등 호출만 >0(비멱등=생성·위임·도구는 0 — 재시도가 중복 부수효과·이중 과금).
      백오프 = 0.5s * 2^attempt.
    - breaker: 서킷브레이커 적용 여부 — 반복 호출로 행이 누적되는 클래스만(산발 호출은 임계에
      안 닿아 노이즈만).
    """

    key: str
    timeout_s: float
    retries: int = 0
    breaker: bool = False
    note: str = ""


# 정본 목록(구남님 승인 수치 — 스펙 430). 값 변경은 여기 한 줄.
POLICIES: tuple[CallPolicy, ...] = (
    CallPolicy(
        "model.chat", 180.0, retries=0, breaker=True,
        note="본선 생성 — 긴 사고/생성 허용. 비멱등이라 재시도 0(중복 생성·이중 과금 방지). "
        "SDK 암묵 600s·재시도2를 명시 정책으로 교체",
    ),
    CallPolicy(
        "model.eval", 60.0, retries=1, breaker=True,
        note="평가 계열(judge/golden/harvest/suggest) 통일 — 종전 30/30/30/60 제각각. 읽기성 생성이라 1회 재시도",
    ),
    CallPolicy(
        "a2a.delegate", 120.0, retries=0, breaker=True,
        note="종전 A2A_TIMEOUT_S=120 흡수 — 위임은 비멱등(원격 부수효과)",
    ),
    CallPolicy(
        "mcp.tool", 30.0, retries=0, breaker=True,
        note="종전 _TOOL_TIMEOUT_S=30 흡수 — 도구는 부수효과 가능, 재시도 0",
    ),
    CallPolicy(
        "card.fetch", 10.0, retries=1,
        note="에이전트 카드 조회 — 멱등 GET. 종전 15/5 두 값을 10으로 통일",
    ),
    CallPolicy(
        "probe", 10.0, retries=0,
        note="연결/모델 probe — 빠른 실패가 목적(재시도가 오히려 진단 지연)",
    ),
    CallPolicy(
        "mcp.discover", 15.0, retries=0,
        note="MCP 서버 도구 탐색(연결+목록) — 종전 blocks_mcp_discovery asyncio.timeout(15) 흡수"
        "(codex 430: 첫 감사가 asyncio.timeout 지점을 놓침 — httpx만 grep한 맹점)",
    ),
    CallPolicy(
        "web.fetch", 8.0, retries=0,
        note="web-fetch 커스텀 MCP(위키 API — 호스트 고정) — 종전 8.0 흡수. 도구 graceful 경로라 재시도 0",
    ),
    CallPolicy(
        "rag.embed", 60.0, retries=1,
        note="인제스트 임베딩 배치(POST /embeddings) — 같은 입력=같은 벡터(멱등)라 1회 재시도. "
        "감사 첫 표기 'URL 다운로드'는 오독 — 실체는 임베딩 호출(스펙 430 교정)",
    ),
)

_BY_KEY: dict[str, CallPolicy] = {p.key: p for p in POLICIES}


def policy(key: str) -> CallPolicy:
    """정책 조회 — 미등록 키는 즉시 KeyError(조용한 기본값 폴백 금지, learning 092 결)."""
    return _BY_KEY[key]


# ----------------------------- 서킷브레이커 -----------------------------
# 상태는 프로세스-로컬 (policy_key, host) 별 — host 단위 격리(atom-spark 열림이 MLX 무영향).
# 단일 이벤트 루프에서 check/record가 전부 동기(await 없는 read-modify-write)라 락 불요.
BREAKER_THRESHOLD = 3  # 연속 실패 이 횟수에서 열림(구남님 승인)
BREAKER_COOLDOWN_S = 30.0  # 열림 유지 시간 — 경과 후 half-open 1회 시도(구남님 승인)


class CircuitOpenError(RuntimeError):
    """회로 열림 — 즉시 실패. remaining_s로 "N초 후 재시도"를 표면화한다."""

    def __init__(self, key: str, host: str, remaining_s: float) -> None:
        self.key = key
        self.host = host
        self.remaining_s = max(0.0, remaining_s)
        super().__init__(
            f"'{host}' 연결 회로가 열려 있습니다({key} — 연속 실패 {BREAKER_THRESHOLD}회). "
            f"약 {self.remaining_s:.0f}초 후 자동 재시도합니다."
        )


@dataclass
class _Circuit:
    failures: int = 0
    opened_at: float | None = None  # None=닫힘
    trial_pending: bool = False  # half-open 1회 시도 in-flight(경쟁 차단)


_circuits: dict[tuple[str, str], _Circuit] = {}


def _norm_host(host: str) -> str:
    """회로 키 정규화(codex 430 P2) — URL이 오면 host만 추출(같은 서버 다른 경로가 회로를 공유하고,
    userinfo·query가 스냅샷/관측 라우트로 새지 않게). URL 아니면(서버명 등) 그대로."""
    if "://" in host:
        try:
            import httpx

            return httpx.URL(host).host or host
        except Exception:  # 정규화 실패는 원문 유지(회로 기능은 동작)
            return host
    return host


def _circuit(key: str, host: str) -> _Circuit:
    return _circuits.setdefault((key, _norm_host(host)), _Circuit())


def check(key: str, host: str) -> None:
    """호출 전 회로 검사 — 열려 있으면 CircuitOpenError(즉시 실패). breaker 미적용 정책은 no-op.

    half-open: cooldown 경과 후 **1회만** 통과시킨다(trial_pending — 동시 요청이 다 뚫는 경쟁 차단,
    codex 우려 지점). 그 시도의 record_success/failure가 회로를 닫거나 다시 연다."""
    if not _BY_KEY[key].breaker:
        return
    c = _circuit(key, host)
    if c.opened_at is None:
        return
    elapsed = time.monotonic() - c.opened_at
    if elapsed < BREAKER_COOLDOWN_S:
        raise CircuitOpenError(key, host, BREAKER_COOLDOWN_S - elapsed)
    if c.trial_pending:  # half-open 시도가 이미 나가 있음 — 그 결과가 날 때까지 즉시 실패 유지
        raise CircuitOpenError(key, host, 1.0)
    c.trial_pending = True  # 이 요청이 half-open 1회 시도


def record_success(key: str, host: str) -> None:
    """성공 — 회로 닫힘·카운트 리셋(half-open 시도 성공 포함)."""
    c = _circuit(key, host)
    c.failures = 0
    c.opened_at = None
    c.trial_pending = False


def release(key: str, host: str) -> None:
    """판정 불가 종료(소비자 이탈 GeneratorExit·비일시 오류 등) — **trial만 해제**하고 성공/실패 어느
    쪽도 기록하지 않는다(codex 430 P1: 이걸 안 하면 half-open trial_pending이 영영 남아 회로가
    프로세스 재시작 전까지 고착). opened_at은 그대로 — cooldown 경과 상태면 다음 요청이 새 trial."""
    c = _circuit(key, host)
    c.trial_pending = False


def record_failure(key: str, host: str) -> None:
    """**타임아웃·연결 오류만** 여기로(호출부 계약) — HTTP 4xx(권한·잘못된 요청)는 의존성 건강과
    무관하니 세지 않는다(설정 실수가 회로를 열어 오진하는 것 방지, 스펙 430). 임계 도달 또는
    half-open 시도 실패 → 열림(타이머 리셋)."""
    c = _circuit(key, host)
    c.failures += 1
    c.trial_pending = False
    if c.failures >= BREAKER_THRESHOLD or c.opened_at is not None:
        c.opened_at = time.monotonic()


def breaker_snapshot() -> list[dict]:
    """관측용(GET /admin/net-policies) — 현재 회로 상태 스냅샷(비밀 없음: key·host·상태만)."""
    now = time.monotonic()
    out = []
    for (key, host), c in _circuits.items():
        state = "closed"
        remaining = 0.0
        if c.opened_at is not None:
            elapsed = now - c.opened_at
            state = "half-open" if elapsed >= BREAKER_COOLDOWN_S else "open"
            remaining = max(0.0, BREAKER_COOLDOWN_S - elapsed)
        out.append(
            {"key": key, "host": host, "state": state, "failures": c.failures,
             "remainingS": round(remaining, 1)}
        )
    return out


def _reset_circuits() -> None:
    """테스트 전용 — 회로 전체 리셋."""
    _circuits.clear()


# ----------------------------- 호출 헬퍼(재시도+브레이커 일체) -----------------------------
def _is_transient(exc: BaseException) -> bool:
    """실패로 셀 예외 판정 — 타임아웃·연결 계열만(4xx/응답 수신 오류는 제외). httpx·openai 모두
    지연 임포트(어느 한쪽만 설치된 소비자도 동작)."""
    try:
        import httpx

        # TransportError = Timeout·Network(Connect/Read/Write/Close)·Protocol·Proxy 전부 — 전송층이
        # 죽은 모든 모양(codex 430: ConnectError만 보던 첫 판정은 mid-stream RST·EOF를 놓쳤다).
        # HTTPStatusError(4xx/5xx 응답 수신)는 TransportError가 아니라 자연 제외(서버가 살아 응답).
        if isinstance(exc, httpx.TransportError):
            return True
    except ImportError:  # pragma: no cover
        pass
    try:
        import openai

        # APITimeoutError는 APIConnectionError의 서브클래스 — 연결 계열 전부. APIStatusError(4xx/5xx
        # 응답 수신)는 "서버가 살아서 응답한 것"이라 회로에 안 센다.
        if isinstance(exc, openai.APIConnectionError):
            return True
    except ImportError:  # pragma: no cover
        pass
    return isinstance(exc, asyncio.TimeoutError | TimeoutError | ConnectionError)


async def call[T](key: str, host: str, fn: Callable[[], Awaitable[T]]) -> T:
    """정책 적용 호출 — 브레이커 검사 → fn 실행 → 성공/실패 기록, 정책 retries만큼 백오프 재시도.

    fn은 자체 타임아웃을 이미 갖는 호출(httpx client에 policy timeout 적용)이어야 한다 — 이 헬퍼는
    회로·재시도만 담당(이중 타임아웃 중첩 방지). 일시 오류(_is_transient)만 재시도·회로 기록 대상."""
    p = _BY_KEY[key]
    check(key, host)
    try:
        for attempt in range(p.retries + 1):
            try:
                result = await fn()
            except Exception as exc:
                if not _is_transient(exc):
                    # 4xx 등 — 회로에 안 세고 재시도도 안 함(의존성 건강과 무관). release는 바깥
                    # finally-except가 담당(codex 430 P1 — half-open trial 고착 방지).
                    raise
                record_failure(key, host)
                if attempt >= p.retries:
                    raise
                await asyncio.sleep(0.5 * (2**attempt))
                check(key, host)  # 재시도 사이 회로가 열렸으면 중단(미문서 경계 — 스펙 430 OUT)
            else:
                record_success(key, host)
                return result
    except Exception as exc:
        if not _is_transient(exc) and not isinstance(exc, CircuitOpenError):
            release(key, host)  # 판정 불가 종료 — trial만 해제
        raise
    raise AssertionError("unreachable")  # pragma: no cover
