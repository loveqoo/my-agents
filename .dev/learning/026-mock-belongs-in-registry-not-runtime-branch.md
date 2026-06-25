# 026 — Mock/스텁은 런타임 분기가 아니라 레지스트리 데이터 + 계약 구현으로

날짜: 2026-06-25
맥락: [스펙 024](../../docs/spec/024-mock-llm-registry-model.md), `mock_remote.py`/`seed.py`, [[012-runtime-config-single-source]], [[025-seed-mock-drift-needs-migration-and-shared-constant]]

## 배운 것
런타임이 **단일 소스만 읽도록**([012]) 설계돼 있으면, 새 동작(mock/스텁/테스트 더블)을
넣을 때 `if mock: ...` 같은 **런타임 특수분기를 추가하지 마라**. 대신 두 가지만 한다:

1. **그 단일 소스에 들어갈 데이터**를 등록한다 — 여기선 레지스트리 `models` 테이블의
   `mock-llm` 행(`provider=openai-compatible`, `base_url`=mock 엔드포인트, `is_default=False`).
2. **그 데이터가 기대하는 계약**을 구현한다 — `build_agent`가 `ChatOpenAI`로 치는
   `{base_url}/chat/completions`(OpenAI 호환 스트림/비스트림 + `/models` list).

그러면 런타임(`build_agent`)은 mock의 존재를 **전혀 모른 채** 평소처럼 base_url을 호출하고,
mock은 일반 경로로 결정적으로 돈다. 특수분기 0 → [012] 불변식 유지 + 테스트 경로 = 실제 경로.

## 왜 중요
- `if mock:` 분기는 **검증 가치를 깎는다** — "mock 경로 통과"가 실제 경로를 안 거치므로.
  데이터+계약 방식은 진짜 langgraph 노드를 통과시켜 검증이 정직해진다.
- 분기는 번진다(폴백·probe·UI 곳곳에 `if`). 데이터는 한 곳(레지스트리)에 모인다 → 025의
  "단일 소스로 묶어 재발 방지"와 같은 결.

## 가드
- **`is_default=False` 필수.** 스텁을 기본으로 두면 모든 폴백이 스텁으로 샌다([012] 위험).
  명시 선택해야만 발동하게.
- **self-주소 env와 외부-배포 env를 분리.** 스텁 엔드포인트가 "이 서비스 자신"을 가리키면
  그 base는 *self-주소 env*(예 `MOCK_LLM_BASE_URL`)다. *외부 배포를 가리키는 env*
  (예 `REMOTE_AGENT_BASE`)와 기본값이 우연히 같아도 **묶지 마라** — 운영에서 외부로 잘못 파생된다.
- **라이브 DB엔 마이그레이션 병행**(025) — seed는 빈 DB에서만 돈다.

## 적용 시점
"라이브 의존 없이 결정적으로 돌릴 더블이 필요하다" / "테스트용 모델·프로바이더·툴을 끼우고 싶다"
— 런타임에 분기 넣기 전에, 그게 단일 소스에 **데이터로** 들어갈 수 있는지부터 본다.
