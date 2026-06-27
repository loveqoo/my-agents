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
from urllib.parse import urlparse


class SsrfBlocked(ValueError):
    """가드가 outbound URL을 차단했다(사설대역·잘못된 스킴 등). ValueError 하위 → 라우터 4xx."""


def _allowed_hosts() -> set[str]:
    raw = os.environ.get("A2A_ALLOWED_HOSTS", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def _ip_is_blocked(ip: ipaddress._BaseAddress) -> bool:
    """공인(global) 대역이 아니면 차단. `not is_global`이 사설/루프백/링크로컬/예약/CGNAT
    (100.64/10)/문서·벤치마킹 대역까지 한 번에 거른다(개별 플래그 denylist의 누락 방지 — 적대리뷰 M1).
    멀티캐스트/미지정은 명시적으로도 막는다(방어적 중복)."""
    return (not ip.is_global) or ip.is_multicast or ip.is_unspecified


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
                "사설/내부 대역으로의 요청은 차단됩니다(A2A_ALLOWED_HOSTS로 허용 가능)"
            )
    if not seen:
        raise SsrfBlocked("호스트에서 유효한 IP를 얻지 못했습니다")
