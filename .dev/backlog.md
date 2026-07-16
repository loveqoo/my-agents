# Backlog — 작업 후보 보드 (AI 영역)

> Scaffolding의 **진입 재료**. "다음 뭐 하지?"에서 이 파일을 먼저 읽어 후보/완료/보류를 한눈에 본다
> (대화 재유도 대신 스캔). 굵은 단위(후보 작업)만 — 서브태스크는 안 쪼갠다(파편화 방지). learning/
> retrospect/spec의 `INDEX.md`가 회고 상기를 싸게 만들듯, 이 파일은 *백로그 상기*를 싸게 만든다.
> 규칙이 아니라 종이 한 장 — 새 작업 정해지면 여기서 옮기고, 끝나면 완료로 내린다.

## 후보
- [ ] **A2A 서빙 v2: contextId 세션 연속성 + 승인(HIL) 브리지**(2026-07-16 접수, 구남님 "백로그에 올려줘" — 387 후속 문답에서 도출). **동기**: 외부 연동의 주력이 A2A 표준이라면, 지금 A2A JSON-RPC 입구는 유저 특정(metadata.userId, 387)+기억(user 축)까지만 — 세션·승인은 채팅 API(머신 Bearer)로 우회해야 한다. **현재 상태(조사 완료)**: 서빙(`stream_local_reply`)은 v1 무상태(스펙 061 §6 — persist·세션·HIL 미적용, 호출당 단일 메시지). 우리 a2a_client는 contextId를 **보내지만**(스펙 057, chat_stream.py:87) 우리 서버는 **소비 안 함**(chat_stream.py:205 "맥락은 호출측 책임"). 승인 필요 도구는 checkpointer=None이라 fail-closed(안전 거부). **설계 조각**: ①contextId→세션 매핑(수신 시 세션 resume/생성 — RBAC 체크리스트 "외부 프로토콜 입구" 항목 정면 적용: contextId 추측으로 타인 세션 잡기 방지 필요, userId+contextId 바인딩 검증) ②승인 브리지=A2A 표준 input-required 태스크 상태로 승인 대기를 표현(우리 approvals와 왕복) ③재개 턴 자동 기억 저장 빚(chat_approval "user_id 부재로 생략" 주석)도 함께. 비교표·근거는 387 후속 문답(2026-07-16) 참조.
- ✅**기억 표면 정직화+A2A 유저 정체성 = 스펙 387 완료**(2026-07-16, 회고 390): 구남님 "단기(세션)" 추궁 발단 — ①죽은 드롭다운 옵션(레거시 행) 삭제 ②머신/A2A userId 전달 개방(단일 관문: 쿠키 422·머신 수용, chat body+A2A metadata 두 입구, 서빙 회상/자동저장 배선) ③저장 검증 422+삭제 참조 가드 409 ④문구 화석 정정. verify_387 18/18·suite 51/51·codex P1(비-dict metadata 500)/P2(캡80 정렬) 봉합. **잔여**: ⓐverify_158 재작성(mock cfg 명시 고정 — 실모델 기본값과 독립하게) ⓑverify_020/268이 옛 카탈로그 이름 참조(죽은 이름으로 조용히 통과 중이었음 — 저장 검증 그물 밖 직접 config, 정리 후보) ⓒ서빙 자동저장의 GeneratorExit 경계(클라이언트 이탈 시 저장 생략 — detached task 후속).
- ✅**make metrics 게이트 복구 = 스펙 386 완료**(2026-07-16, 회고 388): RED 4축 전부 그린 — format 17파일(오진 정정: ruff 버전 드리프트 아닌 make format 안 거친 커밋들)·naming 17→0(rename 13+ACTION_WHITELIST 4 등재)·complexity D2→0(_load_context 21→C11·consolidate 23→C, verbatim 추출)·chat.py MI B(18.77)→A(24.70)(트레이스 가족 6함수 chat_trace.py 이동)·mypy 6→0(베이스라인까지 소거). 동작불변=codex "결함 없음"(AST 동일성)+실채팅 관통+SUITE_OK. ~~잔여 관찰 ①suite 차단~~ **→ 해소(2026-07-16, 회고 389)**: 사라진 MLX provider/모델을 .env 구성으로 재등록+기본값 복원+mock-벡터 잔해 정리 → **suite 51/51**(46→47→50→51). 3층 근인=행 소실·기본값 mock·임베더 교차 오염(mock 시절 벡터 reused). **미해결 관찰**: ⓐ실모델 행이 왜 사라졌나(이력에 실모델 흔적 0 — 369 이전 등록·삭제 추정, 재발 시 단서 대장) ⓑ`_verify093_emb`+`_verify093_prov`+`v369-prov-45e9da` 테스트 누수 잔존(clean-test-agents는 agents만 — 모델/provider/컬렉션 누수는 sweep-debris 확장 후보) ⓒ픽스처 reused가 임베더 지문 미확인(교체 시 무효 벡터 재사용 함정 — suite fixtures 개선 후보).
- ✅**http verify 17건 triage = 스펙 384 완료**(2026-07-16). test-all이 17건 "새 회귀" 보고 → triage(각 단독 실행+baseline 워크트리 대조)로 **전부 테스트 쪽·앱 결함 0 확정**(공유 라이브 DB 얽힘·스키마 진화 뒤처진 기대치·fragile 코드). verify_093 "잠재 실버그"도 delete_model 가드가 이미 컬렉션 참조 409로 덮음(테스트 route 우회 raw 삭제). 조치: 순수 드리프트 047(제거된 status 인자) 수정→그물 복귀·16건 KNOWN_DRIFT 격리. test-all SUITE_OK. 회고 386. **근본 미해결→아래 "verify 스위트 격리"로 승계**: 격리 16/17이 전부 공유 DB 원인이라 격리 하네스(fresh-DB-per-run) 없이는 재오염(개별 전제 수정=두더지잡기). 034 배지 델타·084 mem0 hit shape는 하네스 위 재검.
- ✅**배치 트리거 dry_run 계약 경화 = 스펙 383 완료**(2026-07-16). 안전버그: `POST /admin/batch/{job}/run`이 dry_run을 `Query(False)`로만 읽어 (1)body `{"dry_run":true}` 조용히 무시 (2)기본값 위험쪽(false=진짜실행) — 배치 잡 전부 파괴적 삭제(자원 감사 후속 ③ 소진). 경화=body에서도 읽고·기본값 안전쪽(dry-run)·body>query>true. codex 적대리뷰 P1=StrictBool(강제변환 "off"·0·"no"→False 실행 차단, 422). verify_383 10/10·SUITE_OK. **곁다리**: 묶음 A의 두 번째 건 verify_233 "위임 갭"은 **오경보**(단독 통과 VERIFY233_OK, orchestrate_ranked×agent PASS)—KNOWN_DRIFT 사유만 정정("제품결함 후보"→"상태 오염 격리"). 회고 385. → [[verify-premise-before-designing]](묶음도 각 건 실물 판정).
- [ ] **조율형 위임 전략을 UI에서 고르게(orchestrate_ranked 노출)**(2026-07-16 접수, 구남님 "필요합니다 · UI에서 나중에 설정해서 쓰게"). **동기**: 후보가 여럿일 때 첫 하나만 잡지 말고 관련도 상위 몇 개를 골라 조합하는 랭킹형이 필요한데, 지금 UI로는 새로 못 고름. **현재 상태(조사 완료 — 재조사 불요)**: 백엔드 impl(`RankedOrchestrateAgent`, orchestrate.py:326·`TOP_K=3`·`DISCOVER_LIMIT=10`)·레지스트리(runtime.py:254)·admin 판별(`isOrchestratorImpl`·GENERIC_IMPLS 등재)·라운드트립 보존(AgentForm.tsx:226)까지 **이미 다 있음**. 막힌 곳은 **딱 하나** — `AGENT_TYPES`(AgentForm.tsx:74~80)의 "종류" 셀렉터가 '조율형' 하나만 주고 그게 무조건 `orchestrate`(first-match) 생성. 즉 첫후보형 vs 랭킹형 **하위 선택 어포던스만 부재**. **설계 제약**: `impl`·`orchestrate_ranked`·브로커 같은 내부어 UI 노출 금지(AgentForm.tsx:72) → 사용자 언어 하위 선택으로. [[context-control-propagates-to-affordances]](조율형에 전략 선택 넣으면 하위 어포던스도 승계). **남은 결정(착수 시)**: ①노출 범위=세부 수치(TOP_K 3·후보상한 10) 어디까지 폼에 열지 — 제품 표면 수치라 [[product-limits-need-explicit-approval]] 승인 항목 ②verify_233 위임 갭(랭킹형이 agent kind에 발동 안 함, KNOWN_DRIFT 격리)이 실버그인지 의도 경계인지 판정 후 노출 — 노출하면 사용자가 바로 부딪힘. 둘 다 착수 시 재논의.
- ✅**도그푸딩 DB 테스트-누수 에이전트 정리**(2026-07-16, 회고 384) — 42개 중 37개가 테스트 누수(e2e/verify/버전테스트/mock-a2a). 정식 API 관문으로 정리, 시드 데모 5개만 잔여. 재발 방지=`tests/clean_test_agents.py`+`make clean-test-agents[-apply]`(dry-run 기본·KEEP 리스트 가드). ~~후속 후보(조사 중 드러남): impl 데모-갭~~ **→ 감사로 기각(2026-07-16)**: 걷어낼 죽은 impl 없음. ①6종 전부 테스트·스킬·스펙·admin에서 참조 두터움(죽은 심볼 0 — `OrchestrateAgent` 별칭도 verify_100/101 실사용). ②데모-갭은 **의도적·문서화됨**(seed.py:361-366: "데모는 범용 노드형으로 시연, 코드 정의 impl은 UI 편집 없이 플레이그라운드/suite 픽스처 테스트"·plan_execute는 SDK 레퍼런스로 레지스트리 유지). ③조율형 둘은 **중복 아님**—orchestrate=first-match(스펙 100/101)·orchestrate_ranked=랭킹 상위 k(스펙 102 전략 A), 소유자 선택형 두 전략. **남은 실 잔재 1건**: verify_233의 orchestrate_ranked가 agent kind에 발동 안 하는 위임 갭 = *버그 후보*(죽은 코드 아님, KNOWN_DRIFT 격리 중). 전제(미데모=제거 대상)가 거짓이었음 → [[verify-premise-before-designing]].
- ✅**버전 모델·캐시·평가 게이트 캠페인 = 스펙 367~372 완주**(2026-07-16): 367 확정 모델(불변 단조 버전+오픈 포인터) → 368 측정 하네스(perf-build·buildMs) → 369 블록 버전화(append-only·관문) → 370 복합 버전(pins freeze·충돌 규칙·롤백) → 371 캐시 팩토리(**170ms→0.0ms**, MCP 사양 캐시+클라이언트 풀+그래프 팩토리) → 372 평가 게이트(회수·평균 임계, 롤백 면제·우회 없음). **잔여 관찰**: ①캐시 경로 HIL 승인 e2e 없음(승인 플로우 실사용 관찰 항목, 371 스펙 명시) ②MCP PUT이 미포함 필드(published)를 기본값으로 덮는 wholesale-replace 성질(372 중 실물 재확인 — 라우트 계약 후속 후보) ③그래프 캐시 노드형/조율형 확장(371 OUT) ④D2 클라이언트 풀의 실 TLS 이득은 회사 환경서 측정.
- [ ] **체크포인터 멀티워커 setup 경합(스펙 354 codex P1, 2026-07-15)**: fresh DB에 uvicorn/gunicorn 워커 N개가 동시 부팅해 각자 `saver.setup()` 하면 checkpoint_migrations PK 충돌로 일부 워커의 HIL 재개가 조용히 비활성될 수 있음. 현재 단일 워커라 낮은 위험이나, 멀티 인스턴스(k8s 레플리카) 배포 시 실재. 대응=setup 전후 advisory lock(스펙 348 배치 리더 패턴 재사용) 또는 migration 실패를 "이미 끝남"으로 재조회.
- [ ] **INDEX 키워드 배열 압축(2026-07-15 재압축 후속)**: 재압축으로 후크는 최소화됐으나 능력 브로커 시리즈(spec/retrospect 069~105 등)는 **키워드 배열 자체가 200~540자**(키워드 15~22개)라 줄이 못 줄었다. 키워드는 recall 앵커라 이번엔 "절대 보존"으로 뒀지만, 20개는 과할 수 있음 — 항목당 핵심 5~8개로 추릴지 판단 필요(단, recall 적중률 저하 위험이 있어 측정 동반 필요, 지금은 급하지 않음).
- [ ] **자원 감사 캠페인 후속(스펙 346~352 OUT, 2026-07-15)**: ①**살아있는 유저 기억·메시지의 상한** — 스코어보드 0은 "분류가 정직하다"는 뜻이지 "무한 증가가 없다"는 뜻이 아니다. 유저 자산의 개수/나이 상한은 **제품 가시 한계라 사용자 승인 사항** → 승인 나면 스펙. ②**RAG 인제스트 메모리**(감사에서 유일하게 미해결로 남긴 축 — ~1.6GB는 **산술 추정이지 실측이 아니다**. 처방 전에 5만 행 인제스트 중 RSS를 **측정**부터. 동시 인제스트 태스크 상한도 없음) ~~③배치 트리거의 dry-run 날카로운 모서리~~ **→ 스펙 383 완료(2026-07-16)**: body 수용+안전 기본값(dry-run)+StrictBool(codex P1). verify_383 10/10.
- [ ] **감사 후속(스펙 343 OUT, 2026-07-14)**: ①**감사값 UI 노출**(created_by/updated_by를 목록·상세에 — 값은 다 쌓이는데 화면에 없어 지금은 psql로만 볼 수 있다. "audit 가능"의 마지막 한 칸) ②**변경 이력 테이블**(audit_log — 누가 무엇을 *어떻게* 바꿨나 diff 보관. 지금은 "마지막 수정자"까지만) ③운영 규모 백필(full-table UPDATE 락 — 배치 백필·lock_timeout) ④소프트 삭제(deleted_at/deleted_by).
- [ ] **기존 게이트 드리프트 2건**(2026-07-14, 스펙 343 중 stash 대조로 확증 — 이번 변경 아님): verify_098_session_search P?("plainagent+error → S2만"에 sess_v098_MARKERID_1이 섞임) · verify_034_session_pagination(KeyError 'awaiting' — counts 버킷 4종 기대치가 스키마/응답과 어긋남). 격리 DB에서도 재현 → 검증기 노후. 336류의 "게이트 드리프트" 묶음.
- ✅**체크포인트 무한 누적 정리 = 스펙 346 완료**(2026-07-15, 회고 318 — 사용자가 "컬럼/자식 테이블"로 방향 제안). 3레버: `durability="exit"`(턴당 3행→**1행**)·**관문**(턴 종료 시 폐기, 승인·폼 대기 보존 — 판정은 "핀 있나"가 아니라 **"턴이 정말 끝났나"**, codex P1)·TTL 스윕(24h 배치, 고아+방치승인→`expired` 기록 후 회수). 정상 대화 후 잔여 **0행**. VERIFY346 16/16·UI 7/7. **OUT(후속)**: 대화 이중보관(messages vs 체크포인트 channel_values) 정리 · thread_id 세션-안정화 · 멀티레플리카 스윕 lease + `_PENDING_ARTIFACT` 공유(k8s P1③·P2와 합류) · `ts` 없는 스레드 자동회수(현재 `unknown_age`로 노출만).
- ~~[ ] 체크포인트 무한 누적(원 항목)~~: LangGraph `AsyncPostgresSaver`가 **슈퍼스텝 경계마다 1행** 남긴다 → 턴당 checkpoints ≈ 1(input) + 슈퍼스텝수 + 1(단일노드 personal-secretary=**3**, 멀티노드 suite-pipeline=**7**, checkpoint_writes/blobs 동배율). **삭제 경로가 코드에 아예 없음**(테이블 주인=langgraph, alembic 미관여) → 세션 끝나도 잔류. 현 dev DB: messages 516행 vs checkpoints 10,181 / writes 14,423(20~30배). 존재 이유=HIL 재개(`approvals.checkpoint=thread_id`로 되감음)라 턴 중엔 필수, **끝난 뒤가 문제**. 방안 3갈래: ①세션 종료·승인 해소 시 `saver.adelete_thread(thread_id)` ②나이 기반 TTL 정리 배치 ③HIL 미사용 에이전트는 체크포인터 미부착. 부수 관찰: 대화 히스토리가 messages·checkpoints **양쪽에 중복** 보관.
- ✅**죽은 영역 감사(324) 잔여 3건 = 스펙 329 완료**(2026-07-13, 회고 304 — 감사 축 완전 마감): 사용자 결정 전부 제거 — ①generate-dataset 기계 일습+마커 화석 3곳(_is_generating 접두·좀비 스윕 생성 블록·실행 409 보조판정) ②Chunk.token_count DROP(d5795d21f6a2) ③하네스 088 2종+소비자 shot-markdown-088. ~~재발 방지 스킬화~~ → ✅**스펙 325 완료**(2026-07-13): `.claude/skills/dead-area-audit/SKILL.md` — 축 A~F·4기 프롬프트·규율 5종. 스킬 개선 씨앗(329 발견): 문자열 계약(마커·문구·포맷) 소비자 grep을 축에 추가.
- ✅**init_db 폴백의 조용한 우회 = 스펙 330 완료**(2026-07-14, 회고 305): 사용자 결정=**완전 제거**(virgin 한정안 기각 — 새 DB서 고장 계속 가림). alembic 실패→조치 메시지+부팅 중단, alembic=스키마 단일 진실. verify_330(F1 fail-fast 여집합·F4 확장 보장 실증)+058/059 재작성. k8s ②(마이그레이션 Job 분리)의 선행 정지작업 완료.
- [ ] **verify-eval-ux-193.mjs 드리프트**(2026-07-13, 스펙 329 중 stash 확증 — 기존): P1(컬렉션 칩)부터 4건 실패, UI 개편으로 셀렉터 노후 추정. 브라우저 verify 스크립트 전반 노후 점검은 "verify 스위트 격리"(321 대형)와 합류 후보.
- ✅**기존 게이트 드리프트 3건 = 스펙 336 완료**(2026-07-14, 회고 311): ①suite pipeline-rag-and-tool=발화 정렬로 0/5→8/8(노드 프롬프트 도구 강제는 모델이 무시 — 유저 발화 요구+FACT 토큰 관통 단언) ②복잡도 D 2곳 분해(rag reindex·blocks test_mcp_tool — 둘째는 grep 필터가 숨겼던 것) ③verify_312=검증기 2중 버그(334 여파+스킵 다리 고정 기대치). suite 전판 51/51. 잔여 관찰: flaky 2종(bare-session-recall·direct-control-combined — 재시도 통과 수준)·rag.py 모듈 분할(별 스펙 규모).
- [ ] **RAG 인제스트 후속 씨앗**(스펙 334·335 OUT, 2026-07-14): 실패 문서 "재시도" 버튼(blob 보존돼 재업로드 불요) · 이벤트 버스에 재인덱싱·평가 런 합류(각 publish 한 줄) · 진행률(행 단위 %) · 영속 알림함(놓친 이벤트 재생).
- [ ] **노드형 확장 3부작**(사용자 제안 2026-07-13, 설계 3결정 합의: ①버전 핀 참조[발행 불변·수정=새 버전, 코드 노드만 동일 버전 덮어쓰기 허용] ②에이전트 호출=도구 방식 A·ID 기반 이름[사용자 제안 `agent:{agent_id}` — 단 provider 도구명에 `:` 불허가 흔해 `agent__{agent_id}` 제안 예정] ③재귀 가드 필수):
  - ✅**① 노드 라이브러리+버전 고정 참조 = 스펙 316 완료**(2026-07-13, 회고 291) — NodeTemplate(name,version)·ref 해석(해석→병합)·advisory lock TOCTOU 봉인·삭제 409·특권 변이 게이트·usedBy 가시성 필터·admin 뷰+폼 참조 픽커+오버라이드 베이스. codex P1 4 수정.
  - ✅**② 코드 노드 = 스펙 317 완료**(2026-07-13, 회고 292) — CustomNode Protocol+register_node(085 미러)·부팅 manifest 카탈로그 upsert·mask-pii 레퍼런스·오버라이드는 표면만·미등록 impl=설정오류(네 입구). codex P1 3(eval 입구·재개 500·sync TOCTOU)+P2 2 수정.
  - ✅**③ 노드에서 에이전트 호출 도구 = 스펙 318 완료**(2026-07-13, 회고 293) — build_agent_tools로 브로커를 노드 도구 표면에 연결, `agent__{agent_id}`·재귀 가드(깊이 8·너비 32)·세 입구 extend. 후속 319(도구 결과 인젝션 펜스 통일)까지 완료(회고 294). **3부작 전체 마감.**
