# 339 — 사내 CA 지원: OS 신뢰 저장소 옵트인(SYSTEM_TRUSTSTORE)

> **제거됨(스펙 342, 2026-07-14)** — 실제 원인은 인증서가 아니라 SASE 게이트웨이 UA 필터였고(스펙 341로 해소), 이 기능은 아무도 켜지 않아 죽은 영역이 됐다. 코드·의존성·테스트는 제거, 이 문서는 이력으로 존치.

## 배경 / 요구 (사용자, 2026-07-14)

"다른 디바이스는 인증서가 있어야 외부 인터넷이 됩니다 — 위키 검색이 안 돼요." 회사망 TLS
검사(사내 CA)로 아웃바운드 HTTPS(위키 API 등)가 인증서 검증 실패. 아웃바운드 httpx 지점 11곳 —
지점별 수정 대신 프로세스 전역 처방. **사용자 결정: 기본 꺼짐 + env(SYSTEM_TRUSTSTORE=1)로 켬**.

## 설계

- `truststore` 의존성(pip가 채택한 방식) — `inject_into_ssl()`이 ssl.SSLContext를 OS 신뢰
  저장소 기반으로 교체 → 이후 생성되는 모든 httpx/requests 컨텍스트가 사내 CA(OS에 설치됨)를
  신뢰. 표준 CA도 OS 저장소에 있으므로 일반 사이트 무회귀.
- 주입 지점: `api/main.py` **모듈 최상단**(다른 api 모듈 import 전) — 컨텍스트가 만들어지기 전에
  패치돼야 전역 적용. 게이트: `SYSTEM_TRUSTSTORE=1|true`일 때만(기본 꺼짐 — 사용자 결정).
- 프록시(HTTP(S)_PROXY)는 httpx가 기본으로 env를 읽으므로(trust_env) 별도 작업 없음.
- README에 회사 디바이스 설정 안내 1절.

## 검증

1. verify_339: V1 기본 꺼짐(서브프로세스 — env 없이 import 후 ssl.SSLContext=표준) ·
   V2 켬(env=1 → truststore.SSLContext) · V3 켠 상태 외부 TLS 실동작(wiki_search 실호출 —
   표준 CA 환경 무회귀 실증).
2. **정직 경계**: 사내 MITM 재현은 이 맥에서 불가 — "OS 저장소의 CA를 신뢰"는 truststore
   라이브러리 계약이고, 우리 검증은 주입 성사+무회귀까지. 실검증은 회사 디바이스에서
   `SYSTEM_TRUSTSTORE=1` 설정 후 위키 검색(사용자 실측 대기).

## OUT

- 인증서 파일 경로 방식(EXTRA_CA_FILE — OS 저장소 미설치 환경용, 필요 실증 시) ·
  배치 서비스 프로세스 적용(별 프로세스 — 같은 env 게이트를 그쪽 진입점에도, 필요 시).

## 결과 (2026-07-14 실행)

- 설계대로 — truststore 의존성+main.py 최상단 옵트인 주입(SYSTEM_TRUSTSTORE=1|true), README·
  .env.example 안내.
- 검증: VERIFY339_OK 3/3 — 기본 꺼짐(표준 SSLContext)·켬(truststore 주입 성사)·**켠 상태 위키
  TLS 실동작**(OS 저장소로 표준 CA 사이트 검증 무회귀). lint/mypy 클린.
- codex 생략 사유: 3줄 옵트인 게이트(기본 꺼짐=무영향)+라이브러리 위임 — 적대 표면이 env 게이트
  하나(V1이 핀).
- **사용자 실측 대기**: 회사 디바이스에서 `.env`에 SYSTEM_TRUSTSTORE=1 추가 후 재기동 → 위키
  검색 동작 확인(사내 MITM 재현은 이 맥에서 불가 — 정직 경계).
