"""서버측 outbound URL 가드 (SSRF 방어, 스펙 042).

서버가 관리자/카드가 준 URL로 직접 요청을 보내는 경로(A2A 런타임 호출, Agent Card fetch)는
SSRF 표면이다 — 사설/루프백/링크로컬/메타데이터(169.254.169.254) 대역으로 향하는 요청은
내부 서비스·클라우드 메타데이터를 노출시킬 수 있다.

정책(스펙 042 합의): 호스트를 IP로 resolve해 사설대역이면 **차단**(기본). 단 호스트가
allowlist에 있으면 통과 → dev mock(127.0.0.1) 동작.

allowlist 소스(스펙 064): **DB `allowed_hosts` 테이블이 진실원**. `guard_url`은 sync 시그니처를
유지하려고 모듈 캐시 스냅샷(`_ALLOWED_SNAPSHOT`)만 sync로 읽고, async 호출처가 `guard_url` 직전에
`await refresh_allowed_hosts()`로 DB→스냅샷을 짧은 TTL(기본 10s)로 새로고친다 → **무재시작 반영**.
env(`ALLOWED_HOSTS`, 구 `A2A_ALLOWED_HOSTS` 폴백)는 첫 부팅 1회 시드 소스일 뿐(alembic 마이그레이션이
임포트), 런타임은 DB만 본다(learning 012 — env는 부트스트랩, DB가 단일 레지스트리).

알려진 한계(스펙 042 §7 빚): resolve→connect 사이 DNS 재바인딩(TOCTOU). 진짜 차단은 resolved
IP 핀(커스텀 transport)이 필요하나, 관리자 등록 경계라 resolve-and-check까지를 현실적 바로 둔다.
"""

import ipaddress
import math
import os
import socket
import time
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
    # 보안 하드닝(스펙 063, codex 적대 [P1]): userinfo('user:pass@') 금지.
    # `"://"`만으로 비-http 스킴을 거르면 colon-form URI가 새어나간다 —
    # `mailto:user@example.com/a2a` 는 위 else 분기로 `http://mailto:user@example.com/a2a`
    # 가 되고, urlparse/httpx 모두 host를 공인 `example.com`(userinfo=`mailto:user`)로 본다.
    # 그러면 예전에 guard_url이 비-http 스킴으로 거부하던 값이 가드를 통과해 Bearer 토큰 포함
    # A2A 요청이 공인 호스트로 새어나간다(SSRF·자격증명 누출). A2A 엔드포인트는 임베디드
    # 자격증명을 쓰지 않으므로(인증=별도 token 필드) '@'는 정상 입력에 없다 → 거부가 안전.
    # 잘못된 포트(비숫자)도 여기서 fail-closed(접근 시 ValueError).
    try:
        parsed.port  # 비숫자 포트(예: 'mailto:example.com'→host=mailto)면 접근 시 ValueError
        _bad_port = False
    except ValueError:
        _bad_port = True
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or _bad_port
    ):
        raise ValueError(
            f"서비스 url을 절대 http(s) URL로 해석할 수 없습니다(받은 값: '{s[:80]}'). "
            "카드의 url을 'http://host:port/path' 형태로 지정하세요(자격증명 '@'·비숫자 포트 불가)."
        )
    return candidate


