"""파괴 잡 순수 가드 — jobs.py에서 분할(스펙 395 P1, 순수 이동).

전체-삭제 패턴 판정·A2A 사설망 판정·유저 keep-list·최후 superuser 보호. 전부 순수 함수 —
batch_routes(API 검증기)와 잡 바닥이 같은 함수를 공유해 드리프트를 막는다(스펙 050).
파사드는 jobs.py(재수출 계약).
"""

import ipaddress
from urllib.parse import urlsplit

# user-cleanup의 하드코딩 keep-list — 패턴에 일치해도 절대 삭제 안 함. 부트스트랩 어드민(잠금 방지)과
# 데모 유저(시드 자산). 패턴이 넓게 잡혀도 이 둘은 바닥이 막는다.
_USER_CLEANUP_KEEP = frozenset({"admin@example.com", "alice@example.com"})

# a2a-cleanup이 "사설"로 간주하는 *정확한* 네트워크 — 스펙 050이 열거한 집합만(루프백+RFC1918).
# ipaddress.is_private는 0.0.0.0/8·169.254/16·198.18/15 등 라우팅 가능한 예약대역까지 포함하는
# 상위집합이라, 그 대역에 실 A2A 파트너가 있으면 오삭제한다(적대리뷰 #3). 그래서 명시 멤버십으로 좁힌다.
_A2A_PRIVATE_NETS = tuple(
    ipaddress.ip_network(n)
    for n in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128")
)


def _is_private_host(endpoint: str | None) -> bool:
    """endpoint의 호스트가 루프백/RFC1918 사설이면 True(=테스트 프로브). 공개 호스트면 False.

    실 A2A 파트너는 공개 endpoint라 절대 안 걸린다. scheme 유무 모두 허용(127.0.0.1:8142,
    http://10.0.0.5:9999 등). localhost는 루프백, IP는 _A2A_PRIVATE_NETS 명시 멤버십으로만 판정한다
    (is_private 상위집합 회피, 적대리뷰 #3). IPv4-mapped IPv6(::ffff:10.0.0.1)는 v4로 언랩 후 판정.
    파싱 불가·호스트 없음·도메인(공개 추정)은 False(보수적 — 못 지우는 쪽이 안전)."""
    if not endpoint:
        return False
    raw = endpoint.strip()
    # scheme 없으면 urlsplit이 netloc을 못 잡으므로 // 프리픽스를 붙여 강제 파싱.
    parsed = urlsplit(raw if "//" in raw else f"//{raw}")
    host = parsed.hostname  # 포트·인증정보·대괄호 IPv6 제거된 순수 호스트
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # 도메인명 → 공개 추정, 안 건드림
    mapped = getattr(ip, "ipv4_mapped", None)  # ::ffff:10.0.0.1 → 10.0.0.1로 언랩
    if mapped is not None:
        ip = mapped
    return any(ip in net for net in _A2A_PRIVATE_NETS)


def is_delete_all_pattern(pattern: str | None) -> bool:
    """user-cleanup LIKE 패턴이 전체/광범위 유저 삭제 위험인지 판정 — 와일드카드(`%`·`_`)를 제거한
    '리터럴 골격'으로 본다. `%`·`%a%`·`%@%`처럼 리터럴이 약하면 거의 전체를 매치하므로 거부한다.

    바닥(적대리뷰 #1): 리터럴에 `@`(도메인 셀렉터)가 없거나 리터럴 본문이 5자 미만이면 위험으로 본다.
    정상 셀렉터(`verify%@example.com`·`%@test.example.com`)는 통과한다. NULL/빈은 여기서 안 다룬다
    (호출 측이 disabled로 처리). 검증기(batch_routes)와 잡 바닥이 같은 함수를 공유해 드리프트를 막는다."""
    literal = (pattern or "").replace("%", "").replace("_", "").strip()
    return ("@" not in literal) or (len(literal) < 5)


def _survives_keep_list(email: str | None) -> bool:
    """keep-list(바닥 2) 밖이면 True — 패턴 일치해도 keep-list는 제외. 공백·대소문자 차이로 보호가
    새지 않게 strip().lower() 양변 정규화(적대리뷰 #8 — 저장 이메일에 끝 공백/대문자가 있어도
    부트스트랩 admin 보호)."""
    return (email or "").strip().lower() not in _USER_CLEANUP_KEEP


def _protect_last_supers(candidates: list, total_supers: int) -> tuple[list, list[str]]:
    """바닥 3 — 마지막 super 보호. 매치 super를 다 지우면 시스템 super가 0이 되는지 확인하고,
    되면 매치 super 전부 보존(누가 마지막인지 고르지 않고 보수적으로 전부 남김 = 잠금 0 보장).
    (남길 candidates, 보호된 super 이메일 목록)을 반환."""
    matched_supers = [r for r in candidates if r[2]]
    if matched_supers and total_supers - len(matched_supers) <= 0:
        protected = {r[0] for r in matched_supers}
        protected_emails = [r[1] for r in matched_supers]
        return [r for r in candidates if r[0] not in protected], protected_emails
    return candidates, []
