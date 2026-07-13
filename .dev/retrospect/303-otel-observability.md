# 303 — 관측 계층 OTEL 전환 (스펙 328)

## 무엇을 했나

회사 이식의 남은 숙제. 사용자 우려("Langfuse는 실제로 돌리려면 인프라가 많이 필요")를 전제로 —
**Langfuse 인프라를 세우는 게 아니라 방출을 OTLP 표준으로 바꿔 수신 선택을 뒤로 미룸**.
`observability.py` 내부만 교체(부착 4곳 시그니처 무변경), langfuse 의존 제거, 자작 thin
LangChain→OTEL 콜백(루트·llm·tool 3종 span만). 검증 인프라 상한 = Jaeger 컨테이너 1개(합의 준수).

## 핵심 배운 것

### 1) 좋은 시임(seam)은 리팩터를 "내부 교체"로 만든다 — 118의 복리
스펙 118이 관측을 `with_trace()` 한 함수 뒤에 격리해 둔 덕에, 백엔드 전환이 **호출부 4곳 diff 0**으로
끝났다. callbacks 병합 3분기(codex 118 P2) 같은 방어 시맨틱도 그대로 승계. "한 겹 추상화"는 만들 때
비용이지만 갈아탈 때 회수된다 — 회사 이식에서 또 회수될 것(endpoint 주소만 변경).

### 2) `ignore_agent`가 tool 이벤트를 게이트한다 — 라이브 측정만 잡는 함정
자작 콜백에서 `ignore_agent=True`(에이전트 이벤트 무관심)로 뒀더니 **tool span이 소리 없이 빠졌다**.
langchain_core 콜백 매니저가 역사적 기벽으로 `on_tool_start`를 `ignore_agent` 플래그에 게이트한다
(도구가 "agent" 콜백군이던 시절 잔재). 단위 테스트는 핸들러를 **직접 호출**해서 이 게이트를 안 타
초록이었고, **라이브 Jaeger 조회(도구 시나리오 태우고 span 확인)만이** 잡았다 — 계측 코드의 검증은
계측 대상 프레임워크의 **디스패치 경로를 관통**해야 완성(직접 호출 단위는 절반).

### 3) 외부 전송 표면은 "안 싣는 것"이 설계다
span에 이름·모델·토큰 수·에러 타입만 싣고 프롬프트·인자·결과 본문은 **의도적으로 배제**(상세는 내부
인스펙터 소유). U7이 "본문 문자열이 속성 어디에도 없음"을 단언 — 유출 방지를 기본값이 아니라
**테스트로 고정**했다. 반대로 세션·유저 id는 상관관계용으로 의도 탑재(구분을 스펙에 명시).

### 4) 중간 chain은 span 대신 링크 — 소음과 트리의 양립
LangGraph는 노드마다 chain 이벤트를 쏟는다. 전부 span으로 만들면 소음, 안 만들면 llm/tool의 부모가
끊긴다. **span은 루트·llm·tool만 만들되 `_parents`에 링크를 전부 기록**해 조상 탐색으로 잇는 설계가
둘을 양립시켰다(Jaeger 화면: 루트→llm→tool 래퍼→내부 어댑터 tool의 깨끗한 4층). 도구 2층(래퍼+어댑터)
은 contextvar 콜백 전파의 자연 산물 — 억제하지 않고 정직하게 노출(중첩이 곧 정보).

## 검증
- U 17/17(인프라 0, InMemory exporter): 게이팅·병합 3분기 승계·span 트리/속성·에러 status·예외
  삼킴·본문 미탑재.
- 라이브: Jaeger all-in-one 1컨테이너 + .env endpoint + api 재기동 → suite 실채팅(route·plan-tool)
  → Jaeger API/UI에서 트레이스 확인(스크린샷 — 루트 1.1s→llm 618ms→tool 27ms→llm 438ms).
- 회귀: suite 시나리오 2종 통과(관측 켠 채 — 채팅 경로 무영향 증명)·lint/format/mypy 클린.
- codex 적대(유출·수명·게이팅·잔존 여집합).

관련: [[probe-deeper-before-concluding]](단위 초록≠디스패치 관통) · 스펙 118(시임 원형)·205(실측 캡처 병행) · 회사 이식: [[company-integration-context]] 숙제 소진