def normalize_allowed_host(raw: str) -> str:
    """allowlist 항목을 **정확 host**로 정규화(스펙 064 §3·learning 037 파괴적 노브 바닥). 위반은 ValueError.

    허용: 호스트명 또는 IP 리터럴(IPv4/IPv6 — canonical로 반환). 거부: 빈값·공백 포함·스킴(`://`)·
    `*`(와일드카드)·`/`(경로·CIDR)·`,`(다중 항목 우회)·`@`(userinfo 둔갑, learning 066)·포트(`host:port`).
    guard_url은 `host.lower() in set`로 *정확* 매칭하므로 와일드카드/서브넷은 무력하거나 allow-all로
    둔갑할 위험 → 도입 안 함. 반환값은 guard_url이 보는 `parsed.hostname.lower()`와 동형(IPv6는 무대괄호
    bare form, IP는 ipaddress canonical)이라 저장↔매칭이 어긋나지 않는다.
    """
    s = (raw or "").strip().lower()
    if not s:
        raise ValueError("호스트가 비어 있습니다")
    if any(c.isspace() for c in s):
        raise ValueError(f"호스트에 공백을 포함할 수 없습니다: {s!r}")
    # 길이 캡: DNS 호스트명 최대 253. DB 컬럼은 String(255)라, 캡 없으면 과길이 입력이
    # add_host에서 DataError→500을 낸다(적대리뷰 P2). 정규화 단계에서 422로 막는다.
    if len(s) > 253:
        raise ValueError(f"호스트가 너무 깁니다(>253자): {raw!r}")
    # IPv6 리터럴 입력 편의: '[::1]' → '::1'(guard_url의 parsed.hostname과 동형).
    bare = s[1:-1] if s.startswith("[") and s.endswith("]") else s
    try:  # IP 리터럴이면 canonical form으로 수용(127.0.0.1·::1 등 — 포트의 ':'와 혼동 방지).
        ip = ipaddress.ip_address(bare)
    except ValueError:
        ip = None
    if ip is not None:
        # 미지정 주소(0.0.0.0·::)는 단일 아웃바운드 타깃이 아니라 와일드카드 바인드 주소다.
        # allowlist에 들면 guard_url이 _ip_is_blocked 전에 host 정확매칭으로 통과시켜 로컬
        # 리스너를 노출한다(적대리뷰 P1 — allow-local 둔갑). 정규화 단계에서 거부한다.
        if ip.is_unspecified:
            raise ValueError(f"미지정 주소(0.0.0.0/::)는 허용 호스트가 될 수 없습니다: {raw!r}")
        return str(ip)
    # 호스트명 경로 — 둔갑/우회 벡터를 fail-closed로 거부.
    for bad, why in (
        ("://", "스킴"),
        ("*", "와일드카드"),
        ("/", "경로·CIDR"),
        (",", "다중 항목"),
        ("@", "자격증명(userinfo)"),
        (":", "포트"),
    ):
        if bad in bare:
            raise ValueError(f"호스트에 {why}({bad!r})를 포함할 수 없습니다: {raw!r}")
    if not all(c.isalnum() or c in ".-" for c in bare):
        raise ValueError(f"호스트에 허용되지 않는 문자가 있습니다: {raw!r}")
    return bare


# ── allowlist 캐시 스냅샷(스펙 064 D3) ──────────────────────────────────────────
# guard_url은 sync라 DB를 직접 못 친다. async 호출처가 guard_url 직전에 refresh_allowed_hosts()로
# DB→스냅샷을 새로고치고, guard_url은 스냅샷만 sync로 읽는다. 콜드 스타트 스냅샷은 빈 집합 =
# fail-closed(아무 사설 host도 안 열림 — 안전한 기본). monotonic TTL로 DB 부하를 디바운스.
_ALLOWED_SNAPSHOT: set[str] = set()
_SNAPSHOT_EXPIRES: float = 0.0


def _parse_ttl(raw: str | None) -> float:
    """`ALLOWED_HOSTS_TTL` 안전 파싱 — 잘못된 값이 부팅을 깨거나 수렴을 막지 못하게 [0,300] 클램프.

    직파싱(`float(env)`)은 오타에 ValueError로 import 크래시, `inf`엔 제거(닫는 변경)가 *영원히*
    반영 안 됨(적대리뷰 P2). 비유한/음수/과도값을 기본 10s 또는 상한 300s로 정규화한다.
    """
    try:
        v = float(raw) if raw is not None else 10.0
    except (TypeError, ValueError):
        return 10.0
    if not math.isfinite(v) or v < 0:
        return 10.0
    return min(v, 300.0)


