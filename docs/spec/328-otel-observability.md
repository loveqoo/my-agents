# 328 — 관측 계층 OTEL 전환 (Langfuse SDK 직결 제거)

## 배경 / 동기

회사 이식의 남은 숙제(관측 백엔드 교체 가능성). 현재 관측은 `observability.py` 한 파일에 격리된
Langfuse SDK 직결(env 키 있을 때만 켜지는 inert-until-configured, 스펙 118)이나, Langfuse를 실제로
받으려면 무거운 서버 스택(ClickHouse·Redis·S3)이 필요하다(사용자 지적). **방출을 OTEL 표준(OTLP)으로
바꿔 수신 백엔드 선택을 뒤로 미룬다** — 회사=기존 Grafana 스택에 주소만, 개인=Jaeger 컨테이너 1개,
Langfuse도 OTLP를 받으므로 원하면 같은 배관에 꽂는다. **이 스펙에서 Langfuse 인프라는 세우지 않는다**
(사용자 합의 전제 — 검증 인프라 상한 = Jaeger all-in-one 컨테이너 1개).

## 설계

### 원칙 유지 (스펙 118 계약 그대로)
- **inert-until-configured**: `OTEL_EXPORTER_OTLP_ENDPOINT` env가 있을 때만 켜짐, 없으면 무동작 [].
- **관측은 부가물이지 하중이 아니다**: 핸들러 전 구간 예외 삼킴(채팅 경로 무영향), 비밀 로그 금지.
- **호출부 무변경**: `with_trace(config, name, session_id, user_id, metadata)` 시그니처 유지 —
  부착 4곳(chat·chat_approval·chat_stream a2a·eval_runner) 그대로. callbacks 병합 시맨틱
  (None/list/CallbackManager 3분기, codex 118 P2) 보존.

### 교체 내용
1. **의존성**: `langfuse` 제거 → `opentelemetry-sdk` + `opentelemetry-exporter-otlp-proto-http`
   (http/protobuf — grpc 네이티브 의존 없음. 표준 env `OTEL_EXPORTER_OTLP_ENDPOINT`·
   `OTEL_SERVICE_NAME`을 exporter가 자동 소비).
2. **자작 thin LangChain 콜백**(서드파티 계측 라이브러리 불채택 — openinference/traceloop는 의존 무게
   대비 이득 없음, 우리가 내는 이벤트는 llm·tool·루트뿐): `run_id→span` 맵으로 LangChain 콜백 트리를
   OTEL span 트리로:
   - 루트(chain, parent 없음): `run_name` span + `session.id`/`user.id`/`agent.name` 속성.
   - `on_chat_model_start/end`: `llm {model}` span — model·input/output 토큰(usage)·지연.
   - `on_tool_start/end/error`: `tool {name}` span — 상태·에러 타입(마스킹은 기존 trace 경로 소관,
     span엔 이름·수치만 싣고 **인자·본문은 싣지 않는다** — 외부 전송 표면 최소화).
3. **TracerProvider 싱글턴**: lazy 1회 초기화(BatchSpanProcessor), FastAPI lifespan 종료 시 flush.
4. **메타 키 정리**: `langfuse_session_id/user_id` → `session_id/user_id`(중립) — 핸들러가 소비.

## 범위 밖 (OUT)
- 메트릭(Prometheus) — 회사 층(과투자 금지). 트레이스만.
- A2A 원격 위임의 컨텍스트 전파(traceparent 헤더) — 후속 후보.
- 로그-트레이스 상관관계.

## 검증
- **U(인프라 0)**: `InMemorySpanExporter`로 — 게이팅(미설정=[]·설정=핸들러)·mock 체인/LLM/도구
  이벤트→span 트리·속성(모델·토큰·세션) 단언·핸들러 예외 삼킴(깨진 이벤트에도 채팅 경로 무영향)·
  callbacks 병합 3분기 무회귀.
- **F(컨테이너 1개)**: Jaeger all-in-one 기동 → in-process ASGI로 env 설정 채팅 1회 →
  Jaeger HTTP API에서 해당 trace 조회 단언.
- **실사용**: `.env`에 endpoint 추가·api 재기동 → 플레이그라운드 채팅 → Jaeger UI 스크린샷(육안).
- 회귀: 채팅·suite 부분·metrics-fast 패널.

## 완료 조건
- langfuse 의존 grep 0(코드·pyproject). 미설정 환경 완전 무동작(기존과 동일).
- Jaeger에서 채팅 1회의 span 트리(루트→llm→tool) 확인(스크린샷).
- 부착 4곳 무변경 diff. 회귀 그린.
