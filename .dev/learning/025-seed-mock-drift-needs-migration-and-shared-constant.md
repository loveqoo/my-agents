# 025 — 시드/목업이 레지스트리와 어긋나면: 데이터 마이그레이션 + 단일 상수

날짜: 2026-06-25
맥락: [스펙 023](../../docs/spec/023-agent-foundation-model-realign.md), `seed.py`/`mockData.ts`/`AgentsView.tsx`, [[012-runtime-config-single-source]]

## 증상
시드된 에이전트 5건의 `model`이 레지스트리에 없는 **가상명**(`claude-sonnet-4`/`gpt-4o`/
`claude-haiku-4`)을 가리켰다. 런타임([012])은 미등록 모델을 만나면 기본 chat 모델로 **폴백**해
돌긴 하나, "이 에이전트가 무슨 모델로 도는가"가 화면과 실제가 어긋났다.

## 배운 것
1. **소스 수정만으로는 라이브가 안 고쳐진다.** `seed.py`/`mockData.ts`를 고쳐도 *이미 시드된*
   DB 행은 그대로다. `seed_if_empty`는 빈 DB에서만 돈다 → 라이브 정정은 **Alembic 데이터
   마이그레이션**이 필요. (마이그레이션은 가상명을 하드코딩하지 말고 `models` 테이블에서
   **기본 chat 모델을 동적으로** 골라 적용 — 빈 DB면 no-op 하고 seed가 채움.)
2. **참조를 단일 상수로 묶어 재발을 막는다.** `CHAT_MODEL_NAME` 하나로 `ModelConfig(name=...)`과
   에이전트 참조(`AGENTS`/translator/`code_cfg`)를 묶으면 등록명과 참조가 **구조적으로** 못 어긋난다.
   UI 폼 기본값도 하드코딩 대신 **등록된 첫 chat 모델**(`models.find(m=>m.kind==='chat')`)에서.
3. **두 저장 위치를 다 본다.** model은 `agents.model` 컬럼과 `config.model`(JSONB), 그리고
   `agent_versions.config.model`에 흩어져 있다. 런타임이 읽는 건 `config.model`이지만 UI는 컬럼을
   보여줘 셋 다 정정해야 화면=실제가 맞는다.

## 마이그레이션 패턴 (codex 반영)
- **키 부재 시 추가하지 않는다**: `config.model` 키가 *있고 미등록*일 때만 정정. 없는 키를 새로
  넣으면 불필요한 데이터 변형(`agents`/`agent_versions` 처리 기준 불일치). `"model" in cfg and ...`로 가드.
- **명시 필터 > 인덱스 접근**: UI 기본값을 `models[0]`로 잡으면 페치가 chat-only가 아닐 때
  embedding 모델이 샌다. `.find(m=>m.kind==='chat')`로 의도를 코드에 박는다.
- 다중 기본값 선택은 `ORDER BY name LIMIT 1`로 결정적이게(런타임 무순서 `.first()`보다 안전) —
  단 seed가 단일 기본값을 보장하는 게 1차 방어([012] "kind별 단일 기본값").

## 적용 시점
시드/목업 데모 데이터를 다룰 때, 또는 "화면에 보이는 설정이 실제 실행과 다르다"는 보고를 받을 때.
소스만 고치고 끝내지 말고 — 이미 영속된 행이 있는지, 단일 소스로 묶을 수 있는지 함께 본다.
