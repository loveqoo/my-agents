# 336 — 모델 능력 관리(스펙 408)

## 발단

개발자 "스트리밍 처리 여부 관리 + 대화에 스트리밍 표시". 논의로 2층 원칙을 확정:
**능력(capability)=모델이 선언하는 사실(불가침) / 사용(usage)=능력의 부분집합에서 선택**.
이어 "각 모델에 속한 설정들 + 에이전트 오버라이드"로 확장 → 3층 설정 캐스케이드.
실측 근거: MLX 가이드(스트리밍=능력 있음·클라가 켬 / thinking=모드 보유·클라가 관리).

## 무엇을 했나

- **능력 층**: `ModelConfig.capabilities` JSONB(`{streaming,thinking,vision}`, server_default
  streaming=true) — alembic 1리비전. 에이전트는 없는 능력을 켤 수 없음(부분집합 원칙).
- **설정 캐스케이드 3층**: 모델 params(기본) → 에이전트 `config.modelParams`(화이트리스트
  `enable_thinking`·`stream`만) → 세션 오버라이드(per-key 병합). 미명시=상속.
- **유효 스트리밍** = `capabilities.streaming AND params.stream` → `disable_streaming`으로
  LangChain이 astream을 ainvoke로 접어 완성문 1회 yield(SSE 계약·클라 무변경).
- **표시**: trace `responseMode="single"` + 메시지 메타 "단건" 배지(스트리밍은 무배지).

## 배운 것 (복리 후크)

- **2층은 이 저장소의 반복 패턴이다** — A2A 카드 `capabilities.streaming`, MCP `enabled_tools`,
  오케스트레이션 allowlist 전부 "선언된 능력 ⊇ 선택된 사용". 새 능력 축(비전·오디오)도 같은 틀에
  얹으면 되고, "에이전트가 없는 능력을 켤 수 있나?"는 항상 No가 정답. **불가침을 코드로**:
  능력은 캐스케이드 화이트리스트에 **없다**(층으로 못 내림).

- **단일 거처(single-home) 원칙** — temperature를 modelParams 화이트리스트에 넣고 싶었으나
  기존 `AgentConfig.temperature`(스펙 077)가 이미 에이전트 층 정본. 이중 거처는 "둘 중 뭐가 이기나"
  버그의 씨앗. **새 축을 추가할 때 기존 정본이 있는지 먼저 확인** → 있으면 그 자리에 합류, 새 통로
  안 판다. 화이트리스트를 thinking·stream으로 좁힌 이유.

- **라이브 사실은 pin/캐시 무효화 축을 동반해야** (codex P1①) — 능력은 "지금 서버가 스트리밍을
  껐나"라는 **라이브 사실**이라 블록 버전 payload에서 제외(pin해선 안 됨)했다. 그런데 그래프
  지문(`_graph_fingerprint`)에 caps를 안 넣으면 `streaming true→false` PUT 뒤에도 캐시된
  `ChatOpenAI(disable_streaming=False)`가 재사용된다. **"버전 안 올림"과 "캐시 무효화 안 함"은
  다른 결정** — 버전은 안 올려도(라이브라서) 지문에는 넣어야 참조 중 편집이 즉시 반영된다.
  일반화: *캐시 키에 안 들어간 축은 조용히 낡는다* — 라이브로 바뀌는 값은 반드시 지문에 넣어라.

- **관통(pass-through)은 명시 경로마다 확인** (codex P1②) — 에이전트 modelParams를 `_resolve_model`
  에서만 병합하면, pipeline 노드가 **명시 모델**을 쓸 때 `_chat_model_cfg` 결과가 그대로 주입돼
  stream·thinking이 모델 기본으로 회귀한다. temperature가 `ctx.params`로 전 노드에 관통되는 선례가
  있으니 modelParams도 노드 명시 모델에 관통해야 계약이 맞다. **"에이전트 층 설정"이라 말했으면
  에이전트가 고르는 모든 실행 경로(직접·노드형·노드 명시 모델)에서 확인** — 주 경로만 보면 샌다.

- **여러 모드 혼재 시 턴-단위 단일값은 침묵이 정직** (codex P2) — pipeline root=streaming/node=single
  이면 하나의 `responseMode`로 턴을 표시할 수 없다. **거짓 배지보다 무필드**가 낫다 →
  responseMode를 **노드 없는 직접 경로에만** 부여(`if ctx.nodes_resolved is None`). "정의할 수 없는
  집계값은 만들지 말고 침묵" — 407의 "or 폴백은 빈값도 폴백" 정직화와 같은 결.

## 검증

verify_408 21/21(U1-U3 단위 + H1-H6 API: H5 캐시 회전·H6 세션 층). e2e 단건 배지(사전 셋업
비스트리밍 모델 → "단건" 태그). 기존 e2e 3종(404/405/406) 무회귀. make test SUITE_OK(배타 89/0/
격리0). metrics-fast. codex P1×3+P2 전부 반영 후 재검.

- **자업자득 재확인**: e2e 3종이 처음 FAIL한 건 코드가 아니라 **dev DB에 남은 e2e 잔재**
  (e2e-single-agent-408 에이전트·kb-v405-* 컬렉션). "그물 실행=배타 구간"과 같은 뿌리 —
  db층은 라이브 dev DB를 공유하므로 **셋업 잔재도 정리까지 같은 스크립트 수명에 묶어야** 거짓
  회귀가 안 생긴다.