- [ ] **k8s 멀티 인스턴스(레플리카 N) 배포 지원**(2026-07-13 점검 — deep-reasoner 전수 + 메인 P1 코드검증). 지금 상태로 여러 인스턴스 올리면 깨짐. Dockerfile·k8s 매니페스트 아직 없음(배포 미정의)·단일 파드 `uvicorn --workers N`도 같은 프로세스 경계 문제 재현.
  - **P1 배포 차단(3)**: ①**비밀키 파드별 발산**(`crypto.py _fernet`·`auth.py`: `APP_SECRET_KEY`/`API_AUTH_TOKEN` env 없으면 파드 로컬 파일에 각자 키 생성 → 파드 A가 공유 DB에 암호화한 provider키·에이전트토큰을 파드 B가 복호화 실패 500·머신토큰도 A인증→B 401) = **k8s Secret 전 파드 동일 주입**(최우선, 주입 시 폴백경로 소멸) ②**마이그레이션이 앱 lifespan**(`main.py`→`db.py init_db` alembic upgrade head) = 동시 부팅 경합 → **initContainer/Job 단일 러너로 분리**(seed·스윕도 이관) ③**부팅 좀비 스윕이 타 레플리카 실행 죽임**(`eval_runs.py sweep_zombie_runs`/`sweep_zombie_datasets`·`db.py _recover_stale_reindex` — "부팅=이전 프로세스 죽음" 단일 전제, 레플리카 B 부팅이 A의 running eval/재인덱싱 error 박제) = **heartbeat/lease 기반 회수 또는 Job 이관**(스펙 312 OUT 빚).
  - **P2 운영 위험**: casbin enforcer 파드별 인메모리 stale(`authz.py` — 권한 취소가 타 파드 재시작 전까지 미반영, reload 경로 없음)=롤링 재시작 규칙/TTL reload·`_PENDING_ARTIFACT`(`chat_approval.py`) 프로세스 로컬→산출물형 ask/form 멀티턴이 파드 넘으면 끊김(HIL 승인재개는 DB `Approval.checkpoint`라 안전)·배경 태스크(`background.py spawn`·memory.add·eval 실행) in-process at-most-once 유실·DB `pool_size` 미설정×N파드 `max_connections` 압박·배치 서비스 `replicas=1` 고정(cron 이중 발화 방지).
  - **안심(멀티 안전 코드확인)**: HIL 체크포인터=공유 Postgres(AsyncPostgresSaver, 임의 레플리카 재개)·MCP 서빙 `stateless_http`·A2A 무상태·mem0/RAG=공유 pgvector·`sync_code_nodes` advisory lock(스펙 317)·net_guard ≤10s 수렴·요청/턴 스코프 캐시.
  - **배포 전 필수(압축)**: (1)Secret 2개 주입 (2)마이그레이션 Job 분리 (3)좀비 스윕 lease화 (4)정책변경=롤링재시작 (5)pool_size 명시+배치 replicas=1. 회사 이식 초기=팀 한정이라 과투자 없이(Secret 주입+마이그레이션 Job이 최소 조치). 세부 점검 로그는 대화 세션 참조(원하면 `.dev/`에 문서화 가능).
