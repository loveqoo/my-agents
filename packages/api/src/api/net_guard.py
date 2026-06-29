"""서버측 outbound URL 가드 (SSRF 방어, 스펙 042).

서버가 관리자/카드가 준 URL로 직접 요청을 보내는 경로(A2A 런타임 호출, Agent Card fetch)는
SSRF 표면이다 — 사설/루프백/링크로컬/메타데이터(169.254.169.254) 대역으로 향하는 요청은
내부 서비스·클라우드 메타데이터를 노출시킬 수 있다.

정책(스펙 042 합의): 호스트를 IP로 resolve해 사설대역이면 **차단**(기본). 단 호스트가
`A2A_ALLOWED_HOSTS`(쉼표구분 allowlist)에 있으면 통과 → dev mock(127.0.0.1) 동작.

알려진 한계(스펙 042 §7 빚): resolve→connect 사이 DNS 재바인딩(TOCTOU). 진짜 차단은 resolved
IP 핀(커스텀 transport)이 필요하나, 관리자 등록 경계라 resolve-and-check까지를 현실적 바로 둔다.
"""

import ipaddress
import os
import socket
from urllib.parse import urljoin, urlparse


class SsrfBlocked(ValueError):
    """가드가 outbound URL을 차단했다(사설대역·잘못된 스킴 등). ValueError 하위 → 라우터 4xx."""


def normalize_http_url(raw: str, *, base: str | None = None) -> str:
    """A2A 서비스 url을 **절대 http(s) URL**로 관대 정규화(스펙 060). 못 하면 ValueError(조치 메시지).

    A2A 카드의 서비스 `url`(또는 코드 에이전트 endpoint)이 스킴 없는 `host:port/path`처럼 와도 등록
    시점에 절대화해, 호출 시점(`guard_url`)에 "URL은 http(s) 절대 URL이어야 합니다"로 늦게·모호하게
    깨지지 않게 한다. **보안 불변**: 여기서 절대화만 하고 사설대역 판정은 안 한다 — 정규화된 url에
    `guard_url`이 그대로 돌아 사설/루프백을 여전히 차단한다(정규화는 가드를 우회시키지 않는다).

    규칙:
    - 이미 `http(s)://` → 그대로.
    - `//host/path`(스킴-상대) → `http:` 전치.
    - `/path`(진짜 경로 상대) → base 있으면 urljoin, 없으면 ValueError(절대화 불가).
    - 비-http 스킴(`ftp://`·`://x` 등) → ValueError(http 전치하면 이중스킴이 되므로 거부).
    - 스킴 없는 `host[:port][/path]` → `http://` 전치(dev 관대, curl/브라우저 관례).
    결과를 urlparse해 scheme∈{http,https} & hostname 존재를 단언, 아니면 ValueError.
    """
    s = (raw or "").strip()
    if not s:
        raise ValueError(
            "서비스 url이 비어 있습니다 — 카드의 url을 'http://host:port/path' 형태로 지정하세요."
        )
    low = s.lower()
    if low.startswith(("http://", "https://")):
        candidate = s
    elif s.startswith("//"):
        candidate = "http:" + s  # 스킴-상대 → http 전치
    elif s.startswith("/"):
        if not base:
            raise ValueError(
                f"상대 경로 url('{s[:80]}')을 절대화할 base가 없습니다 — "
                "카드의 url을 'http://host:port/path' 형태로 지정하세요."
            )
        candidate = urljoin(base, s)
    elif "://" in s:
        # 비-http 스킴(ftp://·잡 스킴) — http 전치하면 이중스킴이라 거부.
        raise ValueError(
            f"서비스 url 스킴이 http(s)가 아닙니다('{s[:80]}') — "
            "카드의 url을 'http://host:port/path' 형태로 지정하세요."
        )
    else:
        candidate = "http://" + s  # 스킴 없는 host[:port][/path] → http 전치
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(
            f"서비스 url을 절대 http(s) URL로 해석할 수 없습니다(받은 값: '{s[:80]}'). "
            "카드의 url을 'http://host:port/path' 형태로 지정하세요."
        )
    return candidate


