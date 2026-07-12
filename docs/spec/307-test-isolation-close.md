# 307 — 테스트 격리 마감(stale verifier 정리 + 상태 격리)

## 배경
스펙 304(테스트 잔해 스윕) 후속. dev DB 오염은 스윕으로 막았지만, verify_*.py가 **공유 dev DB +
실행 중 dev 서버**에 의존해 격리 실행 시 red다. backlog가 "stale verifier"로 묶은 6건을 서버 띄우고
전수 진단(2026-07-12):

| verifier | 서버↑ 상태 | 실제 원인 |
|---|---|---|
| 100·101·103 | **PASS** | **인프라**(dev 서버·mock MCP·mock 임베딩 필요)였을 뿐 — stale 아님(오분류) |
| 036 | FAIL | **네이밍 드리프트**: `col_v036_`(밑줄) → 규칙 위반 400(스펙 148, `_` 금지) |
| 061 | FAIL | **구조 드리프트**: seam이 `_load_exposed_ui_agent`→`_load_exposed_agent`로 개명(patch 실효) |
| 056 | FAIL | **상태 드리프트**: 전역 `cleanup_sessions`를 dev DB 통째로 검사 → 세션 133개 전제 붕괴 |

## 처방

### 1. 036 — 네이밍 드리프트(자가정리 유지)
`CP="col_v036_"`·`MP="mdl_v036_"` → `col-v036-`·`mdl-v036-`(대시). 스펙 148 규칙 준수. LIKE 자가정리
(`{CP}%`)·삭제 로직 그대로. 스펙 302 verify_103 밑줄→대시와 동형.

### 2. 061 — seam 개명 추종(302 교훈: 실 lookup 지점을 패치)
`a2a_server._load_exposed_ui_agent = _fake_load` → `a2a_server._load_exposed_agent = _fake_load`
(현 `exposed_agent_card`/`exposed_agent_a2a`가 부르는 실 이름). 필요 시 `_agent_a2a_skills`·
`chat.stream_local_reply` seam도 실호출 지점으로 재지정(라이브 미필요 단위 성격 보존). FAKE_AGENT가
`_agent_a2a_skills`가 읽는 필드를 갖추도록 보강(DB 미접촉 유지).

### 3. 056 — 상태 격리
전역 cleanup을 통째 검사하므로 공유 dev DB 상태에 취약. **통제된 상태에서 검증**한다 — 둘 중 택:
(a) **소유 픽스처 스코핑**: 고유 prefix로 자기 세션을 심고, dry-run 결과에서 *그 세션들만* 필터해
    단언(전역 would_delete 총량 단언 제거), 끝나고 자가삭제(036 패턴). 라이트, 하네스 불요.
(b) **일회용 DB**: `tests/_throwaway_db.py`(smoke_303 일반화 — temp DB 생성·`init_db`+`seed_if_empty`·
    `api.db` 엔진 재바인딩·drop, 라이브 DB 가드)에서 virgin 상태로 실행.
→ **실측 후 결정**: 056 단언이 "truncation 형태 + 특정 세션 포함/제외"면 (a)로 충분(YAGNI, 하네스는
   과투자). "전역 총량·전수 삭제 규칙"이면 (b). 우선 (a) 시도, 불가 시 (b).

### 4. 100·101·103 — stale 아님(문서화)
서버 띄우면 PASS. 코드 수정 불요. 실행 전제(dev 서버 up)를 각 docstring/README에 명시(있으면 확인).

## OUT(스코프 밖)
- verify 149개 전수 일회용-DB 이관 — 앱이 `from .db import SessionLocal`을 import 시점 바인딩해
  전면 격리는 SessionLocal **DI 리팩터**가 선행(큰 별건). 이번은 3건 마감 + (필요 시) 재사용 하네스 씨앗.
- `make`에 verify 배치 타깃 추가(현재 verify_*는 게이트 밖 ad-hoc, suite가 실게이트).

## 검증
- **각 verifier green**: 036·061·056 exit=0(서버 띄운 상태). 100·101·103 PASS 재확인(무변경).
- **자가정리 무오염**: 036·056 실행 후 dev DB에 자기 prefix 잔여 0(측정).
- **드리프트 무재발**: 061은 seam 실호출 지점 패치라 실 함수 미실행(fake 반환 단언). metrics-fast 0.
- **적대**: 순수 테스트 수선(프로덕션 코드 무변경)이라 codex 트리거 약함 — 단, 056이 하네스(b)로 가면
  라이브 DB 가드·drop 누락을 codex로 점검(smoke_303 가드 재사용).
