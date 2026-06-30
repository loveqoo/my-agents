# 068 — 메모리 회상 시험 도구 (스펙 084)

## 무엇을 한 작업인가
이슈1("플레이그라운드 인스펙터가 '메모리에서 검색했다'고 하는데 실제로는 시험 불가")을 닫았다.
메모리 관리 콘솔(에이전트/유저 두 탭)에 **'조회 시험' 드로어**를 달아, 챗과 *같은 공유 코어*로
임의 질의를 스코프(`agent_id`/`user_id`)별로 회상해 결과 카드(관련도·본문·스코프)를 눈으로 본다.
RAG 072의 `/search` 패턴을 메모리 축으로 미러링. RBAC/소유권 체크리스트 적용 대상이었다.

## 어디서 비자명했나 — 분별점

1. **`enabled` 정직성의 진짜 축.** 첫 설계는 `enabled = (mem_cfg is not None)`이었다. happy-path
   초록. 그러나 `resolve_backend`는 **초기화 실패를 try/except로 흡수해 None을 캐시**한다 — 즉
   "구성은 됐으나 깨진 백엔드"가 존재한다. 이때 `mem_cfg`는 not None이므로 `enabled=True`인데
   실제 회상은 항상 0건 → **"구성 안 됨/고장"을 "가용·회상 0건"으로 위장**한다. 사용자가 시험
   도구를 만든 이유(=실제로 되는지 확인)를 정면으로 배신하는 거짓 신호. 적대 codex가 P2a로 짚었고
   유효 수용. 처방: `memory.recall_probe`를 신설해 **`enabled`를 백엔드 *가용성*(resolve_backend
   결과)에 묶고**, None(미가용) vs [](가용·0건)을 구분. chat 경로(`search`)는 무변경(drift 0).

2. **RBAC 미러링의 정확한 기준선.** codex가 P1/P3로 "에이전트 검색이 비-어드민도 접근 가능·존재
   오라클"을 제기. 하지만 이건 형제 `GET /agents/{id}/memory`(list)와 **완전 동일 패턴**(같은
   `_auth` 라우터 게이트·같은 agent_id 스코프·read-only)이다. 신규 노출 0. principal 등급
   질문은 admin API 전체의 선재 속성(084 밖). → **과잉수정 회피**: 기존 형제 입구와 동일하게
   두는 게 정합. 유저 검색은 `_assert_principal_may_access`로 자기 user_id만(403)이라 이미 게이트됨.

3. **방어적 출력 경계(P2b).** 백엔드가 limit를 무시하고 더 반환하면 응답이 무방어. `[:limit]`
   슬라이스를 `recall_probe`에 박아 핸들러 계약과 무관하게 출력 상한 고정. U7 OverflowBackend로 핀.

## 검증 — 3런 비겹침
- ① 단위 35건(인프라 불요): 스키마 422·RBAC 게이트(FakeEnforcer+mock principal)·스코프 격리
  (FakeMem 축 필터)·graceful·404·핸들러 회상·`recall_probe` facade(None vs [] + 슬라이스).
- ② 실인프라 통합 12건(in-process ASGI + 실 DB) + **실 mem0 라운드트립**: add→시맨틱 질의가
  저장 사실을 **score 0.843**로 회상(스코프=agent_id), 시험 후 삭제로 시드 무오염.
- ③ 적대 codex: P2a·P2b 유효 수용·수정+회귀 핀, P1/P3 설계상 의도(형제 입구 동형).
- 브라우저(시스템 Chrome): 양성(회상 카드 #1·관련도 0.845·agent_id·semantic)·음성(enabled=true +
  "회상된 기억 없음", 미가용 Alert와 구분). tsc 0.

## 복리 지점
- learning 086("소비층 fail-closed만으론 죽은 상태가 샌다")과 **같은 결**의 다른 축: 086은
  *capability 술어*를 모든 쓰기/렌더 입구에 정렬, 084는 *상태 표시값(enabled)*을 프록시(mem_cfg
  존재)가 아니라 *실제 가용성*에 묶는다. 둘 다 "겉도는/거짓 신호"를 닫는 일. → learning 087.
- 메모리 [[probe-deeper-before-concluding]]·[[installed-guard-isnt-covering-guard]]와 공명:
  "설치/구성됨 ≠ 작동함"을 한 겹 더 파야 거짓 초록이 안 샌다.
