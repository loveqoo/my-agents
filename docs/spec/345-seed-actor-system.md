# 345 — 마이그레이션 시드 행의 감사 actor를 `system`으로(처녀 DB `unknown` 0)

## 발견 (데이터 초기화, 2026-07-14)

사용자 요청으로 DB를 전량 초기화(드롭→재생성→마이그레이션 44건→시드)한 뒤 실측하니:

| 출처 | 예 | `created_by` | 맞나 |
|---|---|---|---|
| 앱 시드(`seed_if_empty`, ORM) | agents 5 · personas 2 · collections 3 · mcp 3 | `system` | ✅ |
| **마이그레이션 시드**(raw INSERT) | **providers 1 · models 2**(Mock LLM·mock-llm·mock-embed) | **`unknown`** | ❌ |

`unknown`의 뜻은 스펙 343에서 **"감사 도입 이전에 만들어진 행"**이다. 그런데 **갓 만든 DB**에
그 값이 찍힌다 — 감사 이력이 첫 부팅부터 거짓말을 한다.

**근인**: `providers`/`models` 시드는 앱이 아니라 **마이그레이션**이 raw SQL로 넣는다
(`a1b2c3d4e5f6`·`c9d0e1f2a3b4`·`f4a5b6c7d8e9`). 이들은 343(`a7f3c9e21b4d`)보다 **먼저** 돌아
감사 컬럼이 아직 없고, 뒤이어 343의 백필이 그 행들을 `unknown`으로 채운다. 앱 시드는 343 이후
(부팅 시점)에 ORM으로 들어가므로 `system`이 정상 부여된다 — 두 경로의 결과가 갈렸다.

(343의 백필 자체는 옳다 — "그 시점에 이미 있던 행의 주체는 알 수 없다". 문제는 **마이그레이션이
만든 행의 주체는 알 수 있다**는 것: `system`이다.)

## 설계

343 이후 새 리비전에서, **마이그레이션이 심은 시드 행에 한정해** `unknown` → `system`으로 정정한다.

- 대상은 **정확히 지목**한다(seed 행의 식별자로 매칭): provider `Mock LLM`(kind=mock) ·
  models `mock-llm`(model_id=mock-chat) · `mock-embed`(model_id=mock-embed).
- **일괄 `unknown`→`system`은 금지**. 다른 환경(회사 디바이스 등)의 `unknown`에는 **진짜 레거시
  행**(343 이전에 관리자가 만든 provider/모델)이 섞여 있고, 그걸 `system`으로 바꾸면 "사람이 만든
  것을 시스템이 만들었다"고 거짓말하게 된다. 알 수 있는 것만 정정한다.
- 재발 방지: **343 이후의 데이터 시드 마이그레이션은 감사 컬럼을 명시로 채운다**(컬럼이 이미 있음).
  이를 상주 스캔으로 핀(아래 검증 3).

## 검증 (완료 조건 = 측정 가능)

1. **처녀 DB `unknown` 0건**: throwaway DB(마이그레이션+시드)에서 우리 소유 27테이블을 전수 질의해
   `created_by='unknown' or updated_by='unknown'` 행이 **0**. (이 스펙의 완료 조건 — 자가선언 아님.)
2. 시드 행이 `system`: provider/models 3행의 `created_by='system'`.
3. **재발 방지 스캔**: 343 이후 리비전 파일에 `INSERT INTO`가 있으면 같은 문장에 `created_by`가
   있어야 한다(없으면 실패) — 다음 데이터 마이그레이션이 같은 함정에 빠지지 않게.
4. 무회귀: verify_343(16) · verify_343_downgrade(4) · 게이트.

## 결과 (2026-07-14 실행)

- 마이그레이션 `b8e4d2c7a915` — 시드 행만 정확히 지목해 `unknown` → `system`.
- **완료 조건 수치가 내 처방의 누락을 잡았다**: 처음엔 providers/models만 고쳤는데, S1(처녀 DB
  unknown 0건)이 **allowed_hosts 2 · memory_types 2**를 더 뱉었다 — 그것도 마이그레이션 시드였다.
  "고쳤다"고 선언했으면 절반만 고친 채 끝났을 것(자가선언 대신 측정).
- 검증: **VERIFY345_OK 4/4**(처녀 DB unknown **0** · 마이그레이션 시드 3행 system · 앱 시드 system ·
  343 이후 INSERT는 감사 컬럼 명시 스캔). 무회귀: 343(16/16)·343 왕복(4/4)·344(12/12)·lint/mypy 클린.
- 데이터 초기화 실측(2026-07-14): 드롭→재생성→마이그레이션 44건→시드. 결과 = agents 5 · personas 2 ·
  collections 3 · mcp 3 · providers 1 · models 2 · **sessions 0 · messages 0 · checkpoints 0** ·
  user 1(admin 재시드). 삭제 전: 세션 183 · 메시지 520 · 체크포인트 10,191 · 문서 8 · 청크 17.
- 부수 수리: postgres 이미지의 **collation 버전 불일치**로 `CREATE DATABASE`가 막혀 있었다
  (template1이 2.41로 생성됐는데 OS는 2.36). `ALTER DATABASE template1 REFRESH COLLATION VERSION`
  으로 해소 — 이 경고는 이전부터 psql 출력에 떠 있었고, DB 재생성 때 처음 **차단**으로 드러났다.

## OUT

- 레거시 DB의 `unknown` 정리(구분 불가 — 위 설계 참조) · 시드를 마이그레이션에서 앱으로 이관
  (별 스펙 규모: 부팅 순서·자가복구 경로 재설계).