def _allowed_hosts() -> set[str]:
    raw = os.environ.get("A2A_ALLOWED_HOSTS", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def _ip_is_blocked(ip: ipaddress._BaseAddress) -> bool:
    """공인(global) 대역이 아니면 차단. `not is_global`이 사설/루프백/링크로컬/예약/CGNAT
    (100.64/10)/문서·벤치마킹 대역까지 한 번에 거른다(개별 플래그 denylist의 누락 방지 — 적대리뷰 M1).
    멀티캐스트/미지정은 명시적으로도 막는다(방어적 중복)."""
    return (not ip.is_global) or ip.is_multicast or ip.is_unspecified


def host_is_private(host: str) -> bool:
    """host가 **로컬/사설**(루프백·사설·링크로컬·CGNAT 등 비-global)으로만 resolve되면 True.

    `_self_base`가 `request.base_url`(=Host 헤더 파생) 폴백을 신뢰해도 되는지 판단하는 데 쓴다 —
    공인 Host로 들어온 요청에 `A2A_SELF_BASE_URL`이 없으면 카드 `url`이 공격자 호스트를 가리켜
    이후 A2A 호출이 프롬프트·Bearer 토큰을 유출할 수 있다(적대리뷰 H1, 스펙 061 §5). 그래서 폴백은
    로컬/사설 Host에 한정한다. 보수적: resolve 실패하거나 공인 IP가 하나라도 섞이면 False(→ env 강제).
    """
    h = (host or "").strip().lower()
    if not h:
        return False
    try:  # 리터럴 IP 빠른 경로([::1]·100.x Tailscale 등).
        return _ip_is_blocked(ipaddress.ip_address(h.strip("[]")))
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(h, None)
    except socket.gaierror:
        return False
    saw = False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        saw = True
        if not _ip_is_blocked(ip):
            return False  # 공인 IP 하나라도 있으면 신뢰 불가
    return saw


def guard_url(url: str) -> None:
    """outbound URL을 검사. http(s)·공인 대역만 허용. 위반 시 SsrfBlocked(ValueError).

    allowlist(`A2A_ALLOWED_HOSTS`)에 든 호스트는 사설대역이라도 통과(dev mock).
    """
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise SsrfBlocked("URL은 http(s) 절대 URL이어야 합니다")
    host = parsed.hostname
    if not host:
        raise SsrfBlocked("URL에 호스트가 없습니다")

    if host.lower() in _allowed_hosts():
        return  # dev allowlist — 사설대역이라도 명시 허용

    try:
        # 호스트가 향하는 모든 IP를 resolve. 하나라도 사설이면 차단(rebinding 1차 방어).
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise SsrfBlocked(f"호스트를 resolve하지 못했습니다({type(exc).__name__})") from None

    seen = False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        seen = True
        if _ip_is_blocked(ip):
            raise SsrfBlocked(
                f"사설/내부 대역으로의 요청은 차단됩니다(host={host}). 개발용 mock 등 의도된 "
                f"대상이면 환경변수 A2A_ALLOWED_HOSTS에 이 호스트를 추가하세요"
                f"(쉼표구분, 예: A2A_ALLOWED_HOSTS={host}). 변경 후 API 재기동 필요."
            )
    if not seen:
        raise SsrfBlocked("호스트에서 유효한 IP를 얻지 못했습니다")


def mcp_http_client_factory(headers=None, timeout=None, auth=None):
    """MCP outbound HTTP 클라이언트 팩토리 — guard_url을 우회하는 **리다이렉트 추종을 끈다**.

    `guard_url`은 *최초* URL의 resolve IP만 검사한다. 기본 MCP 클라이언트는 follow_redirects=True
    (create_mcp_http_client "always enabled")라, 공인 호스트가 3xx로 사설/메타데이터(169.254.169.254)
    대역을 가리키면 가드를 우회할 뿐 아니라 **복호화된 Bearer 토큰까지 리다이렉트 타깃에 재전송**된다
    (적대 리뷰 H1 — a2a_client/agent_card가 이미 막아둔 것과 동일한 빈틈). 같은 정책
    (`follow_redirects=False`, agent_card.py:85 근거)으로 막는다 — 리다이렉트는 따르지 않고 프로토콜
    오류로 떨어뜨려 fail-closed. MCP 기본값(timeout 등)은 그대로 두고 추종 플래그만 끈다.
    """
    from mcp.shared._httpx_utils import create_mcp_http_client

    client = create_mcp_http_client(headers=headers, timeout=timeout, auth=auth)
    client.follow_redirects = False
    return client
