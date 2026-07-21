# 408 — 모델 능력 관리(capabilities): 스트리밍·thinking·비전

> 상태: **완료** · 2026-07-19 · verify_408 21/21 + e2e(단건 배지) + 기존 e2e 3종 무회귀 + make test SUITE_OK(배타 89/0/격리0) + metrics-fast · codex P1×3+P2 반영
> 발단: 개발자 "스트리밍 처리 여부 관리 + 대화 표시" → 논의로 확정한 2층 원칙 —
> **능력(capability)=모델이 선언하는 사실 / 사용(usage)=능력의 부분집합에서 선택**
> (A2A 카드·MCP enabled_tools와 같은 집 패턴). 실측 근거: MLX 가이드(스트리밍=능력 있음·클라가
> 켬 / thinking=모드 보유·기본을 클라가 관리 — 후자는 params.enable_thinking으로 이미 배관됨).

## 설계(2층 + 설정 캐스케이드 — 개발자 확장 승인)

- **능력 층(신설, 오버라이드 불가)**: `ModelConfig.capabilities` JSONB — `{"streaming": true,
  "thinking": false, "vision": false}` 기본. 서버가 자체적으로 껐다면 관리자가 사실을 기록.
  에이전트는 능력을 못 바꾼다(없는 능력을 켤 수 없음 — 부분집합 원칙).
- **설정 층(사용값, 캐스케이드)**: **모델 params(기본) → 에이전트 config.modelParams(부분
  오버라이드) → 세션 오버라이드(기존)**. 각 층은 바꿀 키만 명시, 미명시=상속.
  화이트리스트 v1(구현 확정): `enable_thinking` · `stream`(선호 — 능력 true일 때만 유효).
  **temperature는 제외** — 기존 `AgentConfig.temperature`(스펙 077)가 이미 에이전트 층 정본이라
  이중 거처를 피한다(단일 거처 원칙). 이 스펙은 thinking·stream의 **에이전트 층 공백**을 채운다.
- **스트리밍 유효값** = `capabilities.streaming AND 설정.stream(기본 true)` — 능력 false면 협상
  불가 단건, true면 층별로 끌 수 있음.

## 구현

- **P1 스키마**: capabilities 컬럼(JSONB, server_default 스트리밍 true) — alembic 1리비전
  (한 번에 완성·단일 head·중복 0 검증 — 회고 177 규율). 스키마/serializer 노출.
- **P2 실행 대응**: model_cfg에 capabilities 동봉 → LLM 클라이언트 생성 시
  `disable_streaming=not streaming능력`(LangChain이 astream을 ainvoke로 접어 완성문 1회 yield —
  SSE 계약·클라이언트 무변경). pins/버전 경로도 같은 필드 관통.
- **P3 표시**: trace `responseMode: "streaming"|"single"` + 메시지 메타 **배지 "단건"**(스트리밍은
  무배지 — 기본이 조용) + 단건 대기 중 빈 말풍선에 "생성 중…(단건 모델 — 완성 후 표시)" 라벨.
- **P4 admin 폼 2곳**: ①모델 폼 — 능력 체크박스 3종 + 사용 기본(enable_thinking·stream)
  가시화 ②에이전트 폼 — "모델 설정 오버라이드" 섹션(화이트리스트 키, 모델 기본값을 placeholder로
  보여주고 비우면 상속 — 상속/오버라이드가 눈에 보이게).
- **P5 검증**: verify_408(21/21) — ①caps.streaming=false → 정상 응답+responseMode=single ②캐스케이드
  실측(모델 기본→에이전트 modelParams→세션 오버라이드 3층 우선순위, enable_thinking·stream 각각) ③능력
  불가침(에이전트가 stream 켜도 능력 false면 단건) ④캐시 회전(능력 PUT 후 재호출이 새 능력 반영 —
  codex P1①) ⑤세션 층(overrides.modelParams — codex P1③). e2e: 단건 배지+기존 3종 무회귀.
  make test SUITE_OK(배타 89/0/격리0)+metrics-fast.

## OUT

- 화이트리스트 밖 키(max_tokens 등 — 컨텍스트 예산 계약과 함께 별도)·키별 검증 고도화.
- 비전 게이트·이미지 첨부(C안), 능력 자동 탐지(probe).
- A2A 서빙 카드의 streaming 선언 제어(현행 유지).

## 완료 기준

- [x] verify_408 21/21(U1-U3·H1-H6) + e2e(단건 배지) + 기존 e2e 3종 무회귀.
- [x] make test SUITE_OK(배타 89/0/격리0) + metrics-fast.
- [x] codex 스팟 — P1×3(캐시 회전·노드 modelParams 관통·세션 층)+P2(파이프라인 trace 거짓 배지)
      전부 반영. responseMode는 노드 없는 직접 경로에만 부여(노드형 모드 혼재 시 턴-단위 단일값
      정의 불가 → 침묵이 정직).
