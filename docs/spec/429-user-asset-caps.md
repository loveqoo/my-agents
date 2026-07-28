# 스펙 429 — 살아있는 유저 자산 상한(기억·메시지)

## 문제

자원 회수 캠페인(스펙 346~352)은 **유령·만료만** 지우고 **살아있는 유저 기억·메시지는 일부러 보존**
했다(토대 기능). 그래서 이 둘은 **상한이 없어 무한 증가**한다 — 스코어보드 0("분류가 정직")이지
"성장이 유계"라는 뜻은 아니다(백로그 스펙 346~352 OUT ①).

- **유저 기억(mem0)**: 상한 메커니즘 자체가 없음. `memory.add()`가 유일 관문인데 개수 체크 0.
- **메시지(세션)**: 나이 기반 보존(`session_retention_days`, session-cleanup 배치)이 **있으나 기본 OFF**(NULL).

## 결정 (구남님 승인 — 제품 가시 한계)

- **기억 상한 = 유저당 1000개**, 넘으면 **오래된 것부터 축출**(최근 보존).
- **메시지 보존 = 180일**, **기본 ON**. `last_activity`가 180일 지난 세션 회수(메시지 cascade).
- 축출/회수는 둘 다 **오래된 것부터**, 파괴적 노브 바닥(값<1=비활성) 가드.

## 구현

### A. 유저 기억 상한 — `memory.add()` 관문 축출([[policy-at-the-chokepoint]])
- `MEMORY_CAP_PER_USER = 1000`(제품 승인 상수).
- `memory/__init__.py add()`: backend.add 후, **scope에 user_id가 있으면** 그 유저 기억 수를 세고
  `> 1000`이면 **오래된 것부터 (count-1000)개 삭제**. 오래된 것 획득 = `list_page(user_scope,
  offset=1000)`(최신순이라 1001위치부터가 가장 오래된 것) → 각 delete.
- user_id 없는 add(run/agent-only 세션 기억)는 미적용 — 세션 축은 B가 담당(축 분리).
- 관문 단일: add() 하나가 자동저장(314)·기억쓰기 브로커(105)·POST /memory 세 입구를 다 덮음.

### B. 메시지 보존 180일 기본 ON — 기존 session-cleanup 활성화
- `models/batch.py` BatchConfig 기본값: `session_retention_days` None→**180**, `session_cleanup_cron`
  None→**"0 3 * * *"**(신규 DB의 싱글톤 생성 시 적용 — checkpoint/token/approval 기본 ON 선례와 정합).
- **마이그레이션**(기존 싱글톤용): `session_retention_days`·cron이 **NULL인 경우만** 180·cron으로 설정
  (사용자가 이미 커스텀한 값은 보존). alembic로 리비전 ID 생성(손수 순번 금지, [[hand-authored-migration-ids-collide-silently]]).
- session-cleanup은 `Session.last_activity < cutoff`로 회수 → **활성·최근 세션 자연 보존**([[retrospect 351]]
  회수가 기능 죽이면 안 됨). 메시지는 `cascade:sessions`.

### 대장(resource_policy) 갱신
- `mem0 memory` 엔트리 `by`에 "add 관문 유저당 1000 축출(스펙 429)" 추가.
- `sessions` 엔트리 note "보존정책=BatchConfig(기본 OFF)" → "기본 180일 ON(스펙 429)".

## 완료 조건(측정) — 결과

`tests/verify_429_user_asset_caps.py` 10/10:
1. ✅ 기억: 1001→1000(오래된 것 축출·최신 보존) · **대량 add 완전 수렴**(한 add 200개→1000, codex 429
   [높음] 수정) · 타 유저 무영향 · 정확히 1000이면 축출 0. user_id 없는 add는 미적용(세션 축).
2. ✅ 메시지: session-cleanup dry-run `retention_days=180`·`would_delete=0`(활성/최근 세션 보존)·
   `cutoff=now-180d`. 마이그레이션으로 싱글톤 180+cron.
3. ✅ 무회귀: 그물 92/0/0(기본값 변경이 깬 테스트 0), 마이그레이션 단일 head·중복 0.
4. ✅ codex 적대 검토: 견고 경계 6건 확인(오래된 것만·타유저 불가침·count 정확·저장 무손상·활성 보존·
   dry-run) + 실결함 2건 봉합([높음] 수렴·[중간] downgrade 클로버) + 경계 2건 정직화(아래 OUT).

## OUT(경계)

- 유저별 상한 커스터마이즈(지금은 전역 상수 1000 — 팀 배포 시 정책은 후속).
- 나이 기반 기억 만료(개수 상한만 — 나이는 세션 축이 담당).
- 기억 축출의 배치 안전망(add 관문 축출로 유계 유지 — 드리프트용 배치는 후속).
- **created_at 결손·비정상 행의 축출 순서**(codex 429 경계): mem0 정렬이 NULLS LAST라 timestamp 없는/
  손상된 행은 실제 나이 무관하게 "가장 오래된 것"으로 취급돼 먼저 축출된다. 정상 mem0 생성 행은 항상
  created_at을 가져 안전 위반 아님 — 레거시·손상 행 처리는 별개(회복할 보조 시간키 없음).
- **BatchConfig 싱글톤이 DB 불변식 아님**(codex 429, 선재): 1행 강제 unique/check 없고 읽기 경로도
  `LIMIT 1`(정렬 없음)이라 2행이면 UI-수정 행과 잡-읽기 행이 다를 수 있다. 429가 도입한 게 아닌 기존
  가정(관례 싱글톤) — 마이그레이션도 싱글톤 전제. 1행 강제(제약)는 orthogonal 후속.
- **downgrade는 no-op**(codex 429): 값만으로 migration-set과 user-custom 180을 구분 못 해 되돌리면
  커스텀 파괴 → 정직하게 안 되돌린다(비활성화는 관리자가 설정에서).
