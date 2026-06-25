# 023 — 에이전트 파운데이션 모델을 등록 구성에 맞게 정정

## 배경 / 증상

등록된 에이전트들의 **파운데이션 모델이 가상명**(레지스트리에 없는 이름)을 가리킨다.
런타임(`chat.py`)은 `ModelConfig.name` 기준으로 매칭하므로 매 실행 시 기본 chat
모델로 **폴백**해서 돌긴 하나, 설정상으론 존재하지 않는 모델을 가리켜 "이 에이전트가
무슨 모델로 도는가"가 화면과 실제가 어긋난다 (learning 012: 실행=등록된 설정이어야 함).

### 실측 현황 (GET /models, GET /agents)

실제 등록 모델은 둘뿐: `qwen3.6-35b`(chat·기본), `multilingual-e5-large`(embedding·기본).

| 에이전트 | source | 현재 model | 등록? |
|---|---|---|---|
| Research Assistant `agt_rsch_7f3a91` | ui | `claude-sonnet-4` | ❌ |
| Code Reviewer `agt_rvw_2b91c4` | ui | `gpt-4o` | ❌ |
| Ops Copilot `agt_ops_5c0833` | ui | `claude-haiku-4` | ❌ |
| Personal Secretary `agt_sec_9d4417` | ui | `claude-sonnet-4` | ❌ |
| Doc Translator `agt_xlt_a17c33` | code | `claude-sonnet-4` | ❌ (원격실행, 런타임 미사용) |

## 결정 (사용자 확인)

- **범위: 파운데이션 모델만.** 벡터테이블 임베딩명·MCP 가상 엔드포인트 등 다른 데모
  데이터는 UI를 채우는 의도된 목업이라 유지.
- **적용: 소스 + 마이그레이션.** seed/mock/UI 기본값을 정정하고, 이미 시드된 라이브 DB
  행도 Alembic 데이터 마이그레이션으로 등록 모델로 정정한다.

## 변경

1. **`packages/api/src/api/seed.py`** — `CHAT_MODEL_NAME = "qwen3.6-35b"` 상수 도입,
   `ModelConfig(name=...)`와 `AGENTS`·translator·`code_cfg`의 model을 모두 이 상수로.
   (모델 등록명과 에이전트 참조가 단일 소스로 묶여 다신 어긋나지 않음.)
2. **`admin/src/admin/mockData.ts`** — 에이전트 5건의 `model`을 `qwen3.6-35b`로
   (API 다운 시 폴백 표시 데이터 일치).
3. **`admin/src/admin/views/AgentsView.tsx`**
   - `blankForm`: 빈 폼 model 기본값을 하드코딩 가상명 대신 **등록된 첫 chat 모델**로
     (persona 기본값과 동일한 데이터 기반 패턴).
   - `RegisterAgentModal` mock 페치 결과 model → `qwen3.6-35b`.
4. **신규 Alembic 마이그레이션** (down_revision = `d2e3f4a5b6c7`) — 데이터 기반 정정:
   레지스트리의 **기본 chat 모델**을 골라, model이 `models`(kind=chat)에 없는 에이전트의
   `agents.model`·`agents.config['model']`·`agent_versions.config['model']`을 갱신.
   기본 chat 모델이 없으면(빈 DB) no-op. 다운그레이드는 비가역(no-op).

## 검증

1. `tsc --noEmit` 무오류.
2. 마이그레이션 적용 후 GET /agents → 모든 model이 `qwen3.6-35b`.
3. 빈 DB 재시드 시뮬레이션(또는 코드 검토)로 seed 경로도 일치 확인.
4. 타자 검증(codex)으로 마이그레이션 SQL·폴백 안전성 비판 리뷰.

## 타자 검증 (codex, GATE: PASS — P1 없음)

P2 3건 처리:
- **P2-1 (반영)** `blankForm`/late-fill의 `models[0]?.name` → `models.find(m=>m.kind==='chat')?.name`.
  실제로는 `listModels('chat')`로 페치해 안전했으나, 호출부 변경에 견고하도록 명시 필터로.
- **P2-2 (수용·미변경)** 마이그레이션 `ORDER BY name LIMIT 1` 다중 default 선택. seed가
  단일 default chat을 보장하는 불변식이 성립하고, `ORDER BY`는 런타임(`chat.py`의
  무순서 `.first()`)보다 오히려 더 결정적이라 그대로 둠.
- **P2-3 (반영)** agents 루프가 `config.model` 키 부재 시 키를 추가하던 것을, `agent_versions`와
  동일하게 **키가 있고 미등록일 때만** 정정하도록 변경(불필요한 데이터 변형 방지). 시드 행은
  모두 키가 존재해 라이브 결과는 동일.

## 완료 조건

- [x] seed.py 상수화 + 5개 에이전트 model 정정
- [x] mockData.ts 5건 정정
- [x] AgentsView 빈 폼/mock 페치 기본값 정정 (chat 명시 필터)
- [x] 마이그레이션: 라이브 DB 에이전트 model = qwen3.6-35b (agents 5 / config 5 / agent_versions 11)
- [x] tsc 무오류 + 타자 검증 통과 (codex GATE PASS)
- [ ] **main 머지 금지** (브랜치에서 사용자 직접 테스트)