- ✅**OTEL 계측 = 스펙 328 완료**(2026-07-13, 회고 303) — Langfuse SDK 직결 제거→OTLP 방출(자작 thin 콜백, 부착 4곳 무변경). 개인=Jaeger 컨테이너 1개로 라이브 확인, 회사=endpoint 주소만. OUT(후속 후보): 메트릭(Prometheus)·A2A traceparent 전파·로그 상관.
- [ ] 오버라이드 서랍 2단계 모바일 실기기 확인(스펙 249 잔여 — 사용자 "다음에") — 사용자 실사용 후보 10건 (2026-07-03 접수, 원문 보존·성격별 묶음)
- ✅**컬렉션 재인덱싱 도구=스펙 312 완료**(2026-07-12, 회고 287) — 스펙 158/160 OUT 씨앗("재인덱싱 도구") 소진. 임베딩 모델 교체(같은 차원 1024)+청크 크기·겹침 재청킹을 저장된 원본으로. 배타 잠금·이력 테이블·평가 이력 보존. mock→e5 검색 0.056→0.907 실측. codex 7건→3수정(F1 P0 데이터손실 봉인). **OUT(후속 후보)**: 차원 변경(1024↔768=전역 벡터 저장 구조 재설계, deep-reasoner 설계 선행)·~~무중단 재인덱싱~~·RAG 모델/청크 비교 격자(에이전트 141 미러)·멀티워커 stale lease·passage 접두어용 재인덱싱(스펙 160 씨앗).
- ✅**plan-execute-demo 멈춤/이상답=스펙 315 완료**(2026-07-13, 회고 290) — "스트리밍 UI 최신 동향 검색"이 오래 멈추고 이상한 답. 실측=실행 노드가 wiki 도구를 14회 반복(수렴 실패)하다 모델 서버 연결 끊김. 실행 노드 ReAct 루프에 상한(6) 도달 시 도구 언바인드+넛지로 강제 수렴→180초+/끊김→27초 정상. 사용자가 이 멈춤에 "314 미완"으로 오인(별개 원인—세션메모리라 314 경로 안 탐). codex P1(느슨한 provider 방어) 수정. **OUT**: recursion_limit 백스톱·모델 끊김 재시도·병렬 tool_calls 실행총량 캡.
- ✅**인스펙터 지연=스펙 314 완료**(2026-07-12, 회고 289) — 사용자 보고 "인스펙터가 너무 오래 걸림". **측정으로 진단하니 인스펙터가 아니라 자동 기억 저장(memory.add, 장기 메모리 mem0 LLM 추출)이 done을 막던 것**(trace는 0ms·1.2KB 무죄). memory.add를 done 뒤 백그라운드로 빼고 완료 시 트레일링 event: memory로 인스펙터에 조용히 반영(pending 로딩→완료). codex P0(detached 태스크를 done yield 앞에서 생성)+P1 3+P2 2 수정. VERIFY314_OK/UI_OK. **OUT**: 폴링(미채택)·배포용 인스펙터 제거 옵션(A2A 서빙은 이미 trace 없음—chat() 직접 노출 시에만)·mem0 호출 취소가능화(hang 시 스레드 고아).
- ✅**무중단 재인덱싱=스펙 313 완료**(2026-07-12, 회고 288) — 스펙 312가 재인덱싱 중 검색까지 409로 막던 걸 **검색 무중단**으로. 핵심=`_do_reindex`가 이미 원자 스왑이라 **Postgres MVCC가 무중단 공짜** → 검색의 잠금 검사만 제거(스키마 변경 0·세대 컬럼 불필요). 쓰기(인제스트·재인덱싱)는 직렬화 유지, 검색만 예외. VERIFY313_OK(실동시성 11회 200)+codex P0/P1 0. **OUT**: 다중컬렉션 전역 스냅샷(REPEATABLE READ)·무중단 인제스트(델타 이중쓰기)·초대형 단일txn 분할(세대기반).

### A. 버그/즉시 (실사용 차단)
- ✅**#1 기본 모델 설정=스펙 150 완료**(2026-07-03, 회고 128) — 원래 항목: **#1 기본 모델 설정(버그)**: provider에서 기본 chat/embedding 모델 변경이 안 됨(삭제 후 재등록만 가능).
  메모리 유사도 검색이 mock embedding에 묶여 있는데, mock 모델이 컬렉션에 참조 중이라 제거도 불가.
  → 기본 모델 전환 API+UI(삭제 없이 is_default 이양). 컬렉션 바인딩(차원 고정)은 유지한 채 *기본*만 전환.
- ✅**#2 MCP 상세 정보=스펙 151 완료**(2026-07-04, 회고 129) — 원래 항목: **#2 MCP 상세 정보(버그/공백)**: 등록 화면에 하위 툴의 메타정보(이름·설명·파라미터)가 노출되지 않고,
  MCP 기능을 들여다보는 화면 자체가 없음. → discover가 파라미터 스키마까지 수집·저장, 상세 드로어 신설.

### B. A2A/MCP 공개 체계 시리즈 (3~8 — 한 묶음, 스펙 시리즈로)
- ✅**#5 재공개 금지=스펙 152 완료**(2026-07-04) — MCP 3입구 봉인+source 불변+배선 fail-closed(에이전트는 083 기봉인).
- ✅**#6 organization 설정=스펙 153 완료**(2026-07-04, 회고 131) — app_settings 저장소 신설(범용 기반, #7·#9 재사용).
- ✅**#3 커스텀 에이전트 A2A 공개=스펙 154 완료**(2026-07-04, 회고 132) — 승격/강등 신설(백로그 ③ 흡수)+code 1홉 중계.
- ✅**#8 플레이그라운드 A2A 루프백 테스트=스펙 155 완료**(2026-07-03, 회고 133) — 직접/A2A 경유 토글+클라 stream 파서+154 후속 배지 게이트 정직화. A2A=단발·비영속 인라인 배너로 정직화.
- ✅**#4 내부 MCP 외부 공개 + 커스텀 MCP=스펙 156 완료**(2026-07-03, 회고 134) — to_fastmcp+FastMCP를 /_served/mcp/{name}에 서빙(외부가 붙음), source=custom 신설·공개 가드·무인증 서빙 안전 불변식. codex High1(유래 시스템전용)/Med1(멱등 reconcile)/Low1(도구 allowlist).
- ✅**#7 A2A skills 확장=스펙 157 완료**(2026-07-03, 회고 135) — 카드가 실제 능력(MCP·delegate·rag) 광고+플그 칩. codex High1(누출+거짓위임 봉인)/Med2/Low1. **B 시리즈(#3·#4·#5·#6·#7·#8) 전부 완료.**

### C. 플랫폼 방향 (대형)
- **#9 buddy agent(메뉴별 도우미)**: 143(평가 도우미)의 확장 — 기본 chat/embedding이 실모델일 때
  각 메뉴 기능을 가이드·대행. #1(기본 모델 설정)이 사실상 선행 조건.
- **#10 피드백→평가 데이터 수확(롱텀 하네스)**: 유저 응답/랜덤 피드백을 평가 케이스·선호 데이터(DPO류)로
  축적해 응답 고도화. 평가 백로그의 "세션→케이스 수확"·"인간 리뷰 층" 씨앗과 합류.

## 후보 (다음에 할 만한 것) — 새 방향 4개(사용자 "모두 차례대로", 순서대로)

- ✅ **방향 1 — A2A 협업 실증 + 위임 승인 게이트**(스펙 117) 완료 → 아래 완료.
- ✅ **방향 2 — 관측·측정 계층(Langfuse)**(스펙 118) 완료 → 아래 완료.
- ✅ **방향 3 — 에이전트 평가 하네스(수치)**(스펙 119) 완료 → 아래 완료.
- ✅ **방향 4 — 저마찰 생성(복제)**(스펙 120) 완료 → 아래 완료. **4개 방향 전부 소진.**

