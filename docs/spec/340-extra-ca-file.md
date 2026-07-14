# 340 — 사내 CA 파일 방식(EXTRA_CA_FILE) — 339 확장

## 배경 / 요구 (사용자, 2026-07-14)

"인증서 경로 방식이 필요합니다. 그 디바이스의 로컬에서만 쓸 것" — 339(OS 신뢰 저장소)에 이어,
사내 CA가 **파일로만** 있는 환경용. 사용자 정정 반영: **서버는 http 그대로** — 바뀌는 건
서버가 밖으로 나가는 **아웃바운드 HTTPS 검증의 신뢰**뿐(서버 TLS 아님).

## 설계

- env `EXTRA_CA_FILE=/path/corp-ca.pem`(기본 꺼짐, 디바이스 로컬 .env) — 지정 CA를 기존
  번들(certifi 등)에 **추가**(SSL_CERT_FILE류 "교체"가 아님 — 일반 사이트 무회귀).
- `api/_ca_boot.py` 신설(339의 truststore 게이트도 이관) — httpx·aiohttp가 쓰는
  `ssl.create_default_context`를 감싸 이후 생성되는 모든 컨텍스트에 적용. main.py의 api 형제
  모듈 import 중 **가장 먼저**(_는 알파벳 앞 — 컨텍스트 생성 전 주입 계약).
- 오타/미존재 경로는 부팅 실패(RuntimeError) — "설정했는데 안 됨" 침묵 방지.

## 검증 — 사내 MITM을 로컬로 실재현

VERIFY340_OK 5/5: V1 기본 꺼짐(표준 create_default_context) · V2 오타 경로=부팅 실패 ·
**V3 재현**(자가서명 CA의 TLS 대역 사이트 GET → CERTIFICATE_VERIFY_FAILED — 회사 디바이스 현
증상) · **V4 처방**(EXTRA_CA_FILE=그 CA → 같은 GET 성공) · V5 무회귀(켠 채 위키 TLS 관통 —
403은 위키 UA 정책·앱 계층이라 TLS 성공의 증거). 339 무회귀(VERIFY339_OK 3/3)·lint/mypy 클린.

## OUT

- 회사 디바이스 최종 실측(사용자: 그 디바이스 .env에 EXTRA_CA_FILE 지정 후 위키 검색) ·
  EXTRA_CA_DIR(디렉토리 방식 — 필요 실증 시).

## 후속 수정 (2026-07-14, 회사 디바이스 실측이 발굴)

- **버그**: `_ca_boot`이 main 최선두 import라 db.py의 `load_dotenv()`보다 먼저 env를 읽어 —
  `.env`에만 적은 SYSTEM_TRUSTSTORE/EXTRA_CA_FILE이 조용히 무시됐다. 내 검증(V1~V5)이 전부
  **셸 env로 주입**해서 못 본 구멍(문서는 ".env에 적으라"고 안내했으면서). `_ca_boot`이
  load_dotenv()를 직접 선행하도록 수정 + V6(".env 파일만으로 적용") 회귀 핀.
- 진단 부기: 사용자 "브라우저에서는 잘 동작" = 사내 CA가 OS 저장소에 있음 → 그 디바이스는
  `SYSTEM_TRUSTSTORE=1`이 최단 경로. 503은 우리 코드에 없는 코드(a2a 제외) — 수정 후에도 503이면
  TLS는 통과했고 사내 프록시 응답일 가능성(HTTPS_PROXY를 .env에 — httpx가 읽음).
