"""A2A Agent Card fetch·검증 (스펙 026, 1차).

외부 에이전트는 자기 capabilities·skills·서비스 엔드포인트·인증을 **Agent Card**(JSON 문서)로
광고한다. 카드 URL을 받아 fetch하고 필수 필드를 검증한다. 실제 A2A 호출(JSON-RPC message/send)은
2차 스펙 — 여기서는 등록에 필요한 카드 메타만 다룬다.

검증 실패는 ValueError(명확한 사유)로 던지고, 라우터가 4xx로 변환한다.
"""

import json
from urllib.parse import urljoin, urlparse

import httpx

from .net_guard import guard_url, normalize_http_url, refresh_allowed_hosts

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


def _resolve_card_endpoint(raw: str, candidate: str) -> str:
    """카드가 광고한 service url을 *카드가 마운트된 prefix* 기준으로 절대화한다(스펙 071).

    A2A 스펙은 카드 url을 절대 URL로 강제하지만, 프록시 path-prefix 배포의 원격 앱은 자기를 root로
    착각해 루트상대 `/a2a`를 발행한다(외부 경로는 `/prefix/a2a`). `urljoin(candidate, "/a2a")`는
    RFC 3986상 prefix를 버리고 origin 루트로 가 채팅 때 404가 난다. 여기서는 카드를 가져온 candidate
    에서 well-known 접미를 떼어 mount prefix를 얻고, 상대 url을 그 prefix 하위로 해석한다(커뮤니티
    a2aproject/A2A#160 의도).

    경계(적대 리뷰 071):
    - 절대/스킴상대/스킴보유(`scheme://`) url은 prefix 무관이라 `normalize_http_url`에 그대로 위임
      (기존 동작 불변). 이 분기는 카드 host와 *다른* host를 가리킬 수 있으나(절대 url은 원래 그랬다),
      호출 시점 `guard_url`이 정규화된 endpoint에 그대로 돌아 사설/루프백을 여전히 차단한다(표면 불변).
    - 상대 url(`/x`·bare `x`)은 **카드 host에 고정** — mount prefix 디렉터리에 `urljoin`으로 resolve해
      절대화한 뒤 `normalize_http_url`을 통과시킨다(SSRF/userinfo/port 검증 동일). `urljoin`이라 dot-
      segment(`..`)는 canonical화되고 origin 위로는 못 올라간다(literal `..`가 stored endpoint에 안 남아
      프록시 path 정규화로 prefix를 탈출하는 표면을 줄임). bare `evil.com/x`도 prefix 하위 path로 묶여
      타host로 안 간다(host 혼동 차단).
    """
    s = (raw or "").strip()
    low = s.lower()
    # 절대·스킴상대·스킴보유(`scheme://`)는 prefix와 무관 — 기존 정규화에 위임.
    if low.startswith(("http://", "https://")) or s.startswith("//") or "://" in s:
        return normalize_http_url(s)
    # mount = 카드를 가져온 candidate에서 well-known 접미 제거 → 원격 앱의 외부 마운트 경로.
    mount = candidate
    for p in WELL_KNOWN_PATHS:
        if mount.endswith(p):
            mount = mount[: -len(p)]
            break
    mp = urlparse(mount)
    origin = f"{mp.scheme}://{mp.netloc}"
    prefix = mp.path.rstrip("/")  # 예: /ai-core/ccab-weekly-report (없으면 "")
    # 루트상대(`/x`)·bare(`x`) 모두 mount prefix 디렉터리 기준 상대로 resolve. urljoin이 dot-segment를
    # 정리하고 origin서 clamp한다(string concat과 달리 `..`가 literal로 안 남는다 — 적대 리뷰 071 F4).
    resolved = urljoin(origin + prefix + "/", s.lstrip("/"))
    return normalize_http_url(resolved)


async def fetch_card(card_url: str) -> dict:
    """카드 URL을 GET해 카드 JSON을 반환. 카드 문서가 아니라 베이스 URL이면 well-known 관례 시도.

    네트워크/파싱/검증 실패는 ValueError로 통일(라우터가 4xx). 비밀값은 메시지에 넣지 않는다.
    """
    url = card_url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise ValueError("cardUrl은 http(s) 절대 URL이어야 합니다")
    # SSRF 가드(스펙 042 — 026에서 유예한 빚 청산). 후보는 path만 다르고 host는 같으니 한 번 검사.
    await refresh_allowed_hosts()  # DB allowlist 무재시작 반영(스펙 064)
    guard_url(url)  # 차단 시 SsrfBlocked(ValueError) → 라우터 4xx

    candidates = [url] + [url + p for p in WELL_KNOWN_PATHS]
    last_err: str = ""
    # follow_redirects=False: guard_url은 *최초* URL의 resolve IP만 검사하므로, 리다이렉트를 추종하면
    # 공개 카드 호스트가 302로 내부 IP(127.0.0.1·169.254.169.254 등)를 가리켜 SSRF 가드를 우회할 수
    # 있다(probe_endpoint·a2a_client와 동일 규칙, 적대리뷰 057). 3xx는 카드 JSON이 아니므로 해당 후보를
    # 건너뛰고 다음 well-known 후보로 넘어간다.
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
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
                # 서비스 url을 절대 http(s)로 정규화(스펙 060). 스킴 없는 host:port·`/`-상대 url이
                # 등록은 통과하고 호출(guard_url) 때 늦게 깨지던 모드1을 등록 시점에 해소한다. 루트상대
                # `/a2a`는 카드가 마운트된 prefix 하위로 resolve해 프록시 path-prefix 배포의 404를 구제한다
                # (스펙 071 — 이전엔 origin루트로 가 prefix 탈락). 절대화 불가면 ValueError가 fetch_card
                # 밖으로(라우터 400). 보안 불변: 절대화만, 사설 판정은 guard_url(결과 normalize 통과).
                data["url"] = _resolve_card_endpoint(data["url"], candidate)
                return data
            last_err = "카드 형식이 아닙니다(name/url 없음)"
    raise ValueError(f"Agent Card를 가져오지 못했습니다: {last_err or '알 수 없는 오류'}")


