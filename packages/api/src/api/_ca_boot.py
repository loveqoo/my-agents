"""사내 CA 신뢰 부트스트랩(스펙 339·340, 옵트인) — main이 **가장 먼저** import한다.

회사망 TLS 검사 환경에서 아웃바운드 HTTPS(위키 API 등)가 certifi 번들만 믿는 httpx에서 검증
실패한다. 서버는 http 그대로 — 아웃바운드 검증의 신뢰만 넓힌다. 이후 생성되는 ssl 컨텍스트에
적용돼야 하므로 다른 api 모듈 import 전에 실행되는 것이 계약. 기본 둘 다 꺼짐(사용자 결정).

- SYSTEM_TRUSTSTORE=1: OS 신뢰 저장소 사용(사내 CA가 OS에 설치된 경우 — pip 방식, 스펙 339).
- EXTRA_CA_FILE=/path/ca.pem: 지정 CA를 기존 번들에 **추가**(교체 아님 — 일반 사이트 무회귀).
  httpx·aiohttp가 쓰는 ssl.create_default_context를 감싼다(스펙 340).
"""

import logging
import os
import ssl
from pathlib import Path

from dotenv import load_dotenv

# .env를 여기서 먼저 로드(340 후속 수정) — 이 모듈은 main의 최선두 import라 db.py의 load_dotenv()
# **이전**에 env를 읽는다. 이 줄이 없으면 `.env`에만 적은 SYSTEM_TRUSTSTORE/EXTRA_CA_FILE이
# 조용히 무시된다(회사 디바이스 실측으로 발견 — 셸 env로만 검증한 내 구멍). load_dotenv는
# 멱등이고 기존 셸 env를 덮지 않는다.
load_dotenv()

logger = logging.getLogger("api.boot")

if os.environ.get("SYSTEM_TRUSTSTORE", "").lower() in ("1", "true"):
    import truststore

    truststore.inject_into_ssl()
    logger.info("OS 신뢰 저장소 사용(SYSTEM_TRUSTSTORE=1) — 사내 CA 지원")

_extra_ca = os.environ.get("EXTRA_CA_FILE", "").strip()
if _extra_ca:
    if not Path(_extra_ca).is_file():
        # 오타/미존재를 조용히 무시하면 "설정했는데 안 됨"이 침묵 — 부팅에서 크게 알린다.
        raise RuntimeError(f"EXTRA_CA_FILE 경로에 파일이 없습니다: {_extra_ca}")
    _orig_create_default_context = ssl.create_default_context

    def _create_ctx_with_extra_ca(*args: object, **kwargs: object) -> ssl.SSLContext:
        ctx = _orig_create_default_context(*args, **kwargs)  # type: ignore[arg-type]
        ctx.load_verify_locations(cafile=_extra_ca)  # 추가(load) — 기존 신뢰 유지
        return ctx

    ssl.create_default_context = _create_ctx_with_extra_ca  # type: ignore[assignment, unused-ignore]
    logger.info("아웃바운드 신뢰 CA 추가(EXTRA_CA_FILE=%s)", _extra_ca)