### 후속 씨앗 (급하지 않음)
- **런타임 도구명(_safe_name) 전역 유일성 검증**(codex 289 #5) — MCP 서버명+도구명·컬렉션 문서
  도구명이 60자 절단·문자 치환으로 충돌하면 by_name이 마지막 것을 조용히 선택. 생성/수정 입구에서
  런타임명 충돌 검증(스펙 148 네이밍 계열). 289 파생은 모호 민이름만 fail-closed로 부분 방어.
- ✅**노드형 풀 서버측 파생 → 스펙 289 P2로 완료**(2026-07-11) — 원 항목: (스펙 288 실측 #2 후속) — API로 직접 만든 노드형은 vectorTables/memories
  풀이 비어 노드 도구가 조용히 미바인딩(폼 derivePipelinePool만이 파생 책임). 서버가 저장/실행 시
  노드 합집합에서 풀을 스스로 파생하면 폼 밖 입구(API·A2A 등록)도 안전 — learning 151(조용한 미바인딩)
  의 구조적 봉합 후보.
- **조합 스위트 artifact(HIL 폼) 시나리오**(스펙 288 P2 OUT) — artifact_form 픽스처+폼 왕복 관측 표면
  실측 후 시나리오 2개 추가. 스위트는 `tests/suite/run.py`(실모델 게이트), 새 기능 추가 시 scenarios.py
  한 줄 추가까지가 한 단위(회고 263).
- ✅**노드형 오버라이드 세부에 Temperature 재검토 → 복귀 완료**(2026-07-10 사용자 결정, 같은 날 등재분) —
  실측(pipeline.py:79)상 에이전트 temperature가 모든 노드에 우선 적용되므로 오버라이드 세부에 복귀.
  적용 범위 문구("모든 노드의 모델에 적용") 동봉, 직접형과 공용 TemperatureField로 통합. verify-287에
  존재+페이로드 동봉 단언.
- **RAG 컬렉션 평가 도구**(사용자 제안 2026-07-03, 평가 하네스 1탄 후속) — 검색 품질(히트·유사도·순위)
  수치화. **문서형=✅스펙 140 완료**(rag_hits/score_gte·rag_source_contains·llm_judge). **엔티티형=구멍
  발견(2026-07-12)**: 파일 1개에 N엔티티라 파일명 무가치 + 러너가 hit meta를 버림. → ✅**로더=스펙 311
  완료**(movie-demo 스킬·모델 선택형 엔티티 컬렉션, 회고 285) + ✅**판정=스펙 310 완료**(2026-07-12,
  회고 286): `rag_meta_contains` metadata 부분집합 매칭+러너 meta 노출+프론트 풀·라벨. 단위+통합
  VERIFY310_OK·codex 2건봉인(str(None) 누출·비스칼라 repr)·브라우저 기능왕복. **순위 종합점수
  (recall@k/MRR)·멀티엔티티 OR 매칭은 310 OUT — 필요 시 후속 스펙**(현 조합은 AND).
- **템플릿/프리셋 생성**(방향 4 OUT) — 미리 만든 시작점(조율형 봇·RAG 봇·빈 에이전트). 복제로 부분 충족.
- ✅**평가 하네스 제품화 1탄=스펙 137 완료**(2026-07-03) — 문제집 DB·오염제로 러너·평가 메뉴. ✅2탄(추이+비교)=스펙 138 완료(2026-07-03). ✅3탄(LLM-judge)=스펙 139 완료(2026-07-03). ✅4탄(RAG 컬렉션 러너)=스펙 140 완료(2026-07-03) — **평가 시리즈(137~140) 전체 마감**. 남은 씨앗: 심판 모델 선택 UI·다중 심판 합의·다중 컬렉션 동시 평가·인제스트 품질 진단·장기 추이.
- ✅**모델별 비교+격자=스펙 141 완료**(2026-07-03, 조사 learning 141 기반). ✅골든셋 자동 생성=스펙 142 완료(2026-07-03). 이후 씨앗: 프롬프트 축 격자·judge 신뢰성(심판 벤치마크)·expected 1급 필드·RAG 표준 메트릭(faithfulness류)·인간 리뷰 층·세션→케이스 수확.
- **메뉴별 도우미 에이전트(플랫폼 방향, 사용자 제안 2026-07-03)**: 기본 chat+embedding이 실모델(mock 아님)이면 전용 도우미 에이전트를 가동해 어떤 메뉴·기능이든 돕는 구조. ✅**1탄=평가 도우미(AI 출제)=스펙 143 완료**(2026-07-03).
- **다음 루프 대기열(2026-07-03 갱신2)**: ✅①스펙 148 네이밍 규칙 완료(회고 126, 데이터 초기화 포함) ✅②엔티티 RAG=스펙 149 완료(회고 127 — JSONL 계약+JSON Schema 검증+meta 동반 검색; v2 씨앗: DB 직결/메타 필터 검색/upsert/엔티티용 평가 assert(rag_meta_contains류)/meta 구조 분리) ✅③private→public 승격=스펙 154에 흡수 완료 ④148 잔여 씨앗: rename 시 참조 자동 갱신·casbin per-cap 동반 갱신·페르소나/권한/MCP 폼 e2e
- **현재 모드(2026-07-03~): 사용자 실사용 테스트·보완 단계** — 평가 v1(137~143) 완비, "모두 맘에 드는 건 아님" → 실사용 피드백으로 기능 보완. 새 대형 스펙보다 사용자 보고 기반 교정 우선. 보고 오면: 재현(브라우저/DB 직접) → 진단 → 스펙化 여부 판단. 이후 후보: 컬렉션 도우미(인제스트 진단), 에이전트 빌더 도우미(페르소나 초안), 세션 도우미(요약·분류).
- ✅**회상 진단 위장 버그=스펙 158 완료**(2026-07-04, 회고 136, 실사용 버그 "기억 있는데 유사도 검색 안 됨") — 근인=mem0 숨은 기본 threshold=0.1 상속→저유사도 전부 컷·"정상·0건" 위장(+M1 예외삼킴 부차). 수정=recall_diag threshold=0으로 top-k 표시(낮은점수까지→자가진단)+저장건수 진단+파사드 3분기(챗[]/브로커error/진단표면화)+로그 비밀 마스킹. codex High1/Med1. **후속 씨앗(OUT)**: arctic query-prefix 임베더 주입·재인덱싱 도구·챗 회상 threshold 튜닝(제품 결정).
- ✅**임베더 차원 강제 버그=스펙 159 완료**(2026-07-04, 회고 137, 158 진단이 표면화한 진짜 원인) — 근인=MEM0_EMBED_DIMS가 컬럼차원+임베더요청차원 겹쳐 써 dimensions=1024 강제→snowflake(256만 허용) 400. 수정=네이티브 차원 probe(RAG 방식)해 네이티브==컬럼 미전송·≠면 컬럼길이 전송(정적기본값은 한쪽 깸). 비파괴(11건 보존). codex 2R(정적미전송 회귀→probe, 캐시키·타임아웃·env검증). **사용자 배포본에서 회상 복구 확인 완료**(다른 디바이스 정상). **후속 씨앗(OUT)**: 컬럼 마이그레이션 도구·모델별 컬럼차원 저장·broker 810/931 to_thread.
- ✅**임베딩 query/passage 접두어=스펙 160 완료**(2026-07-04, 회고 138, 158·159 OUT 후속) — 비대칭 모델(e5·arctic) 접두어를 mem0가 무시→action별 주입(설정형 env, 기본 no-op). **측정 우선**: 로컬 e5 접두어 효과 미미 실측→하드코딩 대신 설정형, arctic만 켜게. arctic=query만·비파괴(기존 저장 무변경). codex 결함0. **후속 씨앗(OUT)**: passage 접두어용 재인덱싱 도구·모델별 접두어 UI. **배포본에서 arctic 접두어 켜고 회상 품질 실측 대기**.
- **관측 수동 span/score**(구 방향 2 OUT — 스펙 328에서 Langfuse→OTEL 전환됨) — 자동 계측 위에 커스텀 span/score(평가 하네스 연동)를 OTEL 속성/이벤트로.

### 후속 씨앗 (급하지 않음)
- **다단 승인 큐**(스펙 116·117 OUT) — 다중 gated/A2A cap 순차 위임 시 두 번째 이후 interrupt를 chat.py
  resume 경로가 새 Approval row로 승격(현재는 고아, 안전은 fail-closed 유지). 101/102 다중 interrupt 완전성 갭.
- **A2A 승인 payload args 스냅샷 바인딩**(스펙 117 OUT) — "승인==전송"을 임의 브로커 호출자까지 일반보장
  (재개 간 args 비결정 대비). 기본 orchestrate 경로는 이미 안전.
- **a2a.delegate self-approve 시드**(스펙 117 OUT) — 현재 admin만 승인(fail-closed). 소유자 self-승인(105 선례).

- ✅**비영속 도구 경계=스펙 237 완료**(2026-07-08, 회고 215 — DB 쓰기 능력(memwrite/memedit)만 금지·MCP/RAG 허용, 235 'interrupt 구조적 불가' 가정 실측 반증·승인 경로 계약위반 봉합)

## AgentOps 루프 로드맵 (2026-07-08 채택 — 사용자+외부 에이전트 논의안 검토 후 확정)
> 방향: 피드백→수확→평가→버전 비교→개선의 운영 루프. 제안의 절반은 기존 자산(209 수확·137~143 평가·
> 138 회귀 비교·205 실측)이 이미 커버 — 진짜 갭 4개를 순서대로. Snapshot은 "완전 재현" 대신
> **EvalRun 경량 환경 기록**(진단 단서)으로 경량화(과설계 회피, 필요 실증 시 확장).
- ✅**A. 평가의 버전 귀속=스펙 240 완료**(2026-07-08, 회고 218) — EvalRun.agent_version+env(마스킹·조인), UI 버전 칩·환경 접이식. 다음=B
- ✅**B. 활성화 시 자동 회귀=스펙 241 완료**(2026-07-08, 회고 219 — may_manage 필터·버전 dedupe·자동 회귀 태그)
- ✅**버전 지정 실행(사용자 방향 삽입)=스펙 242 완료**(2026-07-08, 회고 220 — 내부 버전별 서빙(config 소스 전환)·초안 평가=배포 전 게이트·may_manage 403). ✅**243 플그 버전 선택=완료**(2026-07-08 — 헤더 버전 Select·미리보기 배지·인스펙터 버전). **다음=D 운영 화면**
- ✅**D. 버전 운영 화면=스펙 244 완료**(2026-07-08, 회고 221 — /ops 집계+버전 행 칩, codex 4건 수정). **AgentOps 로드맵 A~D 전부 마감**(240~244). 남은 항목=C(수확 맥락 풍부화)·루프 자동화(cron)는 후속 후보
- **C. 수확 케이스 맥락 풍부화** — 수확 시 trace(도구·RAG 흔적) 연결 (후순위 잔여)
- (이후) 루프 자동화: cron 수확+자동 평가. 주의: 자동 회귀는 실모델 전제, 피드백 표본은 👎 편향이라 회귀 비교용.

- ✅**승인 화면 개편=스펙 251 완료**(2026-07-09, backlog stale 정정 2026-07-12) — 복잡도 진단 1위(245 P2: 117블록·컨트롤 233·세로 22배)를 서버 페이지네이션(PagedListShell 재사용)+대기/처리됨 탭+행클릭 상세 드로어로 처방. e2e 9/9·복잡도 22배→2.4배·블록 117→3·컨트롤 233→45. **승인 게이트(어떤 도구 승인 필요)도 도구 등록 "승인 필요" 토글로 설정 가능(177 P1)**. 남은 승인 정돈=승인 게이트 선언 위치 통일뿐인데 그건 권한 재설계 일부(실불편 쌓일 때).
- ✅**code/external 상세 페이지 승격+죽은 코드 정리=스펙 246 후속4 완료**(2026-07-08, 사용자 지적 — DetailPageShell 공용화·AgentDetail.tsx 삭제)

## 진행 중

- (없음)

## 보류 / 후속 후보

- **antd 전환 보류 5건**(스펙 204, 사용자 결정 "교체 18건만 먼저") — ①TrendChart 생 SVG(antd 코어
  무차트—@ant-design/plots 도입은 별 스펙) ②MessageContent/JsonTree(대응물 없음) ③DataTable 모바일
  카드 분기(→List 후보) ④InlineFormPanel·트레이스 카드 겉면(→Card/Form 표준화) ⑤components/Chat.tsx
  죽은 코드 삭제. 재론 시 docs/spec/204 참조.
- **커스텀 impl이 무시하는 설정을 폼이 경고 없이 수용하는 함정** (스펙 201 후속2에서 실사용 확인) —
  plan_execute(도구 미사용 플로우)에도 편집 폼이 mcps 피커를 노출해 사용자가 연결→조용히 무시→"발동
  안 됨" 혼란. 처방 후보: CustomAgent 매니페스트(describe)에 "소비하는 설정 표면" 선언→폼이 미소비
  표면을 숨기거나 경고. 스펙 108(kind-aware 폼)의 커스텀 impl 일반화.

- **능력 브로커 Phase 2 — memory 수정/삭제 + 인가 입도 강화** — Phase 2-a(MCP, 101)·2-b(RAG, 103)·2-c
  (memory **읽기**, 104)·memory **쓰기**(add, 105) 완료. 남은 후속: (a) ✅**memory 수정/삭제 능력=스펙 111 완료** — add(105)와 달리 **대상 mem_id 소유권 검증(053 `_assert_user_owns`)이 선행**(add는 자기 스코프
  생성이라 대상 없음, update/delete는 대상 행이 자기 것인지 확인 필요). 승인 게이트는 105 재사용. (b)
  per-cap·per-user 인가 + 에이전트 소유권(현재 Agent·Collection은 owner 없는 공유 카탈로그 → member에
  kind RBAC 주면 접근 가능한 allowlist 전부 호출 가능; codex 100/101 [P1] #1/#2 수용·명시경계. memory
  읽기/쓰기는 104/105가 principal-도출로 이 빚을 그 kind에 한해 갚음 — agent/mcp/rag는 여전히 공유). (c)
  카탈로그 커지면 벡터/하이브리드 검색(설계결정 10 — 현 rank_candidates는 lexical, 벡터는 OUT). (d) memwrite
  admin owner-only resolve/args 마스킹(codex 105 P2 미문서 경계 후속 — admin은 이미 053 접근이라 저위험).
- **데이터 채널 내부 attribution 강화** — 다중 위임 fold(102 `fold_results`)의 `## 능력:` 라벨은
  데이터 채널 *내부* 표식일 뿐 스푸핑 가능(신뢰 경계는 SystemMessage 격리로 견고, codex 102 설계한계).
  구조화 출력 등으로 내부 attribution 강화하는 후속.
- **노드 간 멱등 재개(선행 위임 결과 캐시)** — 다중 순차 위임 중 뒤 cap이 interrupt하면 재개 시
  delegate 노드가 처음부터 재실행 → 앞 read-only cap 재호출(gated 부수효과는 exactly-once라 안전하나
  관측상 중복, codex 102 [P1]). 다중 interrupt 난제(스펙 101/102 OUT)의 정공법 후속.

## 완료 (요약 — 상세는 각 스펙/회고)

- **첫 설치 예제 정돈 3연작(스펙 303·304·305, 2026-07-12)** — ✅303 seed 트림(고아 페르소나/컬렉션·빈
  세션 제거, 신선시드 실측 2/3/0/5/0) ✅304 테스트 잔해 스윕(dev DB 58→5 에이전트, 프리픽스 화이트리스트
  +seed keeplist 이중가드 `sweep_debris.py`·make 타깃, codex 검증) ✅305 mockData.ts 死배열 제거(BLOCKS·
  ADMIN_AGENTS·ADMIN_SESSIONS+IIFE+MCP_STATUS, 타입14·상수8 보존, tsc0·build✓). 재발 방지=make
  sweep-debris-apply(브라우저 배치 후). 미처리 후속: 일회용 DB per run·mockData.ts 개명(21 importer).

- **인스펙터 정직성 3건(스펙 205, 2026-07-07)** — 전송 프롬프트 콜백 실측·토큰 usage 실측·턴=질문
  순번. 실모델 7/7.

- **도구 다수 시 디스커버 전환(스펙 203, 2026-07-07)** — 임계 10 초과 시 메타 도구(search_tools/
  call_tool)로 컨텍스트 보호, 브로커 미경유(권한 보존), live 전 체인 검증. 후속 씨앗: 벡터 검색(카탈로그
  확대 시)·승인게이트 도구 HIL·오버라이드 드로어 문구.

- **'능력 부여' UI 개편(스펙 199 진단→200 구현, 2026-07-07)** — 카탈로그 Select(판정 키=value)·문장화·역할/유저 분리·도입 문장·종류 6종 완성. e2e 18/18.

- **드로어 모바일 최적화 → Escape 닫기 통일**(스펙 135, 점검 5탄) — 6개 드로어 점검(가로 넘침 0),
  갭=닫기 수단 불일치 → 커스텀 Drawer·인스펙터에 Escape 추가. E1~E5 2회 PASS. 완료(2026-07-03). 미푸시.

- **턴 트레이스 오버라이드 기록**(스펙 134, 점검 4탄) — "오버라이드한 세션 재진입" 질문 진단(오버라이드=
  UI 적용 상태, 세션 무관) → 턴별 trace.overrides+인스펙터 섹션+과거 세션 토스트. codex 2건(적용 가드
  미러·토스트 타이밍) 수정. 완료(2026-07-03, 회고 114). 미푸시.

- **전 메뉴 모바일 점검 스윕**(스펙 133, 점검 3탄) — 11메뉴 390px 순회: 정상 11·수정 2(승인 세로 압착
  버그·블록 탭 잘림). 교훈=정량 지표는 flex 내부 압착을 못 잡음(육안 페어 필수). 완료(2026-07-03). 미푸시.
  후속이던 'Drawer Escape 닫기'는 스펙 135로 완료(마스크 탭 불가는 구조상 수용).

- **플레이그라운드 모바일 헤더 v2**(스펙 132, 점검 2탄) — v1(아이콘만)을 실기기 피드백이 뒤집어
  세로 스택 3줄+온전 텍스트(fullWidth)로. 검증 8/8×2. 완료(2026-07-03, 회고 113+v2 추기). 미푸시.
  **점검 남은 항목**: 인스펙터/오버라이드 드로어·채팅 영역 모바일 최적화.

- **인스펙터 상세화**(스펙 131) — 전송 프롬프트 전문(sentMessages: 캡+개수상한+마스킹)·브로커/RAG 결과
  본문(resultPreview)·노드 값(query/route/delegated 실값). 가림 계보(086/087) 추적해 관문대로 개방.
  codex 4건(무마스킹×2·무상한·부분표면화) 수정. 새로고침 영속 복원까지 e2e. 완료(2026-07-03, 회고
  112·learning 131). 미푸시. 플레이그라운드 점검(사용자 제기)의 1탄 — 후속 점검 항목은 논의로.

- **조율형 RAG 검색 표면화**(스펙 130) — "RAG 검색 안 함" 신고를 진단으로 반증(검색은 동작·표시가 구멍),
  hits/topScore 구조화→trace.brokerCalls(3경로 전수)→인스펙터 "검색 N건·최고 유사도"+관련도낮음 태그+
  메시지 칩 rag 카운트. codex 3건(경로 누락 P2×2·오표시 P3) 수정. 완료(2026-07-03, 회고 111·learning
  130). 미푸시. **후속 씨앗**: 플레이그라운드 UI 개선·기능 점검(사용자 제기 — Scaffolding서 논의).

- **세션 종료 버튼 배선**(스펙 129) — 목업 버튼에 endSession+Popconfirm+드로어 완료 전환+목록 재조회.
  검증이 "백엔드 완성" 전제를 반증 — 첫 실호출 500(commit 후 onupdate 컬럼 만료→MissingGreenlet,
  커밋 성공+응답 실패=거짓 실패 UX)→refresh 1줄 수정. fast-worker 10/10 PASS·DB completed 확인.
  완료(2026-07-03, 회고 110·learning 129). 미푸시.

- **PagedListShell 일반화**(스펙 128) — 127 엔진을 공용 셸로 추출, 세션(프론트 이관+토스트→지속오류)·
  컬렉션 문서(백엔드 페이지 API 신설)·메모리(소비자 재작성) 3면 공유. 컬렉션 목록은 소수라 OUT.
  codex 2건(과도기 요청·토스트 중복)+사용자 신고(드로어 absolute 스크롤 깨짐→fixed) 수정. 완료
  (2026-07-03, 회고 109·learning 128). **후속 씨앗**: keyset(대규모 시). 세션 end 배선은 스펙 129로 완료.

- **메모리 서버 페이지네이션 + 일치/유사도 통합**(스펙 127) — 증가 데이터 대응: list_page 추상 계약+mem0
  raw SQL(20건 캡 버그도 수정)+PagedMemoryList(Segmented 일치|유사도, SessionsView 패턴). 첫 오케스트레이션
  실전(deep-reasoner 조사·fast-worker 브라우저·codex 적대). 완료(2026-07-02, 회고 108·learning 127). 미푸시.
  후속 씨앗이던 '세션/컬렉션 일반화'는 스펙 128로 완료. keyset은 계속 보류.

- **메모리 조회를 드로어→상세 페이지 인라인**(스펙 126) — "넓게 활용". 검색시험 셸이 컬렉션과 공유라
  본문을 RetrievalTestPanel로 추출·드로어는 얇은 래퍼(컬렉션 무변경)·메모리는 상단 Card 전체폭+목록 아래
  (위아래 스택, 사용자 선택). RecallPanel 신설·RecallDrawer 삭제. codex NO ISSUES. 완료(2026-07-02,
  회고 107·learning 126). **미푸시**.
- **메모리 검색 "왜 0건인지" 관측성**(스펙 125) — 다른 노트북 배포서 유사도검색 안 됨+이유 불명. 근인=
  `recall_probe`가 미가용 3사유를 None 하나로 뭉갬+검색예외 500→사라지는 토스트. `recall_diag`(예외 삼켜
  4모드 구조화)+`diag` 필드+프론트 지속 진단패널(백엔드상태·임베딩모델·스코프·오류). 재현불가 환경을
  관측성으로 옮김(고치는 대신 화면에 "왜"). 비밀=실제 api_key 정확치환. codex 2건(마스킹 gaps·실패≠0건)
  수정. 완료(2026-07-02, 회고 106·learning 125). **미푸시**.
- **조율형이 도구/문서/기억 못 씀**(스펙 124) — broker.discover의 어휘 하드필터(`쿼리⊆능력`)가 자연어
  쿼리서 허가된 능력을 전부 떨궈, 조율형이 discover로 아무 능력도 못 찾던 버그. 필터→랭킹 전환(토큰 겹침
  순, 하드 드롭 안 함). allowlist∩RBAC 게이트 불변. verify_124 7/7+브로커 verify 무회귀+codex 없음.
  버그 필터에 의존하던 GREEN 테스트(101 H2·100 P2)는 진짜 불변식으로 교정. 완료(2026-07-02, 회고
  105·learning 124).
- **오버라이드 그룹 헤더 오토글**(스펙 123) — 플레이그라운드 오버라이드에서 그룹 헤더(기억) 클릭이 다른
  그룹(도구) 첫 체크박스를 토글하던 버그. 근인=`Field`가 `<label>`로 PickerGroups(다중 컨트롤)를 감싸
  label 클릭이 첫 하위 컨트롤로 전달. `Field.group`(div role=group)로 수정+Temperature 방어. 회귀
  브라우저 검증(헤더 불변·실제 토글 정상·Temperature 불변)+122 무회귀. codex 여집합. 완료(2026-07-02,
  회고 104·learning 123).
- **사용자 버그 2건**(스펙 121·122) — (1) RAG/MCP 삭제 가드가 **과거 버전** 참조에도 막히던 과엄격을
  **활성 config만**으로 완화(093 전-버전 스캔 완화, usedBy 배지와 재정렬). 부수로 verify_093이 112
  게이트 추가로 조용히 red였음 발견·복구. (2) 조율형 플레이그라운드 오버라이드에서 **설정한 MCP 누락**
  (108 편집폼만 kind로 가르고 109 오버라이드 누락) → OverridePanel kind-aware+chat.py 허용목록+
  isOrchestratorImpl 단일소스. 각 codex clean, 버그2는 브라우저 검증. 완료(2026-07-02, 회고 102·103,
  learning 121·122).
- **에이전트 복제**(스펙 120, 방향 4) — 저마찰 재사용(POST /agents/{id}/clone + 상세 드로어 복제 버튼).
  복제=읽기+새생성→원본 관리권한 불요(가시하면 복제, 사용≠관리)·복제자 소유(069)·행위설정만 복사
  (card 제거). 버튼은 can_manage 밖에 ui/code/external 3 드로어 모두. verify_120 13/13 + 브라우저
  shot-clone-120. 방향 4(마지막) 완료(2026-07-02, 회고 101·learning 120). **4개 방향 전부 소진.**

- **에이전트 평가 하네스**(스펙 119, 방향 3) — 수치 자율(Ralph)의 전제인 결정적 통과율 수치를 내는
  개발·CI 하네스(tests/eval_harness.py: EvalCase·run_eval(cases,run_fn)→score·결정적 scorer trace_has/lacks·
  no_error·output_*). "조용한 초록"을 대죄로 규정→모든 경로 fail-closed. codex rung3 4구멍(빈 asserts
  자동통과·HTTP 실패 숨김·예외후계속 미검증·scorer 예외 전체중단) 봉합. 판별력 실측. 방향 3 완료
  (2026-07-02, 회고 100·learning 119).

- **관측·측정 계층 Langfuse**(스펙 118, 방향 2 — ※역사 기록: 스펙 328에서 Langfuse SDK 제거·OTEL로 대체됨) — 기술스택엔 있으나 코드 0줄이던 Langfuse를 inert-until-
  configured로 배선(키 둘 다 있을 때만 활성·없으면 no-op·graceful·비파괴 config 병합). chat.py 3곳
  (메인·재개·로컬 A2A 서빙), langfuse v4 의존성(키가 스위치). codex rung3: [P2] with_trace 타입 구멍
  (callbacks list 가정)→타입별 접기+회귀가드. 전달 관통 검증(Recorder 콜백). 방향 2 완료(2026-07-02,
  회고 099·learning 118).

- **A2A 협업 실증 + 위임 승인 게이트**(스펙 117, 방향 1) — AgentProvider(kind=agent) 성공 협업을 채팅 1턴
  관통 실증(a2a_stream 결정적 패치: 원격 성공·1회 호출·질의 도달·종합) + approval_for opt-in 게이트
  (config.requires_approval 기본 off=무회귀·전송 이전 interrupt). codex rung3: requires_approval 스키마
  드롭(P1)→AgentConfig 필드+라운드트립 가드, 승인==전송 재개 경계(P1)→문서화, 비-dict config(P2)→방어.
  방향 1 완료(2026-07-02, 회고 098·learning 117).

- **재개 시 선행 위임 결과 보존**(스펙 116, 102 codex [P1] 봉합) — 다중 순차 위임 중 뒤 gated cap
  interrupt 시 재개서 앞 read-only cap 재호출되던 것을, cap 하나씩 delegate self-loop(pending/done
  operator.add)로 소비해 재개 멱등화(cap 하나=체크포인트 경계). codex [P1] 첫 cap 재-discover→plan
  노드 분리로 봉합. 다중 gated 승인 표면화는 OUT(안전 fail-closed 유지). "1~4 루프" 4번(마지막) 완료
  (2026-07-02, 회고 097·learning 116).

- **위임 결과 attribution 견고화**(스펙 115, 102 codex 설계한계 봉합) — 다중 위임 fold의 `## 능력:` 라벨
  스푸핑을 요청별 랜덤 nonce 펜스(⟦BEGIN nonce⟧…⟦END nonce⟧, 라벨은 펜스 밖·nonce는 위임 능력 미노출)로
  위조 불가화. codex rung3: 라벨 자체 위조(cap.name 자원명, P1)→_label_safe 정규화, 단일 raw+지침 불일치
  (P2)→단일도 펜스+지침 조건화. 3런+102 무회귀. 사용자 "1~4 루프"의 3번 완료(2026-07-02, 회고 096·learning 115).

- **화면에 주인 표시 + 비소유 관리 버튼 숨김**(스펙 114) — 112 백엔드 게이트를 UI에 반영. 백엔드가
  owner_id·can_manage를 Out에 실어 내리고(may_manage=assert의 불리언 형제) 프론트는 OwnerTag+버튼
  가드. 브라우저 검증이 놓친 렌더 지점(목록 행 삭제) 포착·수정. verify_114+tsc+shot-owner-114.
  사용자 "1~4 루프"의 2번 완료(2026-07-02, 회고 095·learning 114).

- **런타임 tool 배선 인가**(스펙 113, 112 P0 봉합) — 채팅 런타임이 config mcps/vectorTables 이름으로
  크레덴셜 tool 배선하던 무인가 경로에 인가. 주체=에이전트 **작성자**(채팅 사용자 아님—공유 보존),
  단일 헬퍼 agent_may_wire(NULL-owner 무회귀·특권·자기소유·published·RBAC per-cap). codex rung3:
  override 주입 confused-deputy(P0)→저장본=작성자·주입분=호출자 분리, non-UUID owner casbin 충돌(P2)→
  UUID 선검증. 3런+무회귀. 사용자 "1~4 루프"의 1번 완료(2026-07-02, 회고 094·learning 113).

- **공유 카탈로그 소유권 + per-cap 인가**(스펙 112) — 브로커 인가를 kind→per-cap(`capability:{kind}:{name}`)
  으로 좁히고(축 A, 인가 빚 상환), Agent·McpServer·Collection에 owner_id 붙여 카탈로그 **관리(수정/삭제)**를
  소유자/특권 게이트(축 B). **설계 갈래**=소유권으로 invoke 막으면 공유 에이전트 깨짐→소유권=관리만·사용은
  per-cap RBAC. 게이트 추가가 기존 열린 문(카탈로그 변경 인증만) 봉합. codex rung3: 메모리 3라우트·404-fold
  body·mcp 서버단위 봉합, P0(런타임 tool 배선 우회)는 정직히 OUT→후보로 승격. 백로그 #1의 (b) 완료
  (2026-07-02, 회고 093·learning 112).

- **브로커 메모리 수정/삭제 능력**(스펙 111) — 브로커가 사용자 기억을 수정/삭제(memedit). 대상 mem_id 소유권 선행(남의 기억 못 건드림, 미소유=404-fold)+실행 전 승인(삭제 비가역→관리자만 fail-closed)+principal user_id 고정(anti-leak). 소유권 술어 `memory.user_owns` HTTP와 단일화. 검증 3런(단위+그래프+실mem0)+codex 적대(하중가정 정직화). 백로그 #1의 (a) 완료(2026-07-02, 회고 092·learning 111).

- **엔드투엔드 오케스트레이션 시연**(스펙 110, 106 잔여) — 조율형 에이전트로 채팅 1턴을 돌려 브로커가 실제로 일을 넘기는지 trace의 `broker_invoke:rag:docs_kb` 노드로 확인. 결정적 테스트(verify_110 5/5)+플레이그라운드 인스펙터 스샷. **발견**: 위임은 유저 세션에서만(머신 토큰 deny-by-default)—E2E는 실제 principal 재현 필요(2026-07-02, 회고 091·learning 110).

- **폼 3단계 + 재사용 효율 피커**(스펙 109) — 등록 폼을 기본/하는 일(종류별)/세부설정(접힘) 3단계로, 늘어나는 항목은 재사용 `PickerGroups`(접이식+검색+카운트)로 효율 렌더, **같은 개선을 플레이그라운드 오버라이드에도** 일관 적용(어댑터로 이질 저장 흡수·storage 무변경). 브라우저 등록폼 9/9+오버라이드 6/6(2026-07-02, 회고 090·learning 109).

- **에이전트 폼 유저언어 재구성**(스펙 108) — 106·107 능력 UI를 사용자 세번째 지적(impl 내부어·MCP 두곳 중복·전략어 어려움) 후 뿌리수술: 유저언어(에이전트 종류=직접응답/조율형, 무엇에 맡길까요?)+**종류가 설정면 가름**(직접응답=직접자원칸, 조율형=위임칸만→MCP 한곳 중복소멸). 브라우저 9/9(내부어·기술id 부재 innerText 자동단언)(2026-07-02, 회고 089·learning 108).

- **능력 브로커 UI**(스펙 106) — 편집 폼에 실행 방식(impl) Select + 능력(capabilities) kind별 피커
  추가 → 브로커(100–105 6 provider)를 UI 저작으로 개방. `GET /agent-impls`(레지스트리 drift0)+AgentOut
  capabilities 직렬화; 능력 피커는 cap id `<kind>:<name>` 규약이라 폼이 이미 가진 데이터서 순수 포매팅
  조립(새 카탈로그 EP 불요). 브라우저 10런+왕복+엔드포인트 검증(2026-07-02, 회고 087·learning 106).
  **백로그 2항목(impl 노출·capabilities 편집 Phase 2-d) 동시 소진.**

- **로드맵 12항목**(스펙 033, 034~042) — 2026-06-27 소진.
- **제안 8항목** — #1 conformance(089)·#2 입력히스토리(091)·#3 도구원본숨김(092)·#5 MCP/RAG삭제
  차단(093)·#6 오버플로(095)·#7 메모리검색UI일관(097)·#8 세션검색(098).
- **#4 트리노드 그래프빌더** — 폐기 후 스펙 099(agent-flow 스킬 코드젠, 데모 `route`)로 대체 해결
  (2026-07-01, 회고 080·learning 099).
- **능력 브로커 Phase 1**(스펙 100) — discovery 시임(discover/describe/invoke)+정책 게이트(allowlist∩
  RBAC deny-by-default)+A2A provider+데모 `orchestrate`(서브스텝 조립) 완료(2026-07-01, 회고 081·
  learning 100). codex 3런: #3(untrusted 데이터 채널 격리) 수정, #1/#2(인가 입도) 명시경계로 문서화.
- **능력 브로커 Phase 2-a**(스펙 101) — MCP provider(툴 단위 `mcp:<server>/<tool>`, provider 시임으로
  정책·메커닉 분리) + 서브스텝 HIL(위임 MCP 툴 승인요구 → 전송이전 interrupt, 기존 Approval/resume
  재사용) 완료(2026-07-01, 회고 082·learning 101). integration rung이 설정 지속경로 누락
  (`AgentConfig.capabilities` 필드) 포착·수정. codex 0 actionable(#3 오탐 기각, #1/#2 기존 명시경계).
- **능력 브로커 Phase 2-b**(스펙 103) — RAG provider(kind=rag, `rag:<collection_name>`, 첫 **읽기전용**
  provider). 셋째 provider가 시임 무누수를 재측정(`_permitted` rag 분기 0줄=정책은 정말 provider와 분리).
  invoke는 `search_collections` 코어 재사용+`format_rag_hits` 추출로 엔드포인트·인챗도구·브로커 **세 입구
  한 코어**(drift 0). 읽기전용→`approval_for` 항상 None(정책은 완전 적용=**두 게이트 분리**) 완료
  (2026-07-01, 회고 084·learning 103). 46 ok + 072/100/101/102 무회귀. codex 3판정: [P1]인챗도구
  vectorTables=브로커 밖=정직한 경계(다른 신뢰모델)→스펙 OUT+H4/H5 안전불변식, [P2]질의무제한→공유코어
  4000자 상한, [P2]빈이름 `rag:`→파싱층 방어.
- **능력 브로커 Phase 2-c**(스펙 104) — Memory provider(kind=memory, `memory:user`, 첫 **per-user 소유**
  능력). 100/081이 미룬 **인가 입도 빚 상환**: 공유카탈로그와 반대로 능력 이름에 대상 안 박고 소유자를
  **런타임 principal서 도출**(user_id=`str(principal.id)`, invoke 스코프 오직 `{"user_id":self._user_id}`)
  →이름으로 남 못 가리켜 교차유출 *구조적* 불가+어드민 에스컬레이션 자동차단. 정책 무변경(`_permitted`
  memory분기 0), invoke=`recall_probe` 코어+`format_memory_hits` 추출 공유(drift 0), 읽기전용→approval None.
  완료(2026-07-02, 회고 085·learning 104). verify_104 3런(FakeMem 결정적격리+실 mem0 통합)+084/100/101/102/
  103 무회귀. codex 3판정 P0/P1 없음: [P2]limit 타입미검증→recall_probe clamp, [P2]승인재개 브로커 user_id
  누락→주입(새 상태축=모든 팩토리), [P2]format_memory_hits=격리아님→docstring+비목표 명시.
- **능력 브로커 Memory write**(스펙 105) — Memory write provider(kind=memwrite, `memwrite:user`, **첫
  부수효과·승인 게이트 능력**). 두 방어 겹침: ①쓰기 축=user_id(자기)만·principal 바인딩(104, agent_id 금지
  =051 누출축) ②승인 게이트(031 처방—프롬프트 아닌 구조)=`approval_for` 항상 non-None, memory.add 이전
  interrupt→승인돼야 저장(reject 무저장/approve 1회). 읽기≠쓰기 별도권한(memwrite kind), **소유자 self-승인
  기본**(사용자 결정—member memory.write self_approve 시드, data.delete는 admin 유지), infer=False(승인=저장).
  완료(2026-07-02, 회고 086·learning 105). verify_105 3런(FakeMemAdd+**최소 1노드 graph 승인왕복 LLM불요**+
  실 mem0 쓰기→읽기 왕복)+066/084/100-104 무회귀. codex 3판정 P0/P1 없음: [P2]길이무제한→공유헬퍼 4000자
  (승인한것==저장되는것), [P2]admin 승인열람=053으로 이미 접근(권한델타0)→명시화.
- **전략 교체형 오케스트레이션**(스펙 102) — 브로커 위 오케스트레이션 방식을 **소유자가 고르는 전략**
  으로: 공통 조상 ABC 템플릿(OrchestrationAgentBase가 골격·채널격리·HIL·정책 소유, 자식 유일구멍=
  `select`) + 첫 출하 2전략(FirstMatch[행위보존]·Ranked[결정적 top-k], 둘째구현으로 추상 무누수 측정) +
  agent-flow 스킬 전략 분기(D7) 완료(2026-07-01, 회고 083·learning 102). 40 ok + 무회귀. codex 5건 정직
  분류: [P1]다중위임+중간interrupt 재실행=여집합공격성공이나 안전위반 아님→주석경계+H10 실측(정직화),
  [P2]override홀→@final, [P2]select계약→chosen⊆candidates 교집합, [설계한계]라벨스푸핑→명시, ABC=오탐.

## 실사용 피드백 (C 시리즈 보류 중 처리)
- ✅**페르소나 수정 반영=스펙 161 완료**(2026-07-04, 회고 139) — 페르소나 편집이 에이전트에 반영 안 되던 것(스냅샷 복사). 라이브참조 기각(사용자: 복사=영향도격리 좋음)→템플릿→인스턴스 동기화(오래됨 배지+명시 반영, can_manage 게이트). codex High(usage 가시성 누출) 수정. **후속 씨앗(OUT)**: 페르소나 버전/롤백·저장 후 드로어 유지 즉시 stale·apply 원자 최신본문.
- **C 시리즈(#9 메뉴별 도우미·#10 피드백→평가 수확)는 보류**(2026-07-04, 사용자 "둘 다 백로그로") — 실사용 피드백 우선 처리 모드.
- ✅**mem0 테이블 미생성 목록 502=스펙 162 완료**(2026-07-04, 회고 140, 실사용 버그 초기화 직후 `relation "mem0_memories" does not exist`) — mem0 lazy 생성 테이블을 list_page 직접 SQL이 우회→UndefinedTable→502. 수정=UndefinedTable만 빈 상태로("실패≠0건" 158의 대칭 함정). codex 결함0/Low경계1(문서명시). **후속 씨앗(OUT)**: 리셋 시 mem0 선생성·리셋 UX(기억 0건 안내)·42P01 미초기화vs drop 구분.
- ✅**RAG 컬렉션 사용 공개=스펙 163 완료**(2026-07-04, 회고 141, 실사용 "공개 설정 없어 공유 못 함") — 컬렉션 published 플래그+publish 토글(MCP 미러), "사용만 공개"(수정·삭제는 소유자). codex High(직접 search가 게이트없이 청크 유출)→may_use_collection로 search+documents 봉인. **후속 씨앗(OUT)**: 공개 컬렉션 필터·PII 경고·평가 러너 사용게이트.
- ✅**프로바이더 테스트 "모델 미발견"=스펙 164 완료**(2026-07-04, 회고 142, 실사용 버그) — 프로바이더 레벨 테스트가 빈 model_id로 _probe 호출→무조건 "미발견". 수정=빈 model_id면 목록 개수로 판정("모델 N개 발견"). 프론트 무변경. **후속 씨앗(OUT)**: 발견 모델 목록 응답 포함·embedding 프로바이더 테스트.
- ✅**도구 무발동 진단성=스펙 236 완료**(2026-07-08, 회고 214 — toolDiag 인스펙터 표면화+폼 mock경고+mock 이름언급 일반트리거로 wiki 실발동) — 원래 항목: **도구 무발동 진단성 + mock 모델 한계 (실사용 2026-07-07, 다른 기기서 web-fetch 트리거 안 됨)** — 사용자가 공개·허용호스트·배선을 다 맞췄는데도 web-fetch(위키) 트리거 안 됨. 근인 **모델 층**(폼·배선 아님, 앞선 진단이 다 헛다리): (1) **mock-llm은 tool_call을 `delete_record`·`search_documents` 두 도구·키워드에만** 냄(mock_remote.py `_TOOL_TRIGGERS`) → wiki_search/wiki_page 등 **임의 도구는 mock서 영영 무발동**; (2) 유일 실 도구모델 qwen3.6-35b는 **로컬 MLX(`localhost:8045`)=이 Mac 한정** → 별도 배포엔 실모델 부재 → mock 강제 → 무발동. **진단성 갭이 핵심**: 세 게이트(공개·허용호스트·배선) 다 통과해도 **조용히** 무발동, "왜"를 표면화하는 신호 0 → 사용자가 한 세션 내내 엉뚱한 층 추적. 처방 후보: (a) 에이전트 모델이 mock일 때 폼/플그에 "이 모델은 도구를 호출 못 함(실모델 필요)" 표면화; (b) 도구 바인딩됐는데 모델이 tool_call 무발화 시 인스펙터/트레이스에 "모델이 도구를 호출하지 않음" 진단(회상 진단 158·검색 진단 125의 결); (c) mock 트리거를 등록 도구 일반으로 확장(실습성) 또는 최소 web-fetch 키워드 추가. **관련**: 71–74줄 "폼이 무시 설정 수용"(스펙 201 후속2, 다른 층=폼 게이트)은 스펙 202/206서 일부 해소.

## 지속 검증 체계 (사용자 제기 2026-07-04 — 자가검증이 관대함)
- ✅**축2 다디바이스 UI 오버플로 감사=스펙 165 완료**(회고 143) — `tests/browser/ui-audit.mjs` 하네스(전수 순회+수치판정+스크린샷). 원리=도구가 좁히고 육안이 확정. 파일럿으로 batch 버튼잘림 1건 발견·수정. ✅축1(사용 시나리오 감사)=스펙 166 완료(회고 144, J1·J2 7단계 ok·막힘0, 핵심경로 건전·초안 대화 잘 처리). ✅축3(문구·평이함 감사)=스펙 167 완료(회고 145, 내부 산출물 누출 12건 수정). **3축 파일럿 완료.** ✅드로어/모달 오버플로=스펙168·✅감사 커맨드화+스킬=스펙169(`/ui-audit`·audit-all.mjs, 회고147) 완료. **검증 아크(165~169) 마감.** **다음 후보**: 자율 감사 cron 실제 등록, 카피 축 기계화(LLM judge), 감사 커버리지 확장(세로잘림·중첩드로어), 또는 새 기능 방향(C시리즈 buddy agent·피드백 수확). ✅**RAG 공개/비공개 제거=스펙 172 완료**(회고 150·163 되돌림): 사용자 교정—public/private·공개/비공개 개념 RAG서 전면 제거, 사용=전부 공용(익명 401)·관리 소유자만. 별명 편집(실제 의도)=스펙 173 완료(회고 151, 편집 드로어 노출). ✅**메뉴 감사=스펙 174 완료**(회고 152): 관리자 그룹 5개 서버 강제 확인·프로바이더·모델(상단이나 변이 관리전용)을 관리자 그룹으로 이동. RAG 임베딩 UX=스펙 175 완료(회고 153). RAG 별명 편집 발견성=스펙 176 완료(회고 154, 행 편집 연필 버튼+전용 모달, 문서 드로어 설정패널 제거). ✅**승인 재개 impl-drift 가드=스펙 171 완료**(회고 149): deep-reasoner 적대 검토로 승인 로직 점검→유일 Low(stale 주석·impl 교체 재개)를 명시 가드로 닫음. 잔여(pre-migration pending 행·완전 런타임키 스냅샷)는 문서화. ✅**평가 도구 정직성=스펙 170 완료**(회고 148): 평가 통과≠도구 호출을 성적표 배지+출제 안내로 표면화. 후속: 메모리 vs 히스토리 의문①=**조사 완료**(learning 143)—mock이 추출 무너뜨려 안 보임(실 모델서 demo-mem-vs-history.mjs로 크로스세션 1 mem 실증 가능)·info-circle 아이콘 잔존 버그(AgentsView:1950, 맵키 info). ✅**드로어·모달 오버플로 감사=스펙 168 완료**(회고 146, 14/14·FAIL0 오버레이 반응형 건전, learning142 부산물). 후속 씨앗: 모바일서 현재 메뉴 재탭 시 사이더 백드롭 안 닫힘(controlled Menu onSelect 같은key 재발화 안 함, 실동작 경계). **축3 후속(백로그)**: mem0 라이브러리명 노출(백엔드 시드 memory type 이름)·`차원` 글로스·배치/프로바이더 admin jargon(SQL LIKE·grant·keep-list)·영어 enum 태그(kind·transport)·용어 사전 상시화.

## 구조 리뷰 후보 (스펙 182/183 발견, 2026-07-05 — deep-reasoner 2병렬 OCP/HoC 점검)
> 사용자 신념("당장 구현보다 구조") 점검. 백엔드 OCP·프론트 HoC. 결론: 소스 대체로 건강(메모리 백엔드·에이전트 런타임·서빙 MCP·remote축=진짜 레지스트리 OCP, DIP/LSP 준수). 정리감은 아래.
- ✅**source 제1자/제3자 축 술어=스펙 183 완료**(회고 164) — is_remote_source 자매 축 미적용 봉합(리터럴 7곳→술어).
- ✅**브로커 kind 파싱 OCP=스펙 306 완료**(2026-07-12, 회고 281) — `_kind_of`·`_cap_resource` 하드코딩 if-체인을 단일 `_PREFIXED_KINDS` 레지스트리+`_strip_kind` 프리미티브로 흡수(새 kind=한 곳 등록, `_cap_resource` 누락→per-cap RBAC 조용한 오추출 함정 봉인). provider 계약 `resource_of` 대신 데이터 레지스트리 택함(5 kind 추출 균일→per-provider는 과추상, 파싱 context-free). 순수 리팩터=옛 if-체인 오라클 박제 대조(바이트 동일)·드리프트 핀 introspection(codex 지적). verify_306 105/105·브로커 verifier PASS·codex 여집합 실패. **잔여**: provider `matches`/`resource_of`는 비균일 kind 생기는 날 트리거(YAGNI).
- **broker.py 1180줄 단일 모듈** → provider들을 `broker/` 패키지로 분할(응집도 높으나 파일 격리 개선). 낮음.
- ✅**프론트 useAsyncData/runWithToast 훅=스펙 184 완료**(회고 165) — `admin/src/hooks.ts`. 소비자 3곳 변환(AllowedHosts·Memory 2탭). ✅**나머지 11 useAsyncData 뷰 이관=스펙 308 완료**(2026-07-12, 회고 283): 10 이관·1 정당 skip(SessionsView `messages`=로컬 낙관 뮤테이션→setter 없는 훅 부적합, 선례 useAgents). tsc0·build✓·브라우저 8/11 네트워크 실증. 폼시드 패턴(SettingsView류)은 훅 부적합—제외. ✅**runWithToast 이관=스펙 309 완료**(2026-07-12, 회고 284): 40 try/catch 중 27 이관·10 skip(읽기·결과분기2결말·409분기=계약 불일치). 훅 `errorPrefix?` 확장으로 프리픽스에러 6곳 무손실. tsc0·build✓·errorPrefix 4/4·브라우저 왕복(성공토스트·결과소비·원복). 에러규칙 3분(P/C/X) 보존이 핵심.
- ✅**AgentsView.tsx 분해=스펙 185 완료**(회고 166·167): **Phase A**(서브컴포넌트 8개 파일분리, 2128→747줄)+**Phase B**(useAgents 훅으로 데이터 오케스트레이션 격리, 747→684줄). tsc0·브라우저 회귀 2종 ALL PASS(파일분리 3드로어/폼/모달 + 뮤테이션 왕복 커스텀토스트 보존)·스샷. runWithToast 미채택(커스텀 플로팅토스트 보존). ~11개 뷰 useAsyncData 이관은 ✅스펙 308서 마감(위 항목).
- **HoC는 불필요**(리뷰 결론): AuthGate(render-prop)·PagedListShell(제네릭)이 HoC 니치 이미 덮음. 권한 게이트는 표현 분기(인라인/조각). 넣으면 과설계=신념 배신.
- **테스트 부채(183서 발견)**: verify_152 V4 "code→400" stale(154가 code 노출 허용, 단언 갱신 필요)·verify_083 노출게이트 5건 404(라이브 인프라/시드 의존).

## antd v6 deprecation 전면 마이그레이션 (스펙 207서 관측 → ✅스펙 208 완료, 2026-07-07)
- ✅**스펙 208 완료**(회고 196): 관측 3종 전수 처리(Alert message→title 30·Drawer width→size 13·List→Flex 4), 완료기준=콘솔 deprecation 경고 0건 달성. 공용 래퍼 Drawer는 내부 1곳만 고쳐 소비자 무변경 커버. **후속 씨앗(OUT)**: 다른 v6 deprecation(bodyStyle·destroyOnClose·Card bordered 등)이 감사에 새로 뜨면 그때 처리.

- [ ] 노드형 인스펙터 노드 행 정보 확충(추후, 스펙 262 후속) — 노드별 모델·출력형식(JSON) 배지·carry/clean 표식 등. 지금은 실행 흐름에 이름·시간·요약·격리 노트까지.

- [ ] 노드형 "마지막 노드만 응답으로" 옵션(스펙 264 관찰) — 중간 노드 출력(계획 등)이 최종 답 앞에 스트림돼 섞임(원 plan_execute는 plan 무토큰). 중간 노드는 인스펙터만·최종 노드만 사용자 응답으로 하는 노드/에이전트 옵션 검토.
- [ ] 노드형 기억: 장기 미선택(단기만) 노드의 "조용한 회상 없음" 안내(스펙 268 주의 — memory_enabled는 장기 블록만). UI 힌트 or 게이트 표시 검토.
- [후보] 기본 public + 생성자 축 분리(번호 미정 — 285는 resync가 사용) — 284에서 분리(2026-07-10): 현 모델 공개=owner_id 소멸이라 "기본 public+내 것 tint" 양립 불가. created_by 신설(마이그레이션)+147 가시성 게이트(404-fold·복제·A2A·메모리) 재설계. RBAC 체크리스트+codex 적대 필수.
- 네비 메뉴명 "메모리" vs 화면 어휘 "기억" 통일 검토(회고 261 — 286서 상세만 통일, 반쪽 상태)
- shot-agent-policy-147·shot-naming-148 e2e — 284(소유 태그·필터 소멸)로 대상 표면 소멸, 수리 또는 폐기 판단 필요(286서 발견)
- antd v6 deprecation 신규 관측: Descriptions labelStyle→styles.label (154 콘솔, 208 규칙에 따라 후속)
- ✅**낡은 verify 스크립트 수리=스펙 307 완료**(2026-07-12, 회고 282) — verify_036(밑줄→대시 네이밍)·verify_056(일회용 DB 격리 러너로 결정화)·verify_061(seam 개명+시그니처 추종) 마감. **100·101·103은 stale 아니라 인프라**(dev 서버·mock MCP·임베딩 필요)로 재분류=서버 띄우면 exit=0. 러너 `tests/_throwaway_db.py`(virgin DB 생성·seed·격리·drop) 신설. ~~verify_038~~은 291 Phase2 회귀로 이미 수리. 교훈: stash 차등은 미커밋만 걷어냄.
- [후보] verify_100_broker.py P1 사전 실패: _FakeAgent에 active_version 속성 없음 — 스펙 256 위임 게이트(active_version 검사) 이후 픽스처 미갱신. 원본/분할판 동일 실패(2026-07-11 Phase 3b-2서 차등 확정). 낡은 verify 3건(036·038·056)과 같은 부류.
- ✅[스펙302 해결] verify_103_broker_rag.py(실은 컬렉션명 밑줄 금지)·verify_130/131(invocations[0] IndexError) P1 사전 실패: 스펙 294서 pristine HEAD 동일 실패로 차등 확정(내 변경 무관, 낡은 mock/픽스처). verify_100과 같은 stale verify 부류 — 일괄 갱신 대상.
- ✅[스펙302 해결] verify_190: **stale 아닌 실 프로덕션 회귀**였음 — produce_node 애노테이션 `RunnableConfig | None`이 langgraph 1.2.5 문자열매칭 주입판정 실패→artifact 크래시, `RunnableConfig`로 복원(회고 277).
- [후보] 스펙 296 = 남은 공통화 B: api A2A 프레이밍 3중(mock_remote↔a2a_server)·get-or-404 인라인 36곳→db.get_or_404·_card_streaming·_assert_valid_name→naming·_non_blank. authz _own_scope/_is_admin은 저자 의도(라우터 독립)라 설계판단+적대검증 별도. eval_* 계열 중복은 미전수(추가 조사).
- ✅**스펙 297 = get-or-404 정본화 완료**(2026-07-11, 회고 272). session.get+404 관용구→`db.get_or_404[T]`(PEP695). 전수=**37곳**(예상 36 아님): 1차 분류 33 + 견고 스캐너가 잡은 멀티라인·꼬리주석 near-miss 4(eval_cases2·eval_authoring2)—"정규식 놓침을 무해로 방치"가 census-lens 재발이라 전량 편입. 순수 PK-get만·결합게이트 제외·존재-404→assert_may_manage 순서보존. verify_112/147/148/104+스위트 51/51·codex 여집합 결함0. **에이전트 dedup 4연작(294~297) 마감.**
  - [잔여 백로그] eval_* 내부 중복(미전수)·stale verifier 일괄 갱신(100/103/130/131/190/084).
- ✅**스펙 298 = authz 스코프 + LIKE-escape 정본화 완료**(2026-07-11, 회고 273). census(deep-reasoner 전수)의 최저위험 2건: (A) LIKE-escape 3중 바이트 동일→신설 `sqlutil.like_escape`, (B) authz `_agent_id_map`(2중 동일)→`serializers.agent_id_map`·`_is_admin`(튜플만 차이)→`authz.is_admin_for(p,obj,act)`·`_own_scope`(동일)→`authz.own_scope(p,obj,act)`. 호출부가 자기 튜플 명시=라우터 독립 보존·골격 단일화. 크로스모듈 private import 2건(rag→sessions._like_escape·chat→sessions._own_scope) 제거. 로컬 정의0·verify_066/067/112/147/177+스위트51/51·codex. **놓친 시임=단위 verifier가 `S._is_admin` 직접참조**(몽키패치 아닌 모듈속성 호출)→정본 위치로 갱신.
- ✅**스펙 299 = end_session 쓰기 스코프 정합 완료**(2026-07-11, 회고 274). `authz.own_scope_write(principal)` 신설(옛 sessions._own_scope_write 승격+machine 분기)로 3 write 라우트(end+feedback PUT/DELETE) 정본. sessions:read 운영자가 타인 세션 종료하던 결함 정정(machine/superuser/owner/member 불변). verify_067_scope M3(운영자 read=None/write=str(id) 대비)·067_live·스위트51/51·codex 7축 결함0. **인접발견도 census부터**=write 라우트 전수해 버그 격리 확인.
- ✅**스펙 300 = llm_cfg 빌더 정본화 완료**(2026-07-11, 회고 275). census 후보 C. `{base_url, api_key: crypto.decrypt, model_id}` 조립을 `mem_config.model_usable`(TypeGuard)+`llm_cfg_of` 원자로 **8곳** 단일화(census-lens=서브에이전트 eval 3곳→전역 grep 8곳 핫패스 포함, 사용자 AskUser 전체원자). dedup vs mypy narrowing=TypeGuard(TypeIs 불건전)·비밀 홈=serializers 회피·술어는 메시지 같을 때만. metrics-fast0·스위트51/51·codex.
- ✅**스펙 301 = eval 배경 작업 스캐폴딩 정본화 완료**(2026-07-11, 회고 276). 4개 배경 작업 반복 스캐폴딩→원자 4(`_job_lock` discard-only·`_next_order_idx`·`_apply_completion_marker`·`_stamp_failure`)+`_execute_append_job`(suggestion+append ~90% 콜러블 주입 통합). generation/harvest 원자만 차용. verify_209_harvest 10/10·스위트51/51·codex 7축. **팬텀 회귀 교훈**: `--reload`+배경태스크+동시 스위트=verifier 플래키(태스크 kill·루프 점유→10초 폴 초과), 계측 타임라인으로 코드무결 확정. **census dedup 후보 A~D 전부 소진**(298 A·B, 300 C, 301 D).
  - [잔여] 배경 verifier 폴 타임아웃(10초)이 스위트 동시 실행 시 짧음—격리 실행 문서화. eval_* 내부 잔여 중복 미전수.
- ✅**스펙 302 = stale verifier 정리 완료**(2026-07-11, 회고 277). 6개(084/100/103/130/131/190) 전수 진단→수선. **190은 stale 아닌 실 프로덕션 회귀**=artifact produce_node config 애노테이션이 langgraph 1.2.5 주입 판정 못 통과(문자열매칭·PEP604 유니언), `RunnableConfig`로 복원(artifact 계열 실사용 크래시 해소). 픽스처 5는 시그니처/명명/컬렉션 드리프트 추종. 6/6 PASS·codex 결함0. **교훈: 실패 verifier "낡았겠지" 방치가 실 회귀 은폐**.
- ✅**스펙 302 후속 = agent hot-reload 봉인**(2026-07-11). `main.py:run()`(uv run api)이 `uvicorn.run(reload=True, reload_dirs=[api_src, agent_src])`로 **두 워크스페이스 소스를 다 watch** → 그간 packages/agent 미watch로 노드/flow 수정이 자동 반영 안 되던 함정(302 회귀가 오래 숨은 근원) 봉인. WatchFiles가 agent 파일 touch에 리로드 발화 실측. 배포는 uvicorn 직접(reload 없이).
- ✅[스펙302 해결] verify_084: 몽키패치 lookup지점 이동(api.agents.memory_routes)+FakeMem threshold kwargs 흡수(회고 277).
- ✅**verify_061 수리=스펙 307 완료**(2026-07-12, 회고 282) — 원인은 chat.stream_local_reply가 아니라 seam 개명(`_load_exposed_ui_agent`→`_load_exposed_agent`)+`exposed_agent_a2a` 시그니처 드리프트(request/`_principal`). 실호출 이름으로 재지정+시그니처 추종+`_agent_a2a_skills` 패치로 exit=0.
- ✅**노드형 확장 3연작(316·317·318) 마감**(2026-07-13, 회고 291·292·293): ①등록 노드+버전핀 참조 ②코드 노드(kind=code, CustomNode Protocol) ③노드→에이전트 호출(`agent__{id}` 도구·브로커 위임). 사용자 요구="잘 만든 노드 관리"+"노드형에 에이전트 호출"을 스펙 의존순으로 분할.
  - ✅**파이프라인 도구 결과 통일 인젝션 펜스=스펙 319 완료**(2026-07-13, 회고 294): 조율형 데이터 채널 격리(nonce 펜스+방어지침)를 파이프라인 도구 결과(MCP·RAG·에이전트) 전체에 통일. toolbox.fence_wrap 신설(조율형 fold_results 재사용=단일출처)·ToolNode 후처리 래퍼로 ToolMessage 펜스·모든 노드 sys 정적 방어절. 옵션 A(도구 빌더 래핑) 기각=DefaultUiAgent·plan_execute 폭발반경, 파이프라인 국소가 안전. VERIFY319_OK+회귀 7종·codex P1/P2 0(P3 sentMessages=ground truth 정직화). **OUT**: LLM 인젝션 100% 불가(하한만)·코드 노드는 신뢰 저작이라 펜스 밖·향후 코드 노드 도구 결과는 저작자가 fence_wrap 직접 사용.
  - ✅**도구 실행 실패 사유 인스펙터 표면화=스펙 320 완료**(2026-07-13, 회고 295): 도구 실패 시 사유 문자열(error 필드·마스킹+캡)을 MCP·RAG·브로커 세 표면에 렌더. **핵심 함정**=langchain-mcp-adapters가 MCP isError를 handle_tool_error로 삼켜 정상 문자열 반환→status=ok 오기록(예외 raise 단위 fake는 못 잡고 진짜 MCP 태운 기능 rung만 드러냄)→rt.handle_tool_error=False로 예외 전파. codex: **P1a**(브로커 MCP provider도 삼킴 잔존=형제 표면 비일관)→provider.invoke 동일 수정·**P1b**(사유가 새 누출 표면)→_SECRET_RE에 URL userinfo·Basic 추가(공용 마스커 전체 강화)·**P2**(failing_op seed 오염)→seed 제외+전용 임시 서버 hermetic. VERIFY320_OK(U1~U8)+UI 11/11·회귀 6종.
    - **[P3 후속]** 메시지 요약 칩의 브로커 MCP 실패 카운트 누락(`DebugChat.tsx:939`가 trace.mcp만 세고 brokerCalls non-rag 실패 미포함). 인스펙터 카드는 정합, 상단 칩만 어긋남 — 320 핵심(카드 표면화) 밖의 요약 신호 정합.
    - **[stale verifier]** verify_125 "E 정상" 실패=사전 stale fake(`memory/__init__:182 search(..., threshold=0.0)` 스펙158를 `_FakeBackend.search()` 미수용). 320 변경 무관(정규식이 TypeError 못 냄). stale verifier 일괄 갱신(100/103/130/131/084 부류)에 편입.
  - ✅**요약 칩 브로커 MCP 집계(320 P3)+stale verifier 재스코프=스펙 321 완료**(2026-07-13, 회고 296): ①P3=DebugChat mcp 칩이 브로커 mcp:* 실패 미집계→rag 대칭 미러 ②verify_125 threshold fake→`**_kw` 18/18 ③`_verify*` 고아행 전량 삭제+delete_record 승인정책(HIL) 복원. **재스코프**: "stale verifier 일괄 정리"=실은 verify 스위트 격리 문제(159개 raw sweep→상태오염·cwd·전제조건·fresh-seed 거짓실패+sweep가 DB 변이). rediscover 승인보존은 무결(스펙177), 드롭은 sweep 테스트 변이.
- [ ] **verify 스위트 격리 하네스**(대형, 2026-07-13 스펙 321서 도출) — 159개 raw `verify_*.py`가 공유 라이브 DB·cwd·전제조건에 얽혀 함께 못 돌린다(전수 sweep=대량 거짓 실패+DB 변이). 유지 회귀는 `make suite`(큐레이션 51/51)뿐. 필요 시 fresh-DB-per-run 격리 또는 curation. **✅Phase 1 완료=스펙 385**(2026-07-16, 회고 387): ASGI 인프로세스 33개(http의 1/3)를 `asgi` 층으로 분리해 스크립트마다 virgin DB(_throwaway_db 재사용, 새 하네스 0줄)로 실행 — SUITE_OK·라이브 DB 무접촉(행수 증명)·233 격리해제. virgin DB가 격리 사유 심판: "오염" 13건 중 12건이 노후로 반증(사유 정직 갱신). **남음 Phase 2**: 라이브 :8000 층 66개(live 46+혼합 12+기타 8) — 전용 uvicorn(임시 포트+임시 DB) 기동 하네스 + 하드코딩 8000→`VERIFY_BASE` env 치환 58파일(fast-worker 기계 작업). **주의**: verifier 스위트 작업은 reseed 기준선 전제(단 dev 도그푸딩 데이터 소실=사용자 결정). 개별 stale 후보 미처리: 029(agents.py→agents/ 분할)·127(infer kwarg)·158(threshold 기본값)·083/059(fresh-seed 가정).
    - [메모] 2026-07-13 sweep가 dev DB를 변이시킴(delete_record 승인 복원 완료, 그러나 059/083/101 등 fresh-seed 가정 실패는 잔존 — 실사용 무영향, 정식 수복은 reseed 필요).
- ✅**custom MCP 기본 공개(오픈)+published 설명=스펙 322 완료**(2026-07-13, 회고 297): 사용자 지적 "published가 MCP 사용 필수인 게 UX상 잘못"→서빙 custom MCP 시드 기본값 published=False→True(두 경로+기존 dev DB flip)+BlocksView "공개(외부 서빙)" 설명 보강(긍정문). 숨은 결합=custom은 served_url로만 접속·그 엔드포인트가 published 게이트라 사실상 published=사용조건(build_mcp_tools 연결실패 조용히 스킵→도구0 footgun, 측정 확증). 재공개 가드 유지. verify_156/211✓.
- ✅**백엔드 리팩토링 캠페인 Tier 1+2 완주**(스펙 374, 2026-07-16) — codex 4그룹 비판리뷰(활성버그0·전부 구조/드리프트) 위 위험오름차순 3-tier. **Tier1 DRY단일화**: 375 MCP캡·376 RAG임베딩검증·377 eval admission. **Tier2 파일분할·계약변경**: 378 schemas→9모듈·379 models→11모듈·380 runtime→rag_runtime·381 rag.py→`rag/`패키지(4도메인+shared)·382 chat_context ctx dict→ChatContext DTO(핫경로 7파일 ~211사이트, mypy가 완전성 그물). 전부 동작불변(SUITE_OK·e2e39·mypy 베이스라인외0·수치보존) per-spec 커밋·**미푸시**. 부산물: verify_049 격리해제(스펙291 _create_approval 드리프트 봉합). 기법=learning 381(verbatim슬라이스+__init__재수출+지연import)·382(mypy 소스그물·tests는 밖·required-not-optional·단일생성). **남음=Tier3**(god-function 수술): chat.py→ChatTurnService·eval_runs app service·jobs.py 파괴잡 plan/execute·pipeline build_graph — 파괴/핫경로라 **출하 전 codex 적대 리뷰 필수**, 별도 착수.
