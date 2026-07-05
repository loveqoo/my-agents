# 158 — 멤버 자율 평가(소유 기반) + codex 적대 검증 하드닝

**스펙**: docs/spec/178-member-self-serve-eval.md · **관련**: 회고 157(권한 정리 P3), learning 069·070(소유권 입구)

## 무엇을 했나
평가(eval)를 admin 전용 `require("eval",*)`에서 **소유 기반 멤버 자율**로 열었다(컬렉션 패턴 = 읽기
공개·관리 소유자). `ownership.py` 술어 이식(assert_may_manage 404-fold, may_use_agent 구멍#1), 비용
가드, `can_manage` UI 게이트. P1~P3 후 **codex challenge**로 적대 검증 → 비용 경계 결함 4건을 봉합(P4).

## 무엇이 잘못됐고 무엇을 배웠나

### 1. 비용 가드를 "메인 액션"에만 걸고 형제 LLM 입구를 놓쳤다 (핵심)
P2에서 나는 **`start_run`(실행)** 하나에만 동시성·작업량 상한을 걸었다. happy-path 소유권 테스트는
전부 초록. 그런데 codex가 즉시 짚었다: **`generate-dataset`(컬렉션→문제집 자동 생성)과
`suggest-cases`(AI 출제)도 배경 LLM을 태우는 입구인데 무가드**였다. 멤버가 이름만 바꿔 반복 POST하면
배경 생성 job이 무한 누적된다.

- **표본**: `_MEMBER_MAX_*` 상한이 `start_run`에만. generate/suggest는 per-call count(≤20/≤10)만 있고
  **동시/누적 상한 없음** → flood로 우회. `_active_jobs` 락은 새 dataset마다 키가 달라 flood를 못 막음.
- **왜 못 봤나**: "비용 가드"를 *실행*이라는 한 개념으로 좁게 잡았다. 같은 리소스(LLM 예산)를 태우는
  입구가 3개인데 1개만 셌다 — 소유권 체크리스트의 "입구 열거(닫힌 집합)"를 **인가**엔 적용했으면서
  **비용**엔 안 했다.
- **처방**: 비용도 인가처럼 **입구를 닫힌 집합으로 열거**하고, 같은 예산을 태우는 입구는 **단일 진실원**
  으로 합산 상한. `_active_jobs`를 생성·출제 공용 카운터로 통일하고 `_member_job_guard`가 소유자별 합산.
  자원 게이트를 설계할 땐 "이 자원을 소비하는 모든 경로"를 먼저 세라(하나만 막으면 나머지로 샌다).

### 2. 락을 배경 태스크 안에서 잡으면 TOCTOU가 열린다
`suggest-cases`는 `if dataset_id in _active_jobs: 409`로 중복을 막는 듯 보였지만, 정작 `.add`는
**배경 태스크(`_execute_suggestion`) 안**에 있었다. 요청 핸들러의 체크와 배경의 add 사이가 벌어져,
동시 요청 둘이 모두 체크를 통과하고 중복 출제 태스크를 만든다.
- **처방**: 락은 **판정과 같은 동기 구간**에서 잡아라(체크와 add 사이에 `await` 금지 — 단일 이벤트루프
  에선 그 구간이 원자). 배경 태스크로 미루면 "락"이 락이 아니다. 실패 시 create_task 전엔 배경 finally가
  안 도니 **except에서 해제**. [[gate-on-intent-value-not-mutable-baseline]]와 같은 결: 판정→실행을 원자로.

### 3. check-then-insert 레이트리밋은 DB 직렬화 없이는 TOCTOU
`start_run`의 `my_running < 2` 확인과 insert 사이에 락이 없어, 서로 다른 dataset로 병렬 요청하면 모두
상한을 보고 통과 → 초과 실행. **`pg_advisory_xact_lock(유저키)`**로 유저별 확인+삽입을 직렬화해 봉합.
단위 테스트로 race 자체는 못 잡지만(happy-path는 순차), advisory 락이 구조적으로 닫는다.

### 4. 가드의 *이름*이 실제 비용과 어긋나면 상한이 거짓말
work=`cases × models`로 셌는데, 케이스당 `llm_judge` 최대 5개가 실 LLM 호출을 배증한다 → 상한 60이
실제 최대 360 호출을 허용. **work=`models × (cases + llm_judge 기준 수)`**로 정직화(harness와 동일 카운트).

## 복리 포인트
- **codex 적대 검증이 내 테스트의 여집합을 잡았다.** 내 24개 체크는 *인가*(소유 격리)만 촘촘했고
  *비용 경계*는 얕았다. "보장 목록의 여집합"을 타자에게 시키니 내가 안 본 축(형제 입구·TOCTOU·judge)이
  나왔다. [[adversarial-review-before-destructive-ship]]·[[use-codex-for-adversarial-verification]] 재확인.
- **의도된 경계는 고치지 말고 문서화.** codex가 짚은 ⑥RAG 컬렉션 사용권·⑦obs 공개는 "정책상 공개"라
  코드결함이 아니다 — 스펙에 by-design으로 명시(주석+안내 UI). [[complement-attack-can-be-honest-boundary]].