_TTL_SECONDS: float = _parse_ttl(os.environ.get("ALLOWED_HOSTS_TTL"))


def _allowed_hosts() -> set[str]:
    return _ALLOWED_SNAPSHOT


async def refresh_allowed_hosts(force: bool = False) -> None:
    """DB `allowed_hosts`를 읽어 모듈 스냅샷을 교체(무재시작 반영). 만료 전이면 no-op(디바운스).

    `guard_url`을 호출하는 모든 async 아웃바운드 경로가 *직전*에 await한다(스펙 064 D3 배선). 동시
    다중 호출은 멱등 교체라 무해. 순환 import를 피하려고 db/models를 함수 안에서 지연 import한다.
    DB 일시 장애 시엔 **기존 스냅샷을 유지**(닫힌 변경만 늦게 반영 — host를 새로 열지 않으니 안전)하고
    만료만 짧게 미뤄 다음 요청에서 재시도한다.
    """
    global _ALLOWED_SNAPSHOT, _SNAPSHOT_EXPIRES
    now = time.monotonic()
    if not force and now < _SNAPSHOT_EXPIRES:
        return
    from sqlalchemy import select

    from . import db
    from .models import AllowedHost

    try:
        async with db.SessionLocal() as session:
            rows = (await session.execute(select(AllowedHost.host))).scalars().all()
    except Exception:  # noqa: BLE001 — DB 블립: 기존 스냅샷 유지(fail-safe), 짧게 재시도.
        _SNAPSHOT_EXPIRES = now + 1.0
        return
    _ALLOWED_SNAPSHOT = {h for h in rows if h}
    _SNAPSHOT_EXPIRES = now + _TTL_SECONDS


def invalidate_allowed_hosts_cache() -> None:
    """관리자 변경(추가/삭제) 후 그 워커 캐시를 즉시 만료 — 다음 refresh가 DB를 재조회한다(스펙 064 D5).

    다른 워커는 TTL(≤10s) 내 수렴. host **제거**가 TTL 동안 아직 허용될 수 있는 창은 스펙 064 §3에
    명시된 허용 staleness(닫는 변경의 지연 반영)다.
    """
    global _SNAPSHOT_EXPIRES
    _SNAPSHOT_EXPIRES = 0.0


def _set_allowed_hosts_for_test(hosts) -> None:
    """**테스트 전용** — DB 없이 스냅샷을 직접 고정한다(런타임 코드는 절대 호출하지 않는다).

    스펙 064에서 allowlist 소스가 env→DB로 바뀌어, DB 없는 단위 테스트는 더는 `os.environ`으로
    allowlist를 주입할 수 없다(런타임이 env를 안 본다 = 우회 방지). 그 자리를 메우는 결정적 시seam.
    `normalize_allowed_host`를 거쳐 guard_url 매칭과 동형으로 넣고, 만료를 무한대로 둬 refresh가
    덮어쓰지 않게 한다.
    """
    global _ALLOWED_SNAPSHOT, _SNAPSHOT_EXPIRES
    snap: set[str] = set()
    for h in hosts:
        try:
            snap.add(normalize_allowed_host(h))
        except ValueError:
            continue
    _ALLOWED_SNAPSHOT = snap
    _SNAPSHOT_EXPIRES = float("inf")


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

    allowlist(DB `allowed_hosts`, net_guard 캐시 스냅샷)에 든 호스트는 사설대역이라도 통과(dev mock).
    호출처는 *직전*에 `await refresh_allowed_hosts()`로 스냅샷을 최신화해야 무재시작 반영된다(스펙 064).
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
                f"대상이면 관리 콘솔의 '허용 호스트'에서 이 호스트({host})를 추가하세요"
                f"(무재시작, 최대 ~10초 내 반영)."
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
