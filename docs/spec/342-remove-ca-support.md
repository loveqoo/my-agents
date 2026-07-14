# 342 — 사내 CA 지원(339·340) 제거: 안 쓰는 기능

## 배경 (사용자, 2026-07-14)

"최근 추가한 인증서 부분은 제거합시다. (안 쓰니까요)"

339·340은 회사 디바이스의 위키 503을 **인증서 문제로 가정**하고 만든 처방이었다. 실제 원인은
**SASE 게이트웨이의 UA 필터**였고, 341의 `WEB_FETCH_UA` 한 줄로 해소됐다(사용자 실측 "잘 됩니다").
CA 지원은 남아서 아무도 켜지 않는 기능(기본 꺼짐) — **죽은 영역**이다. 죽은 영역 원칙(스펙 329·338)
대로 닫힌 제거한다.

## 리스크와 그 처리 (정직)

341 실측 시 그 디바이스는 CA와 UA를 **둘 다 켠 채** 성공했다 → "CA 없이도 된다"는 아직 증명되지
않았다(341 결과의 미분리 경계). 이 제거가 곧 그 검증이다:

- 제거 → 디바이스에서 pull·재기동 → 위키 검색 **되면** CA는 애초에 불필요했던 것(가정 확정).
- 안 되면 이 커밋 하나를 revert(복원점 = git). 되돌림 비용이 낮으므로 미리 재현할 필요 없음.

## 제거 대상 (닫힌 집합 — 접점 열거)

| 대상 | 처리 |
|---|---|
| `packages/api/src/api/_ca_boot.py` | 삭제 |
| `main.py`의 `_ca_boot` 최선두 import | 제거 |
| `packages/api/pyproject.toml`의 `truststore>=0.10.4` + lock | 제거 |
| `tests/verify_339_truststore.py`·`verify_340_extra_ca.py` | 삭제 |
| `README.md` 회사망 절의 CA 2줄 | 제거(**UA 안내는 존치** — 341은 살아 있음) |
| `.env.example`의 SYSTEM_TRUSTSTORE·EXTRA_CA_FILE | 제거(WEB_FETCH_UA 존치) |
| `docs/spec/339·340` | 파일 존치 + **"제거됨(342)" 헤더 주석**(이력 — 338이 333·337에 한 방식) |
| `docs/spec/INDEX.md` 339·340 줄 | **removed** 표기 + 사유 |

## 회귀 위험 1곳 (반드시 실측)

`_ca_boot`이 `load_dotenv()`를 **api 형제 모듈 중 최선두**에서 부르고 있다(340 후속 수정). 지우면
`.env` 로딩이 `db.py`의 `load_dotenv()`로 넘어간다. `WEB_FETCH_UA`(341)는 **호출 시점 조회**라
그때면 이미 로드돼 있어야 정상 — verify_341 **V5(.env 파일만으로 적용)** 가 이 핀이다. 초록이면
안전, 빨강이면 `main.py`에 `load_dotenv()`를 명시적으로 올린다.

## 검증

1. verify_341 7/7(특히 V5) — `.env` 경로 무회귀.
2. grep 0: truststore·SYSTEM_TRUSTSTORE·EXTRA_CA_FILE·_ca_boot(스펙/회고 이력 문서 제외).
3. 앱 부팅 + 위키 검색 실호출(아웃바운드 HTTPS 무회귀 — 표준 CA 경로가 멀쩡한지).
4. lint/mypy 클린 + 201 web-fetch 무회귀.

## 결과 (2026-07-14 실행)

- 설계대로 닫힌 제거 — `_ca_boot.py`·verify_339·verify_340 삭제, `main.py` 최선두 import 제거,
  `truststore` 의존성+lock 제거, README·`.env.example`에서 CA 2줄 제거(**UA 안내는 존치**).
  스펙 339·340은 헤더에 "제거됨(342)" 주석 달아 이력 존치, INDEX는 **removed** 표기.
- **회귀 위험 1곳 초록**: `_ca_boot`이 갖고 있던 `load_dotenv()` 최선두 호출이 사라졌지만
  `db.py`의 `load_dotenv()`가 그 자리를 이어받아 `.env`가 그대로 로드됨 — **VERIFY341_OK 7/7**,
  특히 **V5(.env 파일만으로 `WEB_FETCH_UA` 적용)** 가 초록. `main.py`에 load_dotenv를 따로 올릴
  필요 없었다(추측 대신 핀으로 확인).
- 무회귀: 앱 부팅 정상(`Application startup complete`, /docs 200) · **201 web-fetch 15/15**
  (표준 CA 아웃바운드 HTTPS — `ssl.create_default_context` 원복 후에도 멀쩡) · lint/mypy 클린 ·
  잔재 grep 0(코드·설정·테스트).
- **디바이스 확정(2026-07-14)**: pull·재기동 후 위키 검색 **동작**(사용자 "잘 됩니다") → **CA는
  애초에 불필요했다**가 확정. 341의 미분리 경계가 닫혔다. 이 아크 전체 회고 → retrospect 315.
