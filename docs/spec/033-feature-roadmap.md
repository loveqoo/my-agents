# 033 — 기능 로드맵 (12개 항목 의존순 배열)

상태: **합의 — P0(세션 페이징)부터 시작. 후속 페이즈는 진행하며 재검토(순서 변경 가능).**
날짜: 2026-06-27
브랜치: `feat/agent-service`
배경: 사용자가 제기한 12개 문제/질문(세션·유저·메모리·provider·RAG·A2A·승인)을
코드 현황 전수 조사(서브에이전트 4종 병렬) 위에서 **신설 필요 항목만** 의존순으로 배열한다.

---

## 현황 한 줄 요약 (조사로 검증한 사실 — file:line 근거 보유)

- **#1 세션**: (에이전트, session_id) 단위 컨테이너. `user_id`는 소유자가 아니라 "마지막 mem0 축"
  태그(nullable). **유저 없는 대화도 세션에 포함**(user_id=None), distinct 목록에선 제외. (`models.py:148`, `chat.py:154/264/361`, `sessions.py:49`)
- **#4 유저 관리**: 어드민(superuser/`users:manage`) 전용. 공개 가입 비활성. (`user_admin.py:22`, `main.py:75`)
- **#5 "로컬"**: `source="local"`은 DB 컬럼. env 시드는 초기 admin 1명뿐. provider 등록형 아님(LDAP/OIDC는 seam). (`models.py:222`, `users.py:136`)
- **#7 메모리**: mem0 강결합. 공개 함수 시그니처는 backend-agnostic이나 내부 100% mem0. 인터페이스 없음. (`memory.py:126`)
- **#8 Provider**: 모델 행의 문자열 컬럼일 뿐. 별도 엔티티 없음 → 모델마다 base_url/api_key 반복. (`models.py:77`)
- **#10 vectorTables**: agent.config에 저장만, 런타임 미소비(죽은 필드). (`chat.py`/`runtime.py` grep 0)
- **#11 A2A**: 카드 등록만(026 1차), 실호출 placeholder. MCP 도구도 현재 합성 모의. (`chat.py:343`, `runtime.py:46`)
- **#12 승인**: DB 큐(사후 추적)만. langgraph checkpoint/interrupt 런타임 미사용. (`approvals.py`, grep 0)

---

## 페이즈 (추천 순서)

각 페이즈는 별도 스펙(034~)으로 분리해 per-spec 커밋한다.

### P0 — 세션 페이징 (#2) · 워밍업
- **무엇**: `GET /sessions`에 limit/offset(또는 cursor) + 총계. 프론트 `SessionsView` 페이지네이션.
- **왜 먼저**: 완전 독립·작음, 다른 페이즈와 안 엉킴. 빠른 가치.
- **규모**: 작음. **의존**: 없음.

### P1 — Provider 엔티티 (#8) · 토대
- **무엇**: `Provider`(name, base_url, api_key, kind/protocol) 엔티티 신설 → `ModelConfig`가 provider를
  FK로 참조. provider 1회 등록 → 하위 모델 나열. 어드민 UI에 Provider 탭.
- **왜 여기**: RAG(임베딩 provider)·메모리(모델 선택)·UI가 이 위에 깔끔히 얹힘. 레지스트리 단일출처 강화.
- **참고**: LiteLLM/OpenRouter류 provider 추상화.
- **규모**: 중(레지스트리 리팩터 + 마이그레이션). **의존**: 없음(기존 모델 행 → provider로 승급 마이그레이션).

### P2 — RAG 지식 파이프라인 (#9+#10) · 코어 가치
- **무엇**: (a) 문서 업로드(PDF 등)→chunking→embedding→pgvector 적재 인제스트. (b) `vectorTables`를
  살려 에이전트에 **retrieval tool**로 연결(검색/질의 가능). 
- **분할**: P2a 인제스트(업로드·청킹·임베딩·상태), P2b retrieval tool(에이전트 런타임 연결).
- **왜 여기**: P1의 임베딩 provider 위에 얹음. "구조 속 지식" 핵심.
- **규모**: 큼. **의존**: P1(임베딩 모델/provider 권장).

### P3 — 스케줄러 + 정리 (#3+#6) · 인프라 토대
- **무엇**: 크론/배치 토대(예: APScheduler 또는 외부 크론+엔드포인트) → 오래된 세션 보존정리(#3),
  유저 메모리 요약·재적재(#6).
- **왜 여기**: RAG·메모리 데이터가 쌓인 뒤 정리 니즈가 실제가 됨. 한 토대로 둘 다 얹음.
- **규모**: 중. **의존**: 약함(세션/메모리 위에서 동작).

### P4 — 메모리 백엔드 추상화 (#7) · 코어 확장
- **무엇**: 메모리 Protocol/ABC 추출(현 mem0 호출을 어댑터 뒤로) → 그래프DB 백엔드 drop-in 가능.
- **왜 여기**: 인터페이스 추출 리팩터. P2/P3로 메모리 사용처가 안정된 뒤가 안전.
- **규모**: 중~큼. **의존**: 약함(메모리 사용처 안정화 후 권장).

### P5 — 오케스트레이션 (#11+#12) · 런타임 대수술
- **무엇**: (a) langgraph checkpoint/interrupt로 실제 HIL 승인 게이팅(#12) — 현 사후 큐를 런타임 제어로.
  (b) A2A 실호출(026 2차, #11) — @mention/트리거/sub-agent 도구 설계 포함.
- **왜 마지막**: 현 런타임(`create_react_agent` astream)을 가장 크게 바꿈. 위험 큼.
- **규모**: 큼. **의존**: 런타임 안정 선행 권장.

---

## 사실 답변으로 종결(스펙 불요)
- **#1**: 세션 정의 설명 완료. 단 "유저별 소유"가 필요해지면 P-별도(세션 user_id를 태그→소유자로) 검토.
- **#4 / #5**: 현 구현이 의도대로 동작(어드민 전용 / local=DB+초기 admin env). 변경 요청 시에만 스펙.

---

## 합의 필요 (검토 포인트)
1. 페이즈 순서 — P0→P5가 적절한가, 아니면 코어(P1/P2)를 더 앞당길까.
2. P2(RAG)·P5(오케스트레이션)는 큰 덩어리 → 추가 분할 필요 여부.
3. 스케줄러(P3) 방식 — 인프로세스(APScheduler) vs 외부 크론+보호 엔드포인트.
4. 시작 페이즈 확정(기본 제안: P0 워밍업 → P1 토대).
