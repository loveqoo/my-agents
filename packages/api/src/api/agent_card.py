"""A2A Agent Card fetch·검증 (스펙 026, 1차).

외부 에이전트는 자기 capabilities·skills·서비스 엔드포인트·인증을 **Agent Card**(JSON 문서)로
광고한다. 카드 URL을 받아 fetch하고 필수 필드를 검증한다. 실제 A2A 호출(JSON-RPC message/send)은
2차 스펙 — 여기서는 등록에 필요한 카드 메타만 다룬다.

검증 실패는 ValueError(명확한 사유)로 던지고, 라우터가 4xx로 변환한다.
"""

import json

import httpx

from .net_guard import guard_url

# A2A 카드 관례 위치(신규 → 레거시 순). 베이스 URL만 준 경우 시도한다.
WELL_KNOWN_PATHS = ("/.well-known/agent-card.json", "/.well-known/agent.json")

# 카드 응답 본문 상한 — 악의적/오작동 서버가 거대한 JSON을 흘려 메모리·시간을 소진하는 걸 막는다.
MAX_CARD_BYTES = 256 * 1024


def validate_card(card: dict) -> None:
    """A2A Agent Card 필수 필드 검증. 부족하면 어느 필드가 빠졌는지 ValueError."""
    if not isinstance(card, dict):
        raise ValueError("Agent Card는 JSON 객체여야 합니다")
    name = card.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Agent Card에 'name'(문자열)이 없습니다")
    url = card.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ValueError("Agent Card에 서비스 'url'이 없습니다(A2A 호출 엔드포인트)")
    # capabilities(객체) 또는 skills(배열) 중 최소 하나는 제대로 채워져 있어야 한다.
    # 타입까지 본다 — `"skills": "x"` 같은 잡값이 통과하지 않도록.
    has_caps = isinstance(card.get("capabilities"), dict) and bool(card.get("capabilities"))
    has_skills = isinstance(card.get("skills"), list) and bool(card.get("skills"))
    if not has_caps and not has_skills:
        raise ValueError("Agent Card에 'capabilities'(객체) 또는 'skills'(배열)가 없습니다")


def _looks_like_card(data: object) -> bool:
    return isinstance(data, dict) and "name" in data and "url" in data


async def fetch_card(card_url: str) -> dict:
    """카드 URL을 GET해 카드 JSON을 반환. 카드 문서가 아니라 베이스 URL이면 well-known 관례 시도.

    네트워크/파싱/검증 실패는 ValueError로 통일(라우터가 4xx). 비밀값은 메시지에 넣지 않는다.
    """
    url = card_url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise ValueError("cardUrl은 http(s) 절대 URL이어야 합니다")
    # SSRF 가드(스펙 042 — 026에서 유예한 빚 청산). 후보는 path만 다르고 host는 같으니 한 번 검사.
    guard_url(url)  # 차단 시 SsrfBlocked(ValueError) → 라우터 4xx

    candidates = [url] + [url + p for p in WELL_KNOWN_PATHS]
    last_err: str = ""
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        for candidate in candidates:
            try:
                body = await _fetch_capped(client, candidate)
            except _CardFetchError as exc:
                last_err = str(exc)
                continue
            try:
                data = json.loads(body)
            except ValueError:
                last_err = "카드 응답이 JSON이 아닙니다"
                continue
            if _looks_like_card(data):
                validate_card(data)
                return data
            last_err = "카드 형식이 아닙니다(name/url 없음)"
    raise ValueError(f"Agent Card를 가져오지 못했습니다: {last_err or '알 수 없는 오류'}")


async def probe_endpoint(url: str | None) -> bool:
    """A2A 서비스 엔드포인트 liveness probe(스펙 045, #2).

    카드 published ≠ 실행 엔드포인트 live. 등록 시 endpoint 도달성을 한 번 확인해 status를
    정직하게 정한다. SSRF 가드 후 짧은 타임아웃으로 요청 — **어떤 HTTP status여도 응답이 오면
    live**(A2A는 표준 health 메서드가 없어 도달=충분), 연결오류/타임아웃이면 dead. 예외·비밀값은
    삼키고 bool만 반환(등록을 막지 않는다).

    follow_redirects=False: guard_url은 *최초* URL의 resolve IP만 검사하므로, 리다이렉트를
    추종하면 공개 호스트가 302로 내부 IP(169.254.169.254·127.0.0.1 등)를 가리켜 SSRF 가드를
    우회할 수 있다. 3xx 응답은 그 자체로 '도달=live'로 충분하니 추종하지 않는다(적대 리뷰 045)."""
    if not url or not isinstance(url, str):
        return False
    target = url.strip().rstrip("/")
    if not target.startswith(("http://", "https://")):
        return False
    try:
        guard_url(target)  # SSRF 차단이면 dead로 취급(등록은 라우터가 별도 판단)
    except ValueError:
        return False
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
            resp = await client.get(target, headers={"Accept": "application/json"})
            return resp.status_code < 600  # 응답 자체가 도달 신호(3xx 포함)
    except Exception:
        # probe는 절대 raise하지 않는다 — 등록을 막으면 안 되므로 어떤 예외도 dead로 흡수.
        return False


class _CardFetchError(Exception):
    """fetch_card 내부 후보 시도 실패 — 다음 후보로 넘어가게 하는 신호."""


async def _fetch_capped(client: httpx.AsyncClient, candidate: str) -> bytes:
    """후보 URL을 스트리밍으로 GET하되 MAX_CARD_BYTES를 넘기면 중단. 본문 bytes 반환."""
    try:
        async with client.stream("GET", candidate, headers={"Accept": "application/json"}) as resp:
            if resp.status_code >= 400:
                raise _CardFetchError(f"카드 응답 오류 {resp.status_code}")
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > MAX_CARD_BYTES:
                    raise _CardFetchError("카드 응답이 너무 큽니다(256KB 초과)")
                chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise _CardFetchError(f"요청 실패({type(exc).__name__})") from exc
    return b"".join(chunks)