async def probe_endpoint(url: str | None) -> bool:
    """A2A 서비스 엔드포인트 liveness probe(스펙 045, #2).

    카드 published ≠ 실행 엔드포인트 live. 등록 시 endpoint 도달성을 한 번 확인해 status를
    정직하게 정한다. SSRF 가드 후 짧은 타임아웃으로 요청 — 응답이 오면 대체로 live지만 **404/410
    (경로 부재)은 dead**로 본다(스펙 071): A2A JSON-RPC endpoint는 GET에 보통 405(Method Not Allowed)
    를 주므로 404는 라우트 부재 = 잘못된 endpoint 신호다(prefix 오resolve 증상과 일치). 그 외 status
    (200/3xx/401/403/405)는 live, 연결오류/타임아웃도 dead. 트레이드오프(적대 리뷰 071 F3): 일부
    프레임워크는 method-mismatch에도 404를 주므로 *정상 endpoint를 dead로* 오판할 수 있다 — 단 이는
    **status 라벨(online/offline)만** 좌우하고 endpoint 저장·실호출 가능성은 그대로라 사용성 무관(수용).
    예외·비밀값은 삼키고 bool만 반환(등록을 막지 않는다 — status만 정직).

    follow_redirects=False: guard_url은 *최초* URL의 resolve IP만 검사하므로, 리다이렉트를
    추종하면 공개 호스트가 302로 내부 IP(169.254.169.254·127.0.0.1 등)를 가리켜 SSRF 가드를
    우회할 수 있다. 3xx 응답은 그 자체로 '도달=live'로 충분하니 추종하지 않는다(적대 리뷰 045)."""
    if not url or not isinstance(url, str):
        return False
    target = url.strip().rstrip("/")
    if not target.startswith(("http://", "https://")):
        return False
    try:
        await refresh_allowed_hosts()  # DB allowlist 무재시작 반영(스펙 064)
        guard_url(target)  # SSRF 차단이면 dead로 취급(등록은 라우터가 별도 판단)
    except ValueError:
        return False
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
            resp = await client.get(target, headers={"Accept": "application/json"})
            # 404/410은 경로 부재 = 잘못된 endpoint(dead). 그 외 도달은 live(3xx·405·인증 포함).
            return resp.status_code not in (404, 410)
    except Exception:
        # probe는 절대 raise하지 않는다 — 등록을 막으면 안 되므로 어떤 예외도 dead로 흡수.
        return False


# my-agents 카드 확장 네임스페이스 — 우리가 SDK로 배포한 제1자 에이전트 신호(스펙 057).
MY_AGENTS_EXT_KEYS = ("x-my-agents", "myAgents")


def extract_my_agents(card: object) -> dict | None:
    """A2A 카드의 my-agents 확장 블록을 안전 파싱 → provenance 분류 신호(스펙 057).

    카드에 `x-my-agents`(또는 `myAgents`) 확장이 있고 그 안에 `manifest`(객체)가 있으면 **우리가
    SDK로 배포한 제1자 에이전트**로 본다(source=code). 없거나 형식이 어긋나면 None → 제3자
    (source=external). 제3자가 잡값/부분필드를 흘려도 터지지 않게 전 구간 타입 가드:
    - card가 dict 아님 → None
    - 확장이 dict 아님(문자열·배열 등) → None
    - manifest가 dict 아님 → None (provenance로 인정 안 함 — 표시 메타가 없으면 code일 이유 없음)
    deploy는 선택(없으면 빈 dict). manifest/deploy 두 하위 블록만 정규화해 반환한다.

    주의(스펙 057 리스크): 카드 자기선언이라 제3자가 이 확장을 흉내내면 code로 보인다. 1차 범위는
    수용 — code/external 모두 읽기전용·로컬 미해석이라 권한 상승이 아니라 표시·메타 차이일 뿐.
    서명 검증은 별 스펙.
    """
    if not isinstance(card, dict):
        return None
    ext = None
    for key in MY_AGENTS_EXT_KEYS:
        candidate = card.get(key)
        if isinstance(candidate, dict):
            ext = candidate
            break
    if ext is None:
        return None
    manifest = ext.get("manifest")
    if not isinstance(manifest, dict):
        return None
    deploy = ext.get("deploy")
    if not isinstance(deploy, dict):
        deploy = {}
    return {"manifest": manifest, "deploy": deploy}


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
