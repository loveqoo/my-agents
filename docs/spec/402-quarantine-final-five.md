# 402 — verify 격리 잔여 5건 근본 해결(격리 5→1 목표)

> 상태: **완료** · 2026-07-19 (격리 5→0 — 목표 초과 달성)
> 발단: 스펙 400이 43→5로 줄인 잔여. 실측하니 대장 사유와 실체가 갈림 — 4건은 재활 가능,
> 1건(068)만 진짜 조사 대상.

## 목표(수치)

- KNOWN_DRIFT **5 → 1 이하**(068은 조사 결과에 따라 재활 또는 정당 잔류).
- 재활 4건 virgin 그린 → 그물 복귀. 최종 make test-all SUITE_OK + metrics-fast.

## 처방(파일당 — 400 방법론 재사용: 실측→판정→재작성→복귀)

- **P1 verify_114(owner 표시)**: `next()` 무default로 owner_id=None 레거시 에이전트를 찾다
  StopIteration. 자기완결 픽스처(무소유=public 에이전트 직접 생성+자가정리)로 재작성.
- **P2 verify_143(평가 출제 도우미)**: '옵시디언 매니저' 시드 전제 → 시험용 에이전트 자기완결
  생성(141 선례 — RAG형+역할형 혼합 출제 축 유지, vectorTables 배선).
- **P3 verify_057(connect 분류)**: ①스펙 370 노후(`AgentVersion.status` → everOpened) ②C2/C3
  endpoint 기대치 실측 판정(현동작=:8000/_remote/a2a — 카드 url 정규화 계약(스펙 060·061)과
  대조, "현동작=옳다" 가정 금지) ③C5 라우팅 소스 단언 현행화 ④종료부 이벤트루프 하네스
  버그(asyncio.run 이중 실행) 수선.
- **P4 verify_054_mcp_real_runtime**: ①T6 근인=도구 스펙 캐시(스펙 371) 키 `(name, version,
  auth_fp)`가 **transport·url 미포함** — 같은 이름을 PRE가 http로 캐시하면 stdio 픽스처가 캐시
  적중해 transport 관문(mcp_connection)을 우회. 테스트는 **픽스처 이름 분리**로 축 격리(관문
  자체는 실측 정상). 프로덕션 실재성(편집이 version을 항상 범프해 키가 회전하는가)은 **codex
  적대 검토 포인트**로 명시(installed-guard≠covering-guard). ②`MOCK_MCP_URL` :8000 상수의 dev
  서버 의존 → VERIFY_BASE 유도(throwaway 자립).
- **P5 verify_068(member resume)**: 근인 조사 — deep-reasoner 위임(읽기 전용): D6 실패의 실물
  (예외 타입·발생 지점·asyncpg 커넥션 수명 가설 검증)을 좁혀 판정 보고. 앱 결함이면 **보고만**
  (수선은 별도 승인 — 400 OUT 관례), 테스트 결함이면 재활.

## 결과(실측) — 격리 5→0

- [x] P1 114: 실체는 스펙 147 가시성 노후(bob은 타인 private를 목록에서 못 봄) — 비가시 단언으로 재작성. 그린.
- [x] P2 143: 실체는 제품 게이트 자체(도우미=실모델 전용, eval_guards) — mock이면 **사유 문자열 단언**으로
      승격, 실모델 전체 출제는 VERIFY_143_FULL=1 opt-in 분리, 에이전트 자기완결. 그린(virgin·라이브 양무대).
- [x] P3 057: 370 노후(status→everOpened)+endpoint 기대(카드 광고 url 실측 비교)+C5 라우팅(085 impl 해석)
      +C7(ctx dict→데이터클래스)+하네스(예외 시 별도 asyncio.run 정리 금지 — 단일 루프 finally). 그린.
- [x] P4 054rt: T6 근인=도구 캐시(371) 키의 transport 미포함 — 픽스처 이름 분리로 축 격리+MOCK_MCP_URL
      :8000 의존 제거(VERIFY_BASE 유도). 그린. **codex 판정: 캐시-관문 우회는 비실재**(편집 경로가
      record_block_version으로 항상 version 범프 — blocks_mcp.py:340·block_versions.py:105, pin은 의도).
- [x] P5 068: deep-reasoner 근인 — **테스트 하네스의 SSE early-abort**(첫 프레임 후 즉시 끊음)→서버 턴
      취소→asyncpg/psycopg 공유 풀 poison→후속 인증 쿼리 비결정 500. 재개/소유권 로직 무죄(D6★·T6 통과).
      드레인 하네스로 수선 → **5회 연속 그린, 재활 성공**(잔류 0).
- [x] make test-all SUITE_OK + metrics-fast 전판.

## 실구멍 보고(앱 — 수선은 별도 승인, codex 402 확인)

**SSE 클라이언트 중도 이탈의 커넥션 풀 오염**은 실사용(탭 닫기·모바일 이탈)에서 재현 조건 —
068이 하네스에서 우연히 재현한 프로덕션 잠복 부채. 봉합 스케치(codex): ①`pool_pre_ping=True`
(메인 엔진, 필요하되 불충분) ②체크포인터 psycopg 풀 checkout 검증 ③`event_stream` finally의
`release_thread`를 `asyncio.shield`+timeout으로 취소-레이스 차단 ④early-abort 회귀 테스트.
→ 백로그 등재(후속 스펙 후보).

## OUT

- 앱 코드 수정(P4 캐시 키 확장·068 수선 포함 — 판정·보고까지, 수선은 별도 승인).
- stdio transport 정식 지원(054 §7 유예 유지).
